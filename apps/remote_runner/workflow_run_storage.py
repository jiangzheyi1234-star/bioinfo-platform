from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from .config import RemoteRunnerConfig
from .errors import IdempotencyKeyReusedError
from .event_contracts import append_run_event_v2, record_run_command
from .execution_lifecycle_guard import ensure_execution_lifecycle_admission_open_for_connection
from .execution_policy import execution_policy_from_run_spec
from .execution_query_storage import fetch_run, fetch_run_for_connection
from .run_execution_storage import enqueue_run_job_record
from .run_execution_state_machine import RunExecutionStateMachine
from .storage_core import get_connection, now_iso


@dataclass(frozen=True)
class RunCreateRecordResult:
    run: dict[str, Any]
    status: str
    created: bool
    reason: str


class StaleRunAttemptError(RuntimeError):
    """Raised when an old attempt tries to publish run state."""


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    def _normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: _normalize(sub_value)
                for key, sub_value in sorted(value.items())
                if sub_value not in ("", None, [], {}, False)
                and key != "runId"
            }
        if isinstance(value, list):
            return [_normalize(item) for item in value if item not in ("", None, [], {}, False)]
        return value

    normalized = _normalize(payload)
    raw = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def create_run_record(
    cfg: RemoteRunnerConfig,
    *,
    server_id: str,
    request_id: str,
    run_spec: dict[str, Any],
    idempotency_key: str,
    payload_hash: str,
) -> RunCreateRecordResult:
    run_id = str(run_spec.get("runId") or f"run_{uuid.uuid4().hex[:12]}").strip()
    submitted_at = now_iso()
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        result = create_run_record_for_connection(
            connection,
            server_id=server_id,
            actor=server_id,
            request_id=request_id,
            run_spec=run_spec,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            run_id=run_id,
            submitted_at=submitted_at,
        )
        connection.commit()
        return result


