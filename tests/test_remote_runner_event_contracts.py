from __future__ import annotations

import json
import sqlite3

import pytest

from apps.remote_runner.event_contracts import append_run_event_v2
from apps.remote_runner.storage_schema import SCHEMA_SQL


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_SQL)
    return connection


def test_run_event_v2_appender_requires_event_metadata() -> None:
    connection = _connection()

    with pytest.raises(ValueError, match="EVENT_TYPE_REQUIRED"):
        append_run_event_v2(
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
        append_run_event_v2(
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
        append_run_event_v2(
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
            "2026-06-07T00:00:00Z",
            None,
        ),
    )

    first = append_run_event_v2(
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
        occurred_at="2026-06-07T00:00:01Z",
        command_derived=True,
        correlation_required=True,
    )
    second = append_run_event_v2(
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
        occurred_at="2026-06-07T00:00:02Z",
        command_derived=True,
        correlation_required=True,
    )

    assert first["sequence"] == 2
    assert second["sequence"] == 3
    assert first["schema_version"] == "run-event.v2"
    assert first["occurred_at"] == "2026-06-07T00:00:01Z"
    assert first["command_id"] == "cmd_1"
    assert first["correlation_id"] == "corr_1"
    assert first["payload"] == {"reason": "accepted"}

    rows = connection.execute("SELECT details_json FROM run_events WHERE run_id = ? ORDER BY created_at", ("run_1",))
    details = [json.loads(row["details_json"]) for row in rows.fetchall() if row["details_json"]]
    assert [item["sequence"] for item in details] == [2, 3]
