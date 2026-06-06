from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from .config import RemoteRunnerConfig
from .errors import IdempotencyKeyReusedError
from .execution_query_storage import fetch_run
from .storage_core import get_connection, now_iso


@dataclass(frozen=True)
class RunCreateRecordResult:
    run: dict[str, Any]
    status: str
    created: bool
    reason: str


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
        connection.execute(
            """
            INSERT INTO run_events (
                event_id, run_id, event_type, from_status, to_status, stage, state_version, message, request_id, created_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"evt_{uuid.uuid4().hex[:10]}",
                run["runId"],
                "accepted",
                None,
                "queued",
                "submitted",
                1,
                "Accepted for asynchronous execution",
                request_id,
                submitted_at,
                None,
            ),
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
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT state_version, status, started_at, finished_at, run_spec_json FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if existing is None:
            raise KeyError(run_id)
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
        connection.execute(
            """
            INSERT INTO run_events (
                event_id, run_id, event_type, from_status, to_status, stage, state_version, message, request_id, created_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"evt_{uuid.uuid4().hex[:10]}",
                run_id,
                "status-transition",
                existing["status"],
                status,
                stage,
                next_state_version,
                message,
                request_id,
                last_updated_at,
                json.dumps(last_error) if last_error else None,
            ),
        )
        connection.commit()
    return fetch_run(cfg, run_id)
