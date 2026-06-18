from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from apps.remote_runner import event_contracts
from apps.remote_runner.sqlite_migrations import initialize_or_migrate_runtime_db
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.storage_schema import SCHEMA_SQL
from tests.helpers.reference_database import make_remote_runner_config


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_SQL)
    return connection


def test_run_event_v2_appender_requires_event_metadata() -> None:
    connection = _connection()

    with pytest.raises(ValueError, match="EVENT_TYPE_REQUIRED"):
        event_contracts.append_run_event_v2(
            connection,
            run_id="run_1",
            event_type="",
            stage="queued",
            state_version=1,
            message="Queued",
            request_id="req_1",
            payload={},
        )

    with pytest.raises(ValueError, match="COMMAND_ID_REQUIRED"):
        event_contracts.append_run_event_v2(
            connection,
            run_id="run_1",
            event_type="run.accepted",
            stage="queued",
            state_version=1,
            message="Queued",
            request_id="req_1",
            payload={},
            command_derived=True,
        )

    with pytest.raises(ValueError, match="EVENT_PAYLOAD_OBJECT_REQUIRED"):
        event_contracts.append_run_event_v2(
            connection,
            run_id="run_1",
            event_type="run.accepted",
            stage="queued",
            state_version=1,
            message="Queued",
            request_id="req_1",
            payload=[],
        )


def test_run_event_v2_appender_assigns_deterministic_sequence_after_v1_rows() -> None:
    connection = _connection()
    connection.execute(
        """
        INSERT INTO run_events (
            event_id, run_id, event_type, from_status, to_status, stage, state_version,
            message, request_id, created_at, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "evt_v1",
            "run_1",
            "accepted",
            None,
            "queued",
            "submitted",
            1,
            "Accepted",
            "req_1",
            "2099-06-07T00:00:00Z",
            None,
        ),
    )

    first = event_contracts.append_run_event_v2(
        connection,
        run_id="run_1",
        event_type="run.queued",
        from_status="submitted",
        to_status="queued",
        stage="queued",
        state_version=2,
        message="Queued",
        request_id="req_1",
        command_id="cmd_1",
        correlation_id="corr_1",
        payload={"reason": "accepted"},
        occurred_at="2099-06-07T00:00:01Z",
        command_derived=True,
        correlation_required=True,
    )
    second = event_contracts.append_run_event_v2(
        connection,
        run_id="run_1",
        event_type="run.running",
        from_status="queued",
        to_status="running",
        stage="executing",
        state_version=3,
        message="Running",
        request_id="req_1",
        command_id="cmd_1",
        correlation_id="corr_1",
        payload={},
        occurred_at="2099-06-07T00:00:02Z",
        command_derived=True,
        correlation_required=True,
    )

    assert first["sequence"] == 2
    assert second["sequence"] == 3
    assert first["schema_version"] == "run-event.v2"
    assert first["occurred_at"] == "2099-06-07T00:00:01Z"
    assert first["command_id"] == "cmd_1"
    assert first["correlation_id"] == "corr_1"
    assert first["payload"] == {"reason": "accepted"}

    rows = connection.execute("SELECT details_json FROM run_events WHERE run_id = ? ORDER BY created_at", ("run_1",))
    details = [json.loads(row["details_json"]) for row in rows.fetchall() if row["details_json"]]
    assert [item["sequence"] for item in details] == [2, 3]


def test_run_event_v2_appender_writes_ledger_columns_and_hash_chain() -> None:
    connection = _connection()

    command = event_contracts.record_run_command(
        connection,
        run_id="run_chain",
        command_type="submit_run",
        payload={"workflowRevisionId": "wfr_1"},
        command_id="cmd_submit",
        actor="tester",
        requested_at="2099-06-07T00:00:00Z",
    )
    first = event_contracts.append_run_event_v2(
        connection,
        run_id="run_chain",
        event_type="run.accepted",
        stage="submitted",
        state_version=1,
        message="Accepted",
        request_id="req_chain",
        payload={"runId": "run_chain"},
        command_id=command["commandId"],
        actor="tester",
        occurred_at="2099-06-07T00:00:01Z",
        command_derived=True,
    )
    second = event_contracts.append_run_event_v2(
        connection,
        run_id="run_chain",
        event_type="run_job_queued",
        stage="queue",
        state_version=1,
        message="Queued",
        request_id="req_chain",
        payload={"jobId": "job_1"},
        occurred_at="2099-06-07T00:00:02Z",
    )

    rows = connection.execute(
        """
        SELECT seq, schema_version, command_id, actor, payload_hash, event_hash, prev_event_hash
        FROM run_events
        WHERE run_id = ?
        ORDER BY seq
        """,
        ("run_chain",),
    ).fetchall()

    assert [row["seq"] for row in rows] == [1, 2]
    assert rows[0]["schema_version"] == "run-event.v2"
    assert rows[0]["command_id"] == "cmd_submit"
    assert rows[0]["actor"] == "tester"
    assert rows[0]["payload_hash"] == first["payload_hash"]
    assert rows[0]["event_hash"] == first["event_hash"]
    assert rows[0]["prev_event_hash"] is None
    assert rows[1]["prev_event_hash"] == first["event_hash"]
    assert rows[1]["event_hash"] == second["event_hash"]

    verification = event_contracts.verify_run_event_hash_chain(connection, "run_chain")
    assert verification == {"valid": True, "checked": 2, "reason": None}


def test_run_event_hash_chain_verification_detects_payload_mutation() -> None:
    connection = _connection()
    event_contracts.append_run_event_v2(
        connection,
        run_id="run_tampered",
        event_type="run.accepted",
        stage="submitted",
        state_version=1,
        message="Accepted",
        request_id="req_tamper",
        payload={"runId": "run_tampered"},
        occurred_at="2099-06-07T00:00:01Z",
    )
    row = connection.execute("SELECT details_json FROM run_events WHERE run_id = ?", ("run_tampered",)).fetchone()
    details = json.loads(row["details_json"])
    details["payload"] = {"runId": "mutated"}
    connection.execute(
        "UPDATE run_events SET details_json = ? WHERE run_id = ?",
        (json.dumps(details, sort_keys=True), "run_tampered"),
    )

    verification = event_contracts.verify_run_event_hash_chain(connection, "run_tampered")

    assert verification["valid"] is False
    assert verification["reason"] == "PAYLOAD_HASH_MISMATCH"


def test_storage_connection_migrates_legacy_run_events_table_before_index_creation(tmp_path) -> None:
    cfg = make_remote_runner_config(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy = sqlite3.connect(str(db_path))
    legacy.execute(
        """
        CREATE TABLE run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            stage TEXT NOT NULL,
            state_version INTEGER NOT NULL,
            message TEXT NOT NULL,
            request_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            details_json TEXT
        )
        """
    )
    legacy.commit()
    legacy.close()

    initialize_or_migrate_runtime_db(cfg.db_path)
    with get_connection(cfg) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(run_events)").fetchall()}
        event_contracts.append_run_event_v2(
            connection,
            run_id="run_legacy",
            event_type="run.accepted",
            stage="submitted",
            state_version=1,
            message="Accepted",
            request_id="req_legacy",
            payload={},
            occurred_at="2099-06-07T00:00:01Z",
        )
        row = connection.execute("SELECT seq, event_hash FROM run_events WHERE run_id = ?", ("run_legacy",)).fetchone()

    assert {"seq", "schema_version", "payload_hash", "event_hash", "prev_event_hash"} <= columns
    assert row["seq"] == 1
    assert row["event_hash"]
