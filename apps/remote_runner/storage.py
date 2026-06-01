from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .config import RemoteRunnerConfig, ensure_runtime_layout
from .storage_schema import SCHEMA_SQL
from .tool_contract import build_tool_contract, default_contract_status, normalize_contract_status

MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_connection(cfg: RemoteRunnerConfig) -> sqlite3.Connection:
    ensure_runtime_layout(cfg)
    connection = sqlite3.connect(str(cfg.db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_SQL)
    _ensure_tools_columns(connection)
    connection.commit()
    return connection


def _ensure_tools_columns(connection: sqlite3.Connection) -> None:
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(tools)").fetchall()}
    if "tool_revision_id" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN tool_revision_id TEXT NOT NULL DEFAULT ''")
    if "revision" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
    if "rule_template_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN rule_template_json TEXT NOT NULL DEFAULT '{}'")
    if "rule_spec_draft_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN rule_spec_draft_json TEXT NOT NULL DEFAULT '{}'")
    if "capabilities_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN capabilities_json TEXT NOT NULL DEFAULT '[]'")
    if "snakemake_wrappers_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN snakemake_wrappers_json TEXT NOT NULL DEFAULT '[]'")
    if "contract_status_json" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN contract_status_json TEXT NOT NULL DEFAULT '{}'")
    if "published_at" not in columns:
        connection.execute("ALTER TABLE tools ADD COLUMN published_at TEXT")


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


