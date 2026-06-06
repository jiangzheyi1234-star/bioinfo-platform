"""SQLite persistence for immutable WorkflowRevision records."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


WORKFLOW_REVISION_SCHEMA_VERSION = "workflow-revision.v1"


def create_or_fetch_workflow_revision(
    cfg: RemoteRunnerConfig,
    *,
    draft_id: str | None,
    draft_revision: int | None,
    manifest: dict[str, Any],
    graph_snapshot: dict[str, Any],
    runtime_lock: dict[str, Any],
    compiler: dict[str, Any],
    created_by: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    content = _content_payload(
        draft_id=draft_id,
        draft_revision=draft_revision,
        manifest=manifest,
        graph_snapshot=graph_snapshot,
        runtime_lock=runtime_lock,
        compiler=compiler,
    )
    content_hash = _sha256_hex(content)
    revision_id = f"wfrev_{content_hash[:24]}"
    timestamp = _optional_text(created_at) or now_iso()

    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT * FROM workflow_revisions WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if existing is not None:
            return {**_row_to_dict(existing), "created": False}

        connection.execute(
            """
            INSERT INTO workflow_revisions (
                workflow_revision_id, draft_id, draft_revision, content_hash,
                manifest_json, graph_snapshot_json, runtime_lock_json, compiler_json,
                created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id,
                _optional_text(draft_id),
                _optional_int(draft_revision),
                content_hash,
                _stable_json(manifest),
                _stable_json(graph_snapshot),
                _stable_json(runtime_lock),
                _stable_json(compiler),
                _optional_text(created_by),
                timestamp,
            ),
        )
        connection.commit()
        created = connection.execute(
            "SELECT * FROM workflow_revisions WHERE workflow_revision_id = ?",
            (revision_id,),
        ).fetchone()
    return {**_row_to_dict(created), "created": True}


def fetch_workflow_revision(cfg: RemoteRunnerConfig, workflow_revision_id: str) -> dict[str, Any] | None:
    revision_id = _required_text(workflow_revision_id, "WORKFLOW_REVISION_ID_REQUIRED")
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM workflow_revisions WHERE workflow_revision_id = ?",
            (revision_id,),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def _content_payload(
    *,
    draft_id: str | None,
    draft_revision: int | None,
    manifest: dict[str, Any],
    graph_snapshot: dict[str, Any],
    runtime_lock: dict[str, Any],
    compiler: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": WORKFLOW_REVISION_SCHEMA_VERSION,
        "draftId": _optional_text(draft_id),
        "draftRevision": _optional_int(draft_revision),
        "manifest": _required_object(manifest, "WORKFLOW_REVISION_MANIFEST_REQUIRED"),
        "graphSnapshot": _required_object(graph_snapshot, "WORKFLOW_REVISION_GRAPH_SNAPSHOT_REQUIRED"),
        "runtimeLock": _required_object(runtime_lock, "WORKFLOW_REVISION_RUNTIME_LOCK_REQUIRED"),
        "compiler": _required_object(compiler, "WORKFLOW_REVISION_COMPILER_REQUIRED"),
    }


def _sha256_hex(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "workflowRevisionId": row["workflow_revision_id"],
        "draftId": row["draft_id"],
        "draftRevision": int(row["draft_revision"]) if row["draft_revision"] is not None else None,
        "contentHash": row["content_hash"],
        "manifest": json.loads(row["manifest_json"]),
        "graphSnapshot": json.loads(row["graph_snapshot_json"]),
        "runtimeLock": json.loads(row["runtime_lock_json"]),
        "compiler": json.loads(row["compiler_json"]),
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
    }


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required_object(value: dict[str, Any], code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _required_text(value: str, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _optional_int(value: int | None) -> int | None:
    if value is None:
        return None
    normalized = int(value)
    if normalized < 0:
        raise ValueError("WORKFLOW_REVISION_DRAFT_REVISION_INVALID")
    return normalized
