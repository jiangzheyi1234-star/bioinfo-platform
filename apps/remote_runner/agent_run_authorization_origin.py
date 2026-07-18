"""Binding-first integrity guard for Agent-owned WorkflowRun creation rows."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, NoReturn

from core.contracts.agent_control_plane_namespace import (
    AGENT_CONTROL_PLANE_SERVER_ID,
)
from core.contracts.agent_fastq_qc_execution import (
    AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
    agent_fastq_qc_execution_hash,
    agent_workflow_run_spec_hash,
)
from core.contracts.agent_run_authorization import (
    agent_run_authorization_run_idempotency_key,
)

from .agent_run_authorization_storage import (
    fetch_agent_run_authorization_by_id_for_connection,
)
from .generated_workflow_constants import GENERATED_TOOL_RUN_PIPELINE_ID


AGENT_RUN_AUTHORIZATION_CREATION_ORIGIN_INVALID = (
    "AGENT_RUN_AUTHORIZATION_CREATION_ORIGIN_INVALID"
)
AGENT_RUN_AUTHORIZATION_ORIGIN_TRANSACTION_REQUIRED = (
    "AGENT_RUN_AUTHORIZATION_ORIGIN_TRANSACTION_REQUIRED"
)


class AgentRunAuthorizationOriginIntegrityError(RuntimeError):
    """Raised when an immutable authorization is not backed by its exact origin."""

    def __init__(
        self,
        component: str,
        *,
        code: str = AGENT_RUN_AUTHORIZATION_CREATION_ORIGIN_INVALID,
    ) -> None:
        self.code = code
        self.component = component
        super().__init__(f"{self.code}: {component}")


def require_agent_run_authorization_origin_for_connection(
    connection: sqlite3.Connection,
    authorization_id: str,
) -> dict[str, Any]:
    """Verify the exact creation chain selected only by immutable authorization id."""

    if not connection.in_transaction:
        raise AgentRunAuthorizationOriginIntegrityError(
            "transaction",
            code=AGENT_RUN_AUTHORIZATION_ORIGIN_TRANSACTION_REQUIRED,
        )
    normalized_authorization_id = str(authorization_id or "").strip()
    if not normalized_authorization_id:
        _fail("binding")

    try:
        binding = fetch_agent_run_authorization_by_id_for_connection(
            connection,
            normalized_authorization_id,
        )
    except (KeyError, TypeError, ValueError) as exc:
        _fail("binding", cause=exc)
    if binding is None:
        _fail("binding")

    run_row, run_spec = _require_run(connection, binding)
    internal_key = agent_run_authorization_run_idempotency_key(
        str(binding["sessionId"]),
        str(binding["authorizationId"]),
        str(binding["commandHash"]),
    )
    command_row = _require_submit_command(
        connection,
        binding=binding,
        run_spec=run_spec,
        internal_key=internal_key,
    )
    accepted_row = _require_accepted_event(
        connection,
        binding=binding,
        run_row=run_row,
        run_spec=run_spec,
        command_row=command_row,
    )
    queued_row, queued_payload = _require_queued_event(
        connection,
        binding=binding,
        accepted_row=accepted_row,
    )
    _require_creation_event_slots(
        connection,
        run_id=str(binding["runId"]),
        accepted_row=accepted_row,
        queued_row=queued_row,
    )
    job_row = _require_job(
        connection,
        binding=binding,
        run_spec=run_spec,
        queued_payload=queued_payload,
    )
    _require_idempotency(
        connection,
        binding=binding,
        internal_key=internal_key,
    )
    return {
        "authorizationId": binding["authorizationId"],
        "runId": binding["runId"],
        "commandId": command_row["command_id"],
        "acceptedEventId": accepted_row["event_id"],
        "queuedEventId": queued_row["event_id"],
        "jobId": job_row["job_id"],
        "idempotencyKey": internal_key,
        "runSpecHash": binding["runSpecHash"],
        "executionPolicyHash": binding["executionPolicyHash"],
    }


def _require_run(
    connection: sqlite3.Connection,
    binding: dict[str, Any],
) -> tuple[sqlite3.Row, dict[str, Any]]:
    row = connection.execute(
        "SELECT * FROM runs WHERE run_id = ?",
        (binding["runId"],),
    ).fetchone()
    if row is None:
        _fail("run")
    run_spec = _json_object(row["run_spec_json"], "run")
    if (
        "runId" in run_spec
        or run_spec.get("pipelineId") != GENERATED_TOOL_RUN_PIPELINE_ID
    ):
        _fail("run")
    try:
        run_spec_hash = agent_workflow_run_spec_hash(run_spec)
        execution = run_spec.get("execution")
        execution_policy_hash = agent_fastq_qc_execution_hash(execution)
    except (TypeError, ValueError) as exc:
        _fail("run", cause=exc)
    expected = {
        "run_id": binding["runId"],
        "server_id": AGENT_CONTROL_PLANE_SERVER_ID,
        "project_id": _created_text(run_spec.get("projectId"), "proj_default"),
        "pipeline_id": _created_text(run_spec.get("pipelineId"), ""),
        "pipeline_version": _created_text(run_spec.get("pipelineVersion"), "0.1.0"),
        "run_spec_version": _created_text(run_spec.get("runSpecVersion"), "2026-04-21"),
        "workflow_revision_id": binding["workflowRevisionId"],
        "request_id": binding["requestId"],
        "submitted_at": binding["createdAt"],
        "trigger_id": None,
        "trigger_event_id": None,
        "trigger_source": "",
        "trigger_cursor": "",
    }
    actual = {key: row[key] for key in expected}
    if not _strict_json_equal(actual, expected):
        _fail("run")
    if not _strict_json_equal(
        run_spec.get("workflowRevisionId"), binding["workflowRevisionId"]
    ):
        _fail("run")
    if (
        run_spec_hash != binding["runSpecHash"]
        or binding["executionPolicyId"] != AGENT_FASTQ_QC_EXECUTION_POLICY_ID
        or execution_policy_hash != binding["executionPolicyHash"]
    ):
        _fail("run")
    return row, run_spec


def _require_submit_command(
    connection: sqlite3.Connection,
    *,
    binding: dict[str, Any],
    run_spec: dict[str, Any],
    internal_key: str,
) -> sqlite3.Row:
    rows = connection.execute(
        """
        SELECT * FROM run_commands
        WHERE (run_id = ? AND command_type = 'submit_run')
           OR idempotency_key = ?
        """,
        (binding["runId"], internal_key),
    ).fetchall()
    if len(rows) != 1:
        _fail("submit_command")
    row = rows[0]
    payload = _json_object(row["payload_json"], "submit_command")
    expected = {
        "run_id": binding["runId"],
        "command_type": "submit_run",
        "idempotency_key": internal_key,
        "actor": binding["actor"],
        "payload_hash": _sha256(_stable_json(run_spec)),
        "requested_at": binding["createdAt"],
    }
    if (
        row["payload_json"] != _stable_json(run_spec)
        or not _strict_json_equal({key: row[key] for key in expected}, expected)
        or not _strict_json_equal(payload, run_spec)
    ):
        _fail("submit_command")
    return row


def _require_accepted_event(
    connection: sqlite3.Connection,
    *,
    binding: dict[str, Any],
    run_row: sqlite3.Row,
    run_spec: dict[str, Any],
    command_row: sqlite3.Row,
) -> sqlite3.Row:
    rows = connection.execute(
        "SELECT * FROM run_events WHERE run_id = ? AND event_type = 'accepted'",
        (binding["runId"],),
    ).fetchall()
    if len(rows) != 1:
        _fail("accepted_event")
    row = rows[0]
    payload = {
        "pipelineId": run_row["pipeline_id"],
        "projectId": run_row["project_id"],
        "runId": binding["runId"],
    }
    if run_spec.get("workflowRevisionId"):
        payload["workflowRevisionId"] = run_spec["workflowRevisionId"]
    expected = {
        "run_id": binding["runId"],
        "event_type": "accepted",
        "seq": 1,
        "schema_version": "run-event.v2",
        "from_status": None,
        "to_status": "queued",
        "stage": "submitted",
        "state_version": 1,
        "message": "Accepted for asynchronous execution",
        "request_id": binding["requestId"],
        "command_id": command_row["command_id"],
        "correlation_id": None,
        "actor": binding["actor"],
        "created_at": binding["createdAt"],
    }
    _require_event_envelope(
        row, expected=expected, payload=payload, component="accepted_event"
    )
    if row["prev_event_hash"] is not None:
        _fail("event_chain")
    return row


def _require_queued_event(
    connection: sqlite3.Connection,
    *,
    binding: dict[str, Any],
    accepted_row: sqlite3.Row,
) -> tuple[sqlite3.Row, dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM run_events WHERE run_id = ? AND event_type = 'run_job_queued'",
        (binding["runId"],),
    ).fetchall()
    if len(rows) != 1:
        _fail("queued_event")
    row = rows[0]
    details = _json_object(row["details_json"], "queued_event")
    payload = details.get("payload")
    if not isinstance(payload, dict):
        _fail("queued_event")
    expected = {
        "run_id": binding["runId"],
        "event_type": "run_job_queued",
        "seq": 2,
        "schema_version": "run-event.v2",
        "from_status": None,
        "to_status": None,
        "stage": "queue",
        "state_version": 1,
        "message": "Run job queued.",
        "request_id": binding["requestId"],
        "command_id": None,
        "correlation_id": None,
        "actor": None,
        "created_at": binding["createdAt"],
    }
    _require_event_envelope(
        row, expected=expected, payload=payload, component="queued_event"
    )
    if row["prev_event_hash"] != accepted_row["event_hash"]:
        _fail("event_chain")
    if set(payload) != {"jobId", "queueName", "maxAttempts"}:
        _fail("queued_event")
    return row, payload


def _require_event_envelope(
    row: sqlite3.Row,
    *,
    expected: dict[str, Any],
    payload: dict[str, Any],
    component: str,
) -> None:
    if not _strict_json_equal({key: row[key] for key in expected}, expected):
        _fail(component)
    payload_hash = _sha256(_stable_json(payload))
    if row["payload_hash"] != payload_hash:
        _fail(component)
    event_hash = _event_hash(row, payload_hash=payload_hash)
    if row["event_hash"] != event_hash:
        _fail("event_chain")
    details = _json_object(row["details_json"], component)
    expected_details = {
        "schema_version": row["schema_version"],
        "occurred_at": row["created_at"],
        "sequence": row["seq"],
        "command_id": row["command_id"],
        "correlation_id": row["correlation_id"],
        "actor": row["actor"],
        "payload_hash": row["payload_hash"],
        "event_hash": row["event_hash"],
        "prev_event_hash": row["prev_event_hash"],
        "payload": payload,
    }
    if not _strict_json_equal(details, expected_details):
        _fail(component)


def _require_creation_event_slots(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    accepted_row: sqlite3.Row,
    queued_row: sqlite3.Row,
) -> None:
    rows = connection.execute(
        """
        SELECT event_id, event_type, seq FROM run_events
        WHERE run_id = ? AND seq <= 2 ORDER BY seq ASC, event_id ASC
        """,
        (run_id,),
    ).fetchall()
    actual = [
        {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "seq": row["seq"],
        }
        for row in rows
    ]
    expected = [
        {
            "event_id": accepted_row["event_id"],
            "event_type": "accepted",
            "seq": 1,
        },
        {
            "event_id": queued_row["event_id"],
            "event_type": "run_job_queued",
            "seq": 2,
        },
    ]
    if not _strict_json_equal(actual, expected):
        _fail("event_chain")


def _require_job(
    connection: sqlite3.Connection,
    *,
    binding: dict[str, Any],
    run_spec: dict[str, Any],
    queued_payload: dict[str, Any],
) -> sqlite3.Row:
    rows = connection.execute(
        "SELECT * FROM run_jobs WHERE run_id = ?",
        (binding["runId"],),
    ).fetchall()
    if len(rows) != 1:
        _fail("job")
    row = rows[0]
    try:
        execution = run_spec["execution"]
        retry_policy = execution["retryPolicy"]
        timeout_policy = execution["timeoutPolicy"]
        expected = {
            "job_id": queued_payload.get("jobId"),
            "run_id": binding["runId"],
            "queue_name": execution["queueName"],
            "priority": 0,
            "max_attempts": retry_policy["maxAttempts"],
            "created_at": binding["createdAt"],
        }
    except (KeyError, TypeError) as exc:
        _fail("job", cause=exc)
    if (
        not _strict_json_equal({key: row[key] for key in expected}, expected)
        or not _strict_json_equal(queued_payload.get("queueName"), row["queue_name"])
        or not _strict_json_equal(
            queued_payload.get("maxAttempts"), row["max_attempts"]
        )
        or not _strict_json_equal(
            _json_object(row["retry_policy_json"], "job"), retry_policy
        )
        or not _strict_json_equal(
            _json_object(row["timeout_policy_json"], "job"), timeout_policy
        )
    ):
        _fail("job")
    return row


def _require_idempotency(
    connection: sqlite3.Connection,
    *,
    binding: dict[str, Any],
    internal_key: str,
) -> None:
    rows = connection.execute(
        "SELECT * FROM idempotency WHERE run_id = ?",
        (binding["runId"],),
    ).fetchall()
    if len(rows) != 1:
        _fail("idempotency")
    row = rows[0]
    expected = {
        "server_id": AGENT_CONTROL_PLANE_SERVER_ID,
        "idempotency_key": internal_key,
        "canonical_payload_hash": binding["runSpecHash"],
        "run_id": binding["runId"],
        "status": "accepted",
    }
    if not _strict_json_equal({key: row[key] for key in expected}, expected):
        _fail("idempotency")


def _event_hash(row: sqlite3.Row, *, payload_hash: str) -> str:
    return _sha256(
        _stable_json(
            {
                "actor": row["actor"],
                "command_id": row["command_id"],
                "correlation_id": row["correlation_id"],
                "event_type": row["event_type"],
                "occurred_at": row["created_at"],
                "payload_hash": payload_hash,
                "prev_event_hash": row["prev_event_hash"],
                "run_id": row["run_id"],
                "schema_version": row["schema_version"],
                "sequence": row["seq"],
            }
        )
    )


def _json_object(value: Any, component: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        _fail(component, cause=exc)
    if not isinstance(parsed, dict):
        _fail(component)
    return parsed


def _strict_json_equal(left: Any, right: Any) -> bool:
    try:
        return _canonical_json(left) == _canonical_json(right)
    except (TypeError, ValueError):
        return False


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _created_text(value: Any, default: str) -> str:
    normalized = str(value or default).strip()
    return normalized or default


def _fail(component: str, *, cause: Exception | None = None) -> NoReturn:
    error = AgentRunAuthorizationOriginIntegrityError(component)
    if cause is not None:
        raise error from cause
    raise error


__all__ = [
    "AGENT_RUN_AUTHORIZATION_CREATION_ORIGIN_INVALID",
    "AGENT_RUN_AUTHORIZATION_ORIGIN_TRANSACTION_REQUIRED",
    "AgentRunAuthorizationOriginIntegrityError",
    "require_agent_run_authorization_origin_for_connection",
]