def create_run_record_for_connection(
    connection: sqlite3.Connection,
    *,
    server_id: str,
    actor: str,
    request_id: str,
    run_spec: dict[str, Any],
    idempotency_key: str,
    payload_hash: str,
    run_id: str | None = None,
    submitted_at: str | None = None,
) -> RunCreateRecordResult:
    """Create or replay a run inside the caller's existing writer transaction."""

    if not connection.in_transaction:
        raise RuntimeError("RUN_CREATION_WRITER_TRANSACTION_REQUIRED")
    recorded_actor = str(actor or "")
    if not recorded_actor.strip():
        raise ValueError("RUN_CREATION_ACTOR_REQUIRED")
    requested_run_id = str(run_id or "").strip()
    run_spec_id = str(run_spec.get("runId") or "").strip()
    if requested_run_id and run_spec_id and requested_run_id != run_spec_id:
        raise ValueError("RUN_CREATION_RUN_ID_MISMATCH")
    normalized_run_id = requested_run_id or run_spec_id or f"run_{uuid.uuid4().hex[:12]}"
    project_id = str(run_spec.get("projectId") or "proj_default").strip() or "proj_default"
    pipeline_id = str(run_spec.get("pipelineId") or "").strip()
    if not pipeline_id:
        raise ValueError("PIPELINE_ID_REQUIRED")
    pipeline_version = str(run_spec.get("pipelineVersion") or "0.1.0").strip() or "0.1.0"
    run_spec_version = str(run_spec.get("runSpecVersion") or "2026-04-21").strip() or "2026-04-21"
    workflow_revision_id = str(run_spec.get("workflowRevisionId") or "").strip() or None
    normalized_submitted_at = str(submitted_at or "").strip() or now_iso()
    execution_policy = execution_policy_from_run_spec(run_spec)
    accepted = RunExecutionStateMachine.submission_accepted()
    run = {
        "runId": normalized_run_id,
        "serverId": server_id,
        "projectId": project_id,
        "pipelineId": pipeline_id,
        "pipelineVersion": pipeline_version,
        "runSpecVersion": run_spec_version,
        "workflowRevisionId": workflow_revision_id,
        "status": accepted.to_status,
        "stage": accepted.stage,
        "stateVersion": accepted.state_version,
        "message": accepted.row_message,
        "startedAt": None,
        "finishedAt": None,
        "resultDir": "",
        "lastError": None,
        "lastUpdatedAt": normalized_submitted_at,
        "requestId": request_id,
        "submittedAt": normalized_submitted_at,
        "resumeSupported": False,
        "runSpec": run_spec,
    }

    existing = connection.execute(
        "SELECT run_id, canonical_payload_hash, status FROM idempotency WHERE server_id = ? AND idempotency_key = ?",
        (server_id, idempotency_key),
    ).fetchone()
    if existing is not None:
        if existing["canonical_payload_hash"] != payload_hash:
            raise IdempotencyKeyReusedError("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD")
        existing_run = fetch_run_for_connection(connection, existing["run_id"])
        if existing_run is None:
            raise ValueError("RUN_NOT_FOUND")
        return RunCreateRecordResult(
            run=existing_run,
            status=existing["status"],
            created=False,
            reason="idempotency_replay",
        )

    ensure_execution_lifecycle_admission_open_for_connection(connection, now=normalized_submitted_at)
    connection.execute(
        """
        INSERT INTO runs (
            run_id, server_id, project_id, pipeline_id, pipeline_version, run_spec_version,
            workflow_revision_id, status, stage, state_version, message, started_at, finished_at, result_dir,
            last_error_json, last_updated_at, request_id, submitted_at, run_spec_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run["runId"],
            run["serverId"],
            run["projectId"],
            run["pipelineId"],
            run["pipelineVersion"],
            run["runSpecVersion"],
            run["workflowRevisionId"],
            run["status"],
            run["stage"],
            run["stateVersion"],
            run["message"],
            run["startedAt"],
            run["finishedAt"],
            run["resultDir"],
            None,
            run["lastUpdatedAt"],
            run["requestId"],
            run["submittedAt"],
            json.dumps(run["runSpec"]),
        ),
    )
    command = record_run_command(
        connection,
        run_id=run["runId"],
        command_type="submit_run",
        payload=run["runSpec"],
        idempotency_key=idempotency_key,
        actor=recorded_actor,
        requested_at=normalized_submitted_at,
    )
    append_run_event_v2(
        connection,
        run_id=run["runId"],
        event_type=accepted.event_type,
        from_status=accepted.from_status,
        to_status=accepted.to_status,
        stage=accepted.stage,
        state_version=accepted.state_version,
        message=accepted.event_message,
        request_id=request_id,
        command_id=command["commandId"],
        actor=recorded_actor,
        payload={
            "pipelineId": run["pipelineId"],
            "projectId": run["projectId"],
            "runId": run["runId"],
            **(
                {"workflowRevisionId": run_spec["workflowRevisionId"]}
                if run_spec.get("workflowRevisionId")
                else {}
            ),
        },
        occurred_at=normalized_submitted_at,
        command_derived=True,
    )
    enqueue_run_job_record(
        connection,
        run_id=run["runId"],
        queue_name=execution_policy.queue_name,
        available_at=normalized_submitted_at,
        max_attempts=execution_policy.retry.max_attempts,
        retry_policy=execution_policy.retry.as_dict(),
        timeout_policy=execution_policy.timeout.as_dict(),
    )
    connection.execute(
        """
        INSERT INTO idempotency (server_id, idempotency_key, canonical_payload_hash, run_id, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (server_id, idempotency_key, payload_hash, run["runId"], "accepted"),
    )
    return RunCreateRecordResult(run=run, status="accepted", created=True, reason="created")


def update_run_state(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    status: str,
    stage: str,
    message: str,
    request_id: str,
    last_error: dict[str, Any] | None = None,
    result_dir: str | None = None,
    attempt_id: str | None = None,
    lease_generation: int | None = None,
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT state_version, status, started_at, finished_at, run_spec_json FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if existing is None:
            raise KeyError(run_id)
        if not run_attempt_can_publish(
            connection,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        ):
            raise StaleRunAttemptError("RUN_ATTEMPT_STALE")
        transition = RunExecutionStateMachine.publish_status(
            current_status=str(existing["status"]),
            state_version=int(existing["state_version"]),
            status=status,
            stage=stage,
            message=message,
        )
        started_at = existing["started_at"] or now_iso()
        finished_at = (
            now_iso()
            if RunExecutionStateMachine.is_terminal_run_status(transition.to_status)
            else None
        )
        last_updated_at = now_iso()
        connection.execute(
            """
            UPDATE runs
            SET status = ?, stage = ?, state_version = ?, message = ?, started_at = ?, finished_at = ?,
                result_dir = ?, last_error_json = ?, last_updated_at = ?
            WHERE run_id = ?
            """,
            (
                transition.to_status,
                transition.stage,
                transition.state_version,
                transition.row_message,
                started_at,
                finished_at,
                result_dir or "",
                json.dumps(last_error) if last_error else None,
                last_updated_at,
                run_id,
            ),
        )
        append_run_event_v2(
            connection,
            run_id=run_id,
            event_type=transition.event_type,
            from_status=transition.from_status,
            to_status=transition.to_status,
            stage=transition.stage,
            state_version=transition.state_version,
            message=transition.event_message,
            request_id=request_id,
            payload={"lastError": last_error} if last_error else {},
            occurred_at=last_updated_at,
        )
        connection.commit()
    return fetch_run(cfg, run_id)


def run_attempt_can_publish(
    connection,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
) -> bool:
    lease = connection.execute(
        "SELECT attempt_id, lease_generation, state FROM run_leases WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    decision = RunExecutionStateMachine.current_lease_guard(
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        current_attempt_id=str(lease["attempt_id"]) if lease is not None else None,
        current_lease_generation=int(lease["lease_generation"]) if lease is not None else None,
        current_lease_state=str(lease["state"]) if lease is not None else None,
        allow_missing_attempt_context=True,
    )
    return decision.accepted
