from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner.agent_session_storage import (
    AgentSessionStorageConflictError,
    create_agent_session,
    fetch_agent_events,
    fetch_agent_session,
    list_agent_sessions,
    transition_agent_session,
    verify_agent_event_hash_chain,
)
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.sqlite_migrations import (
    AGENT_SESSION_MIGRATION_NAME,
    SCHEMA_LEDGER_AHEAD_ERROR,
    RemoteRunnerSQLiteSchemaError,
    initialize_or_migrate_runtime_db,
)
from apps.remote_runner.storage_core import get_connection
from tests.helpers.reference_database import make_remote_runner_config


AGENT_SESSION_V18_TABLES = frozenset(
    {"agent_approvals", "agent_events", "agent_plan_revisions", "agent_sessions"}
)


def _configured_runner(tmp_path: Path):
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    return cfg


def _create_session(cfg, *, request_id: str = "create-qc-1", summary: str = "Run FASTQ QC"):
    return create_agent_session(
        cfg,
        project_id="project-qc",
        goal={
            "summary": summary,
            "successCriteria": ["Produce a reviewable MultiQC report"],
        },
        budget={
            "maxModelTurns": 8,
            "maxToolCalls": 12,
            "maxReplans": 3,
            "maxRetries": 2,
            "maxWallClockSeconds": 3600,
        },
        creation_request_id=request_id,
        created_by="user-1",
    )


def test_agent_session_creation_is_idempotent_and_audited(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)

    first = _create_session(cfg)
    replay = _create_session(cfg)

    assert replay == first
    assert first["contractVersion"] == "agent-session.v1"
    assert first["status"] == "created"
    assert first["stateVersion"] == 1
    assert first["planGeneration"] == 0
    assert fetch_agent_session(cfg, first["sessionId"]) == first
    assert [item["sessionId"] for item in list_agent_sessions(cfg)] == [first["sessionId"]]

    events = fetch_agent_events(cfg, first["sessionId"])
    assert len(events) == 1
    assert events[0]["eventType"] == "agent.session_created"
    assert events[0]["sequence"] == 1
    assert events[0]["prevEventHash"] is None
    assert verify_agent_event_hash_chain(cfg, first["sessionId"]) == {
        "valid": True,
        "checked": 1,
        "reason": None,
    }


