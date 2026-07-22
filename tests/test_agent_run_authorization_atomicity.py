from __future__ import annotations

import sqlite3
from typing import Any

import pytest

import apps.remote_runner.agent_run_authorization_service as authorization_service
from apps.remote_runner.agent_run_authorization_preview_service import (
    build_agent_run_authorization_preview,
)
from apps.remote_runner.agent_run_authorization_storage import (
    AgentRunAuthorizationStorageConflictError,
)
from apps.remote_runner.storage_core import get_connection
from core.contracts.agent_control_plane_namespace import (
    AGENT_CONTROL_PLANE_SERVER_ID,
)
from core.contracts.agent_run_authorization import (
    AgentRunAuthorizationRequest,
    agent_run_authorization_command_hash,
    agent_run_authorization_run_idempotency_key,
)


pytest_plugins = ("tests.test_agent_fastq_qc_execution_candidate",)


_ACTOR = "user-1"
_FAULT_TRIGGERS = (
    (
        "runs",
        """
        CREATE TRIGGER test_agent_authorization_fail_runs
        AFTER INSERT ON runs
        BEGIN
            SELECT RAISE(ABORT, 'TEST_AGENT_AUTHORIZATION_FAIL_RUNS');
        END
        """,
    ),
    (
        "run_commands",
        """
        CREATE TRIGGER test_agent_authorization_fail_run_commands
        AFTER INSERT ON run_commands
        BEGIN
            SELECT RAISE(ABORT, 'TEST_AGENT_AUTHORIZATION_FAIL_RUN_COMMANDS');
        END
        """,
    ),
    (
        "accepted_event",
        """
        CREATE TRIGGER test_agent_authorization_fail_accepted_event
        AFTER INSERT ON run_events
        WHEN NEW.event_type = 'accepted'
        BEGIN
            SELECT RAISE(ABORT, 'TEST_AGENT_AUTHORIZATION_FAIL_ACCEPTED_EVENT');
        END
        """,
    ),
    (
        "run_jobs",
        """
        CREATE TRIGGER test_agent_authorization_fail_run_jobs
        AFTER INSERT ON run_jobs
        BEGIN
            SELECT RAISE(ABORT, 'TEST_AGENT_AUTHORIZATION_FAIL_RUN_JOBS');
        END
        """,
    ),
    (
        "queued_event",
        """
        CREATE TRIGGER test_agent_authorization_fail_queued_event
        AFTER INSERT ON run_events
        WHEN NEW.event_type = 'run_job_queued'
        BEGIN
            SELECT RAISE(ABORT, 'TEST_AGENT_AUTHORIZATION_FAIL_QUEUED_EVENT');
        END
        """,
    ),
    (
        "idempotency",
        """
        CREATE TRIGGER test_agent_authorization_fail_idempotency
        AFTER INSERT ON idempotency
        BEGIN
            SELECT RAISE(ABORT, 'TEST_AGENT_AUTHORIZATION_FAIL_IDEMPOTENCY');
        END
        """,
    ),
    (
        "agent_run_authorizations",
        """
        CREATE TRIGGER test_agent_authorization_fail_binding
        AFTER INSERT ON agent_run_authorizations
        BEGIN
            SELECT RAISE(ABORT, 'TEST_AGENT_AUTHORIZATION_FAIL_AGENT_RUN_AUTHORIZATIONS');
        END
        """,
    ),
    (
        "evidence_schemas",
        """
        CREATE TRIGGER test_agent_authorization_fail_evidence_schemas
        AFTER INSERT ON evidence_schemas
        BEGIN
            SELECT RAISE(ABORT, 'TEST_AGENT_AUTHORIZATION_FAIL_EVIDENCE_SCHEMAS');
        END
        """,
    ),
    (
        "evidence_events",
        """
        CREATE TRIGGER test_agent_authorization_fail_evidence_events
        AFTER INSERT ON evidence_events
        BEGIN
            SELECT RAISE(ABORT, 'TEST_AGENT_AUTHORIZATION_FAIL_EVIDENCE_EVENTS');
        END
        """,
    ),
)
_EFFECT_TABLES = (
    "runs",
    "run_commands",
    "run_events",
    "run_jobs",
    "idempotency",
    "agent_run_authorizations",
    "evidence_schemas",
    "evidence_events",
)


