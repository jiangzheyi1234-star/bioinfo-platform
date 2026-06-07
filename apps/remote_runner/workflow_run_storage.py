from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from .config import RemoteRunnerConfig
from .errors import IdempotencyKeyReusedError
from .event_contracts import append_run_event_v2, record_run_command
from .execution_query_storage import fetch_run
from .run_execution_storage import enqueue_run_job_record
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
    project_id = str(run_spec.get("projectId") or "proj_default").strip() or "proj_default"
    pipeline_id = str(run_spec.get("pipelineId") or "").strip()
    if not pipeline_id:
        raise ValueError("PIPELINE_ID_REQUIRED")
    pipeline_version = str(run_spec.get("pipelineVersion") or "0.1.0").strip() or "0.1.0"
    run_spec_version = str(run_spec.get("runSpecVersion") or "2026-04-21").strip() or "2026-04-21"
    submitted_at = now_iso()
    run = {
        "runId": run_id,
        "serverId": server_id,
        "projectId": project_id,
        "pipelineId": pipeline_id,
        "pipelineVersion": pipeline_version,
        "runSpecVersion": run_spec_version,
        "status": "queued",
        "stage": "submitted",
        "stateVersion": 1,
        "message": "Run accepted",
        "startedAt": None,
        "finishedAt": None,
        "resultDir": "",
        "lastError": None,
        "lastUpdatedAt": submitted_at,
        "requestId": request_id,
        "submittedAt": submitted_at,
        "resumeSupported": False,
        "runSpec": run_spec,
    }

    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT run_id, canonical_payload_hash, status FROM idempotency WHERE server_id = ? AND idempotency_key = ?",
            (server_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if existing["canonical_payload_hash"] != payload_hash:
                raise IdempotencyKeyReusedError("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD")
            existing_run = fetch_run(cfg, existing["run_id"])
            if existing_run is None:
                raise ValueError("RUN_NOT_FOUND")
            return RunCreateRecordResult(
                run=existing_run,
                status=existing["status"],
                created=False,
                reason="idempotency_replay",
            )

        connection.execute(
            """
            INSERT INTO runs (
                run_id, server_id, project_id, pipeline_id, pipeline_version, run_spec_version,
                status, stage, state_version, message, started_at, finished_at, result_dir,
                last_error_json, last_updated_at, request_id, submitted_at, run_spec_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["runId"],
                run["serverId"],
                run["projectId"],
                run["pipelineId"],
                run["pipelineVersion"],
                run["runSpecVersion"],
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
            actor=server_id,
            requested_at=submitted_at,
        )
        append_run_event_v2(
            connection,
            run_id=run["runId"],
            event_type="accepted",
            from_status=None,
            to_status="queued",
            stage="submitted",
            state_version=1,
            message="Accepted for asynchronous execution",
            request_id=request_id,
            command_id=command["commandId"],
            actor=server_id,
            payload={
                "pipelineId": run["pipelineId"],
                "projectId": run["projectId"],
                "runId": run["runId"],
                **({"workflowRevisionId": run_spec["workflowRevisionId"]} if run_spec.get("workflowRevisionId") else {}),
            },
            occurred_at=submitted_at,
            command_derived=True,
        )
        enqueue_run_job_record(
            connection,
            run_id=run["runId"],
            available_at=submitted_at,
        )
        connection.execute(
            """
            INSERT INTO idempotency (server_id, idempotency_key, canonical_payload_hash, run_id, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (server_id, idempotency_key, payload_hash, run["runId"], "accepted"),
        )
        connection.commit()
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
        next_state_version = int(existing["state_version"]) + 1
        started_at = existing["started_at"] or now_iso()
        finished_at = now_iso() if status in {"completed", "failed"} else None
        last_updated_at = now_iso()
        connection.execute(
            """
            UPDATE runs
            SET status = ?, stage = ?, state_version = ?, message = ?, started_at = ?, finished_at = ?,
                result_dir = ?, last_error_json = ?, last_updated_at = ?
            WHERE run_id = ?
            """,
            (
                status,
                stage,
                next_state_version,
                message,
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
            event_type="status-transition",
            from_status=existing["status"],
            to_status=status,
            stage=stage,
            state_version=next_state_version,
            message=message,
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
    has_attempt_context = any(
        value is not None and str(value).strip()
        for value in (attempt_id, lease_generation)
    )
    if not has_attempt_context:
        return True
    if not str(attempt_id or "").strip() or lease_generation is None:
        return False
    lease = connection.execute(
        "SELECT attempt_id, lease_generation, state FROM run_leases WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return bool(
        lease is not None
        and lease["attempt_id"] == attempt_id
        and int(lease["lease_generation"]) == int(lease_generation)
        and lease["state"] == "active"
    )