def fetch_upload(cfg: RemoteRunnerConfig, upload_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
    if row is None:
        return None
    return {
        "uploadId": row["upload_id"],
        "filename": row["filename"],
        "path": row["path"],
        "sizeBytes": row["size_bytes"],
        "sha256": row["sha256"],
        "mimeType": row["mime_type"],
        "uploadedAt": row["uploaded_at"],
    }


def _tool_row_to_dict(row) -> dict[str, Any]:
    item = {
        "id": row["tool_id"],
        "toolRevisionId": row["tool_revision_id"],
        "revision": int(row["revision"] or 0),
        "name": row["name"],
        "source": row["source"],
        "sourceLabel": row["source_label"],
        "version": row["version"],
        "packageSpec": row["package_spec"],
        "summary": row["summary"],
        "targetPlatform": row["target_platform"],
        "targetPlatformSupported": bool(row["target_platform_supported"]),
        "platforms": json.loads(row["platforms_json"] or "[]"),
        "sourceUrl": row["source_url"],
        "testCommand": row["test_command"],
        "ruleTemplate": json.loads(row["rule_template_json"] or "{}"),
        "ruleSpecDraft": json.loads(row["rule_spec_draft_json"] or "{}"),
        "capabilities": json.loads(row["capabilities_json"] or "[]"),
        "snakemakeWrappers": json.loads(row["snakemake_wrappers_json"] or "[]"),
        "snakemakeWrapperCount": len(json.loads(row["snakemake_wrappers_json"] or "[]")),
        "contractStatus": normalize_contract_status(json.loads(row["contract_status_json"] or "{}")),
        "status": row["status"],
        "message": row["message"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "publishedAt": row["published_at"],
        "lastCheckedAt": row["last_checked_at"],
    }
    item["toolContract"] = build_tool_contract(item)
    return item


def list_tools(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute("SELECT * FROM tools ORDER BY updated_at DESC, name ASC").fetchall()
    return [_tool_row_to_dict(row) for row in rows]


def fetch_tool(cfg: RemoteRunnerConfig, tool_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT * FROM tools WHERE tool_id = ?", (tool_id,)).fetchone()
    return _tool_row_to_dict(row) if row is not None else None


def upsert_tool(cfg: RemoteRunnerConfig, tool: dict[str, Any]) -> dict[str, Any]:
    tool_id = str(tool.get("id") or "").strip()
    name = str(tool.get("name") or "").strip()
    source = str(tool.get("source") or "").strip()
    package_spec = str(tool.get("packageSpec") or "").strip()
    if not tool_id or not name or not source or not package_spec:
        raise ValueError("TOOL_MANIFEST_INVALID")

    now = now_iso()
    existing = fetch_tool(cfg, tool_id)
    status = str(tool.get("status") or (existing or {}).get("status") or "declared")
    message = str(tool.get("message") or (existing or {}).get("message") or "Tool declared.")
    contract_status_provided = "contractStatus" in tool
    contract_status = normalize_contract_status(
        tool.get("contractStatus") if contract_status_provided else (existing or {}).get("contractStatus") or default_contract_status()
    )
    last_checked_at = (
        _latest_contract_checked_at(contract_status)
        if contract_status_provided
        else str(tool.get("lastCheckedAt") or (existing or {}).get("lastCheckedAt") or "") or None
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO tools (
                tool_id, tool_revision_id, revision, name, source, source_label, version, package_spec, summary,
                target_platform, target_platform_supported, platforms_json, source_url,
                test_command, rule_template_json, rule_spec_draft_json, capabilities_json, snakemake_wrappers_json,
                contract_status_json, status, message, created_at, updated_at, published_at, last_checked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tool_id) DO UPDATE SET
                tool_revision_id = excluded.tool_revision_id,
                revision = excluded.revision,
                name = excluded.name,
                source = excluded.source,
                source_label = excluded.source_label,
                version = excluded.version,
                package_spec = excluded.package_spec,
                summary = excluded.summary,
                target_platform = excluded.target_platform,
                target_platform_supported = excluded.target_platform_supported,
                platforms_json = excluded.platforms_json,
                source_url = excluded.source_url,
                test_command = excluded.test_command,
                rule_template_json = excluded.rule_template_json,
                rule_spec_draft_json = excluded.rule_spec_draft_json,
                capabilities_json = excluded.capabilities_json,
                snakemake_wrappers_json = excluded.snakemake_wrappers_json,
                contract_status_json = excluded.contract_status_json,
                status = excluded.status,
                message = excluded.message,
                updated_at = excluded.updated_at,
                published_at = excluded.published_at,
                last_checked_at = excluded.last_checked_at
            """,
            (
                tool_id,
                str(tool.get("toolRevisionId") or ""),
                int(tool.get("revision") or 0),
                name,
                source,
                str(tool.get("sourceLabel") or source),
                str(tool.get("version") or ""),
                package_spec,
                str(tool.get("summary") or ""),
                str(tool.get("targetPlatform") or "linux-64"),
                1 if bool(tool.get("targetPlatformSupported")) else 0,
                json.dumps(list(tool.get("platforms") or [])),
                str(tool.get("sourceUrl") or ""),
                str(tool.get("testCommand") or ""),
                json.dumps(dict(tool.get("ruleTemplate") or {}), ensure_ascii=False),
                json.dumps(dict(tool.get("ruleSpecDraft") or {}), ensure_ascii=False),
                json.dumps(list(tool.get("capabilities") or []), ensure_ascii=False),
                json.dumps(list(tool.get("snakemakeWrappers") or []), ensure_ascii=False),
                json.dumps(contract_status, ensure_ascii=False),
                status,
                message,
                (existing or {}).get("createdAt") or now,
                now,
                str(tool.get("publishedAt") or "") or None,
                last_checked_at,
            ),
        )
        connection.commit()
    saved = fetch_tool(cfg, tool_id)
    if saved is None:
        raise KeyError(tool_id)
    return saved


def _latest_contract_checked_at(contract_status: dict[str, dict[str, str]]) -> str | None:
    values = [
        str(item.get("checkedAt") or "").strip()
        for item in contract_status.values()
        if isinstance(item, dict) and str(item.get("checkedAt") or "").strip()
    ]
    return max(values) if values else None


def delete_tool(cfg: RemoteRunnerConfig, tool_id: str) -> None:
    with get_connection(cfg) as connection:
        cursor = connection.execute("DELETE FROM tools WHERE tool_id = ?", (tool_id,))
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError(tool_id)


def update_tool_status(
    cfg: RemoteRunnerConfig,
    *,
    tool_id: str,
    status: str,
    message: str,
) -> dict[str, Any]:
    checked_at = now_iso()
    with get_connection(cfg) as connection:
        cursor = connection.execute(
            """
            UPDATE tools
            SET status = ?, message = ?, updated_at = ?, last_checked_at = ?
            WHERE tool_id = ?
            """,
            (status, message, checked_at, checked_at, tool_id),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError(tool_id)
    item = fetch_tool(cfg, tool_id)
    if item is None:
        raise KeyError(tool_id)
    return item


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
    size_bytes, sha256 = _artifact_payload_stats(path)
    created_at = now_iso()
    artifact = {
        "artifactId": f"art_{uuid.uuid4().hex[:10]}",
        "runId": run_id,
        "kind": kind,
        "path": str(path),
        "sizeBytes": size_bytes,
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


def _artifact_payload_stats(path: Path) -> tuple[int, str]:
    if path.is_file():
        content = path.read_bytes()
        return len(content), hashlib.sha256(content).hexdigest()
    if path.is_dir():
        digest = hashlib.sha256()
        size_bytes = 0
        for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
            relative = child.relative_to(path).as_posix()
            if child.is_dir():
                digest.update(f"D\t{relative}\0".encode("utf-8"))
                continue
            if child.is_file():
                content = child.read_bytes()
                digest.update(f"F\t{relative}\0".encode("utf-8"))
                digest.update(content)
                size_bytes += len(content)
        return size_bytes, digest.hexdigest()
    raise ValueError("OUTPUT_ARTIFACT_PATH_INVALID")


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
