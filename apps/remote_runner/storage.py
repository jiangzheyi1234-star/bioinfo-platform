from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .config import RemoteRunnerConfig, ensure_runtime_layout


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS service_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    upload_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    server_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    run_spec_version TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    message TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    result_dir TEXT NOT NULL,
    last_error_json TEXT,
    last_updated_at TEXT NOT NULL,
    request_id TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    run_spec_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_events (
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
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    server_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    canonical_payload_hash TEXT NOT NULL,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (server_id, idempotency_key)
);
"""

MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_connection(cfg: RemoteRunnerConfig) -> sqlite3.Connection:
    ensure_runtime_layout(cfg)
    connection = sqlite3.connect(str(cfg.db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_SQL)
    connection.commit()
    return connection


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


def persist_upload(
    cfg: RemoteRunnerConfig,
    *,
    filename: str,
    content_base64: str,
    mime_type: str,
) -> dict[str, Any]:
    uploads_dir = Path(cfg.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    estimated_size = _estimate_base64_size(content_base64)
    if estimated_size > MAX_UPLOAD_BYTES:
        raise ValueError("UPLOAD_TOO_LARGE")
    try:
        content = base64.b64decode(content_base64.encode("utf-8"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("INVALID_UPLOAD_BASE64") from exc
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("UPLOAD_TOO_LARGE")
    upload_id = f"upl_{uuid.uuid4().hex[:12]}"
    target = uploads_dir / f"{upload_id}_{Path(filename).name}"
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_bytes(content)
    sha256 = hashlib.sha256(content).hexdigest()
    temp.rename(target)
    uploaded_at = now_iso()
    row = {
        "uploadId": upload_id,
        "filename": Path(filename).name,
        "path": str(target),
        "sizeBytes": len(content),
        "sha256": sha256,
        "mimeType": mime_type or "application/octet-stream",
        "uploadedAt": uploaded_at,
    }
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO uploads (upload_id, filename, path, size_bytes, sha256, mime_type, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["uploadId"],
                row["filename"],
                row["path"],
                row["sizeBytes"],
                row["sha256"],
                row["mimeType"],
                row["uploadedAt"],
            ),
        )
        connection.commit()
    return row


def _estimate_base64_size(content_base64: str) -> int:
    raw = "".join(str(content_base64 or "").split())
    if not raw:
        return 0
    padding = len(raw) - len(raw.rstrip("="))
    return max(0, (len(raw) * 3) // 4 - padding)


def create_run_record(
    cfg: RemoteRunnerConfig,
    *,
    server_id: str,
    request_id: str,
    run_spec: dict[str, Any],
    idempotency_key: str,
    payload_hash: str,
) -> tuple[dict[str, Any], str]:
    run_id = str(run_spec.get("runId") or f"run_{uuid.uuid4().hex[:12]}").strip()
    project_id = str(run_spec.get("projectId") or "proj_default").strip() or "proj_default"
    pipeline_id = str(run_spec.get("pipelineId") or "taxonomy-v1").strip() or "taxonomy-v1"
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
                raise ValueError("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD")
            existing_run = fetch_run(cfg, existing["run_id"])
            if existing_run is None:
                raise ValueError("RUN_NOT_FOUND")
            return existing_run, existing["status"]

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
    return run, "accepted"


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


def append_log_lines(cfg: RemoteRunnerConfig, run_id: str, stream: str, lines: Iterable[str]) -> None:
    logs_dir = Path(cfg.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{run_id}.{stream}.log"
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(f"{line}\n")


def fetch_log_lines(cfg: RemoteRunnerConfig, run_id: str, stream: str, cursor: str | None) -> dict[str, Any]:
    path = Path(cfg.logs_dir) / f"{run_id}.{stream}.log"
    if not path.exists():
        return {"runId": run_id, "stream": stream, "cursor": cursor or "", "nextCursor": cursor or "", "lines": []}
    content = path.read_text(encoding="utf-8")
    start = int(cursor or 0)
    next_cursor = len(content)
    lines = [line for line in content[start:].splitlines() if line]
    return {
        "runId": run_id,
        "stream": stream,
        "cursor": cursor or "",
        "nextCursor": str(next_cursor),
        "lines": lines,
    }


def persist_artifact(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    kind: str,
    path: Path,
    mime_type: str,
) -> dict[str, Any]:
    content = path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    created_at = now_iso()
    artifact = {
        "artifactId": f"art_{uuid.uuid4().hex[:10]}",
        "runId": run_id,
        "kind": kind,
        "path": str(path),
        "sizeBytes": path.stat().st_size,
        "sha256": sha256,
        "mimeType": mime_type,
        "createdAt": created_at,
    }
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO artifacts (artifact_id, run_id, kind, path, size_bytes, sha256, mime_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact["artifactId"],
                artifact["runId"],
                artifact["kind"],
                artifact["path"],
                artifact["sizeBytes"],
                artifact["sha256"],
                artifact["mimeType"],
                artifact["createdAt"],
            ),
        )
        connection.commit()
    return artifact


def fetch_run(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    last_error = json.loads(row["last_error_json"]) if row["last_error_json"] else None
    return {
        "runId": row["run_id"],
        "serverId": row["server_id"],
        "projectId": row["project_id"],
        "pipelineId": row["pipeline_id"],
        "pipelineVersion": row["pipeline_version"],
        "runSpecVersion": row["run_spec_version"],
        "status": row["status"],
        "stage": row["stage"],
        "stateVersion": row["state_version"],
        "message": row["message"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "resultDir": row["result_dir"],
        "lastError": last_error,
        "lastUpdatedAt": row["last_updated_at"],
        "requestId": row["request_id"],
        "submittedAt": row["submitted_at"],
        "resumeSupported": False,
        "runSpec": json.loads(row["run_spec_json"]),
    }


def list_runs(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute("SELECT run_id FROM runs ORDER BY submitted_at DESC").fetchall()
    return [fetch_run(cfg, row["run_id"]) for row in rows if fetch_run(cfg, row["run_id"]) is not None]


def fetch_run_events(cfg: RemoteRunnerConfig, run_id: str) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [
        {
            "eventId": row["event_id"],
            "runId": row["run_id"],
            "eventType": row["event_type"],
            "fromStatus": row["from_status"],
            "toStatus": row["to_status"],
            "stage": row["stage"],
            "stateVersion": row["state_version"],
            "message": row["message"],
            "requestId": row["request_id"],
            "createdAt": row["created_at"],
            "detailsJson": json.loads(row["details_json"]) if row["details_json"] else None,
        }
        for row in rows
    ]


def fetch_run_results(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    run = fetch_run(cfg, run_id)
    if run is None:
        raise KeyError(run_id)
    with get_connection(cfg) as connection:
        rows = connection.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    artifacts = [
        {
            "artifactId": row["artifact_id"],
            "runId": row["run_id"],
            "kind": row["kind"],
            "path": row["path"],
            "sizeBytes": row["size_bytes"],
            "sha256": row["sha256"],
            "mimeType": row["mime_type"],
            "createdAt": row["created_at"],
        }
        for row in rows
    ]
    return {"runId": run_id, "resultDir": run["resultDir"], "artifacts": artifacts}


def list_results(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT run_id, pipeline_id, finished_at, last_updated_at
            FROM runs
            WHERE status IN ('completed', 'failed')
            ORDER BY COALESCE(finished_at, last_updated_at) DESC
            """
        ).fetchall()
    items = []
    for row in rows:
        artifacts = fetch_run_results(cfg, row["run_id"])["artifacts"]
        items.append(
            {
                "resultId": f"res_{row['run_id']}",
                "runId": row["run_id"],
                "title": f"{row['pipeline_id']} result",
                "pipelineId": row["pipeline_id"],
                "artifactCount": len(artifacts),
                "producedAt": row["finished_at"] or row["last_updated_at"],
            }
        )
    return items


def fetch_result(cfg: RemoteRunnerConfig, result_id: str) -> dict[str, Any]:
    run_id = result_id.removeprefix("res_")
    run = fetch_run(cfg, run_id)
    if run is None:
        raise KeyError(result_id)
    results = fetch_run_results(cfg, run_id)
    return {
        "resultId": result_id,
        "runId": run_id,
        "title": f"{run['pipelineId']} result",
        "pipelineId": run["pipelineId"],
        "producedAt": run["finishedAt"] or run["lastUpdatedAt"],
        "artifactCount": len(results["artifacts"]),
        "artifacts": results["artifacts"],
    }