def test_agent_session_creation_detects_idempotency_conflict_and_sensitive_fields(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    _create_session(cfg)

    with pytest.raises(AgentSessionStorageConflictError, match="AGENT_SESSION_CREATION_REQUEST_CONFLICT"):
        _create_session(cfg, summary="Different goal")

    with pytest.raises(ValueError, match="AGENT_SESSION_SECRET_LIKE_KEY_FORBIDDEN"):
        create_agent_session(
            cfg,
            project_id="project-qc",
            goal={"summary": "unsafe", "context": {"apiKey": "must-not-persist"}},
            budget={
                "maxModelTurns": 1,
                "maxToolCalls": 0,
                "maxReplans": 0,
                "maxRetries": 0,
                "maxWallClockSeconds": 60,
            },
            creation_request_id="create-unsafe",
            created_by="user-1",
        )

    with pytest.raises(ValueError, match="AGENT_SESSION_SECRET_LIKE_KEY_FORBIDDEN"):
        create_agent_session(
            cfg,
            project_id="project-qc",
            goal={"summary": "unsafe", "context": {"nested": {"db_password": "no"}}},
            budget={
                "maxModelTurns": 1,
                "maxToolCalls": 0,
                "maxReplans": 0,
                "maxRetries": 0,
                "maxWallClockSeconds": 60,
            },
            creation_request_id="create-unsafe-nested",
            created_by="user-1",
        )


def test_agent_session_transitions_use_optimistic_concurrency_and_command_idempotency(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    session = _create_session(cfg)
    session_id = session["sessionId"]
    command = {
        "expected_state_version": 1,
        "event_type": "agent.plan_requested",
        "to_status": "planning",
        "request_id": "plan-request-1",
        "actor": "user-1",
        "idempotency_key": "plan-command-1",
        "payload": {"planner": {"adapterId": "fixture-planner"}},
        "plan_generation": 1,
        "planner": {"adapterId": "fixture-planner", "modelRef": "fixture-model"},
    }

    first = transition_agent_session(cfg, session_id, **command)
    replay = transition_agent_session(cfg, session_id, **command)

    assert first["replayed"] is False
    assert replay["replayed"] is True
    assert replay["event"] == first["event"]
    assert replay["session"] == first["session"]
    assert first["session"]["status"] == "planning"
    assert first["session"]["stateVersion"] == 2
    assert first["session"]["planGeneration"] == 1

    with pytest.raises(AgentSessionStorageConflictError, match="AGENT_COMMAND_IDEMPOTENCY_CONFLICT"):
        transition_agent_session(cfg, session_id, **(command | {"payload": {"changed": True}}))

    with pytest.raises(AgentSessionStorageConflictError, match="AGENT_SESSION_STATE_VERSION_CONFLICT"):
        transition_agent_session(
            cfg,
            session_id,
            expected_state_version=1,
            event_type="agent.plan_validated",
            to_status="awaiting_approval",
            request_id="validate-stale",
            actor="planner",
            idempotency_key="validate-stale",
            payload={"valid": True},
        )


def test_agent_session_approval_is_bound_to_plan_hash_and_event_chain(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    session_id = _create_session(cfg)["sessionId"]
    planning = transition_agent_session(
        cfg,
        session_id,
        expected_state_version=1,
        event_type="agent.plan_requested",
        to_status="planning",
        request_id="plan-1",
        actor="user-1",
        idempotency_key="plan-1",
        payload={"requested": True},
        plan_generation=1,
    )
    plan_hash = "a" * 64
    awaiting = transition_agent_session(
        cfg,
        session_id,
        expected_state_version=planning["session"]["stateVersion"],
        expected_plan_generation=1,
        event_type="agent.plan_validated",
        to_status="awaiting_approval",
        request_id="validate-1",
        actor="planner",
        idempotency_key="validate-1",
        payload={"draftId": "wfd_qc", "planHash": plan_hash},
        active_draft_id="wfd_qc",
        active_draft_revision=1,
        active_plan_hash=plan_hash,
    )

    with pytest.raises(AgentSessionStorageConflictError, match="AGENT_SESSION_PLAN_HASH_CONFLICT"):
        transition_agent_session(
            cfg,
            session_id,
            expected_state_version=awaiting["session"]["stateVersion"],
            expected_plan_hash="b" * 64,
            event_type="agent.approval_granted",
            to_status="ready_to_run",
            request_id="approve-wrong",
            actor="user-1",
            idempotency_key="approve-wrong",
            payload={"decision": "approve"},
        )

    approved = transition_agent_session(
        cfg,
        session_id,
        expected_state_version=awaiting["session"]["stateVersion"],
        expected_plan_hash=plan_hash,
        expected_plan_generation=1,
        event_type="agent.workflow_revision_compiled",
        to_status="ready_to_run",
        request_id="approve-1",
        actor="user-1",
        idempotency_key="approve-1",
        payload={"decision": "approve", "workflowRevisionId": "wfrev_qc"},
        workflow_revision_id="wfrev_qc",
    )

    assert approved["session"]["workflowRevisionId"] == "wfrev_qc"
    events = fetch_agent_events(cfg, session_id)
    assert [item["sequence"] for item in events] == [1, 2, 3, 4]
    assert events[-1]["prevEventHash"] == events[-2]["eventHash"]
    assert verify_agent_event_hash_chain(cfg, session_id)["valid"] is True


def test_agent_event_ledger_is_database_immutable(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    session_id = _create_session(cfg)["sessionId"]

    with get_connection(cfg) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_EVENT_IMMUTABLE"):
            connection.execute(
                "UPDATE agent_events SET payload_json = '{}' WHERE session_id = ?",
                (session_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_EVENT_IMMUTABLE"):
            connection.execute("DELETE FROM agent_events WHERE session_id = ?", (session_id,))


def test_runtime_schema_migrates_v17_agent_session_tables(tmp_path: Path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    initialize_or_migrate_runtime_db(db_path)
    with sqlite3.connect(db_path) as connection:
        fresh_schema = _agent_schema_snapshot(connection)
        _downgrade_agent_schema_to_v17(connection)

    initialize_or_migrate_runtime_db(db_path)
    with get_connection(cfg) as connection:
        migrated_schema = _agent_schema_snapshot(connection)
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'agent_%'"
            ).fetchall()
            if row[0] in AGENT_SESSION_V18_TABLES
        }
        migration = connection.execute(
            "SELECT name FROM schema_migrations WHERE version = ?",
            (18,),
        ).fetchone()

    assert names == AGENT_SESSION_V18_TABLES
    assert migrated_schema == fresh_schema
    assert migration["name"] == AGENT_SESSION_MIGRATION_NAME


def test_runtime_schema_rejects_partial_v17_rewind_before_writing(
    tmp_path: Path,
) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    initialize_or_migrate_runtime_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TRIGGER agent_approvals_no_delete")
        connection.execute("DROP TRIGGER agent_approvals_no_update")
        connection.execute("DROP TRIGGER agent_events_no_delete")
        connection.execute("DROP TRIGGER agent_events_no_update")
        connection.execute("DROP TRIGGER agent_plan_revisions_no_delete")
        connection.execute("DROP TRIGGER agent_plan_revisions_no_update")
        connection.execute("DROP TABLE agent_approvals")
        connection.execute("DROP TABLE agent_events")
        connection.execute("DROP TABLE agent_plan_revisions")
        connection.execute("DROP TABLE agent_sessions")
        connection.execute("DELETE FROM schema_migrations WHERE version = 18")
        connection.execute("PRAGMA user_version = 17")
        ledger_before = connection.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        schema_before = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()

    with pytest.raises(RemoteRunnerSQLiteSchemaError, match=SCHEMA_LEDGER_AHEAD_ERROR):
        initialize_or_migrate_runtime_db(db_path)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 17
        assert connection.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall() == ledger_before
        assert connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall() == schema_before


def _downgrade_agent_schema_to_v17(connection: sqlite3.Connection) -> None:
    for object_type in ("trigger", "table"):
        names = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ? AND name LIKE 'agent_%'",
            (object_type,),
        ).fetchall()
        for (name,) in names:
            quoted_name = '"' + str(name).replace('"', '""') + '"'
            connection.execute(f"DROP {object_type.upper()} {quoted_name}")
    connection.execute("DELETE FROM schema_migrations WHERE version >= 18")
    connection.execute("PRAGMA user_version = 17")


def _agent_schema_snapshot(connection: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    return [
        (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            " ".join(str(row[3]).split()),
        )
        for row in connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE sql IS NOT NULL
                AND (name LIKE 'agent_%' OR tbl_name LIKE 'agent_%')
            ORDER BY type, name
            """
        ).fetchall()
        if str(row[1]) in AGENT_SESSION_V18_TABLES
        or str(row[2]) in AGENT_SESSION_V18_TABLES
    ]