@pytest.mark.parametrize(("fault_point", "trigger_sql"), _FAULT_TRIGGERS)
def test_authorization_rolls_back_every_effect_when_each_write_fails(
    candidate_case: dict[str, Any],
    fault_point: str,
    trigger_sql: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    request = _matching_request(candidate_case, suffix=fault_point)
    authority_before = _authority_rows(candidate_case)
    assert _effect_counts(cfg) == {table: 0 for table in _EFFECT_TABLES}

    real_create_run = authorization_service.create_run_record_for_connection

    def create_run_with_fault(connection, *args, **kwargs):
        connection.execute(trigger_sql)
        return real_create_run(connection, *args, **kwargs)

    monkeypatch.setattr(
        authorization_service,
        "create_run_record_for_connection",
        create_run_with_fault,
    )

    marker = f"TEST_AGENT_AUTHORIZATION_FAIL_{fault_point.upper()}"
    with pytest.raises(
        (sqlite3.IntegrityError, AgentRunAuthorizationStorageConflictError)
    ) as caught:
        authorization_service.authorize_agent_workflow_run(
            cfg,
            session_id,
            request,
            actor=_ACTOR,
        )

    assert marker in _exception_chain_text(caught.value)
    assert _effect_counts(cfg) == {table: 0 for table in _EFFECT_TABLES}
    assert _authority_rows(candidate_case) == authority_before


def test_internal_idempotency_collision_without_binding_is_never_adopted(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    request = _matching_request(candidate_case, suffix="collision")
    authorization_id = "agrauth_collision"
    attempted_run_id = "run_collision_attempt"
    orphan_run_id = "run_orphan_without_binding"
    command_hash = agent_run_authorization_command_hash(
        session_id,
        _ACTOR,
        request,
    )
    internal_key = agent_run_authorization_run_idempotency_key(
        session_id,
        authorization_id,
        command_hash,
    )
    authority_before = _authority_rows(candidate_case)
    monkeypatch.setattr(
        authorization_service,
        "_new_authorization_id",
        lambda: authorization_id,
    )
    monkeypatch.setattr(
        authorization_service,
        "_new_run_id",
        lambda: attempted_run_id,
    )

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO idempotency (
                server_id, idempotency_key, canonical_payload_hash, run_id, status
            ) VALUES (?, ?, ?, ?, 'accepted')
            """,
            (
                AGENT_CONTROL_PLANE_SERVER_ID,
                internal_key,
                request.expectedRunSpecHash,
                orphan_run_id,
            ),
        )
        connection.commit()

    with pytest.raises(
        AgentRunAuthorizationStorageConflictError,
        match="^AGENT_RUN_AUTHORIZATION_INTERNAL_IDEMPOTENCY_COLLISION$",
    ):
        authorization_service.authorize_agent_workflow_run(
            cfg,
            session_id,
            request,
            actor=_ACTOR,
        )

    assert _effect_counts(cfg) == {
        "runs": 0,
        "run_commands": 0,
        "run_events": 0,
        "run_jobs": 0,
        "idempotency": 1,
        "agent_run_authorizations": 0,
        "evidence_schemas": 0,
        "evidence_events": 0,
    }
    with get_connection(cfg) as connection:
        row = connection.execute(
            """
            SELECT server_id, idempotency_key, canonical_payload_hash, run_id, status
            FROM idempotency
            """
        ).fetchone()
        assert row is not None
        assert dict(row) == {
            "server_id": AGENT_CONTROL_PLANE_SERVER_ID,
            "idempotency_key": internal_key,
            "canonical_payload_hash": request.expectedRunSpecHash,
            "run_id": orphan_run_id,
            "status": "accepted",
        }
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM runs WHERE run_id IN (?, ?)",
                (orphan_run_id, attempted_run_id),
            ).fetchone()[0]
            == 0
        )
    assert _authority_rows(candidate_case) == authority_before


def test_same_derived_key_in_public_server_namespace_does_not_collide(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    request = _matching_request(candidate_case, suffix="public-server-key")
    authorization_id = "agrauth_public_server_key"
    run_id = "run_public_server_key"
    command_hash = agent_run_authorization_command_hash(
        session_id,
        _ACTOR,
        request,
    )
    internal_key = agent_run_authorization_run_idempotency_key(
        session_id,
        authorization_id,
        command_hash,
    )
    monkeypatch.setattr(
        authorization_service,
        "_new_authorization_id",
        lambda: authorization_id,
    )
    monkeypatch.setattr(
        authorization_service,
        "_new_run_id",
        lambda: run_id,
    )

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO idempotency (
                server_id, idempotency_key, canonical_payload_hash, run_id, status
            ) VALUES ('srv_public', ?, ?, 'run_public_orphan', 'accepted')
            """,
            (internal_key, request.expectedRunSpecHash),
        )
        connection.commit()

    result = authorization_service.authorize_agent_workflow_run(
        cfg,
        session_id,
        request,
        actor=_ACTOR,
    )

    assert result["idempotencyReplay"] is False
    assert result["authorization"]["authorizationId"] == authorization_id
    assert result["authorization"]["runId"] == run_id
    assert result["run"]["runId"] == run_id
    assert _effect_counts(cfg) == {
        "runs": 1,
        "run_commands": 1,
        "run_events": 2,
        "run_jobs": 1,
        "idempotency": 2,
        "agent_run_authorizations": 1,
        "evidence_schemas": 1,
        "evidence_events": 1,
    }
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT server_id, idempotency_key, canonical_payload_hash, run_id, status
            FROM idempotency
            WHERE idempotency_key = ?
            ORDER BY server_id
            """,
            (internal_key,),
        ).fetchall()
    assert [dict(row) for row in rows] == [
        {
            "server_id": AGENT_CONTROL_PLANE_SERVER_ID,
            "idempotency_key": internal_key,
            "canonical_payload_hash": request.expectedRunSpecHash,
            "run_id": run_id,
            "status": "accepted",
        },
        {
            "server_id": "srv_public",
            "idempotency_key": internal_key,
            "canonical_payload_hash": request.expectedRunSpecHash,
            "run_id": "run_public_orphan",
            "status": "accepted",
        },
    ]


def _matching_request(
    candidate_case: dict[str, Any],
    *,
    suffix: str,
) -> AgentRunAuthorizationRequest:
    preview = build_agent_run_authorization_preview(
        candidate_case["cfg"],
        candidate_case["session"]["sessionId"],
        actor=_ACTOR,
    )
    return AgentRunAuthorizationRequest.model_validate(
        {
            "expectedStateVersion": preview["stateVersion"],
            "expectedPlanRevisionId": preview["planRevisionId"],
            "expectedPlanGeneration": preview["planGeneration"],
            "expectedPlanHash": preview["planHash"],
            "expectedWorkflowRevisionId": preview["workflowRevisionId"],
            "expectedPreviewHash": preview["previewHash"],
            "expectedInputManifestDigest": preview["inputManifestDigest"],
            "expectedRunSpecHash": preview["runSpecHash"],
            "expectedExecutionPolicyHash": preview["executionPolicyHash"],
            "expectedRuntimeProofHash": preview["runtimeProofHash"],
            "confirmation": "authorize-workflow-run",
            "requestId": f"authorize-atomicity-{suffix}",
            "idempotencyKey": f"authorize-atomicity-{suffix}",
        }
    )


def _effect_counts(cfg: Any) -> dict[str, int]:
    with get_connection(cfg) as connection:
        return {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in _EFFECT_TABLES
        }


def _authority_rows(candidate_case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    plan_revision_id = candidate_case["plan"]["planRevisionId"]
    workflow_revision_id = candidate_case["revision"]["workflowRevisionId"]
    queries = {
        "session": (
            "SELECT * FROM agent_sessions WHERE session_id = ?",
            session_id,
        ),
        "plan": (
            "SELECT * FROM agent_plan_revisions WHERE plan_revision_id = ?",
            plan_revision_id,
        ),
        "workflowRevision": (
            "SELECT * FROM workflow_revisions WHERE workflow_revision_id = ?",
            workflow_revision_id,
        ),
        "effectBudget": (
            "SELECT * FROM agent_session_effect_budgets WHERE session_id = ?",
            session_id,
        ),
    }
    with get_connection(cfg) as connection:
        rows: dict[str, dict[str, Any]] = {}
        for name, (query, value) in queries.items():
            row = connection.execute(query, (value,)).fetchone()
            assert row is not None
            rows[name] = dict(row)
        return rows


def _exception_chain_text(error: BaseException) -> str:
    messages: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(str(current))
        current = current.__cause__ or current.__context__
    return " | ".join(messages)
