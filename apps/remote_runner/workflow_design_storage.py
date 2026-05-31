"""SQLite persistence for WorkflowDesignDraft records."""

from __future__ import annotations

import json
import uuid
from typing import Any

from .config import RemoteRunnerConfig
from .storage import get_connection, now_iso
from .workflow_design_contract import normalize_workflow_design_draft


def create_workflow_design_draft(
    cfg: RemoteRunnerConfig,
    draft: dict[str, Any],
    *,
    parent_draft_id: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_workflow_design_draft(draft)
    draft_id = f"wfd_{uuid.uuid4().hex[:12]}"
    now = now_iso()
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO workflow_design_drafts (
                draft_id, parent_draft_id, contract_version, engine, name, project_id,
                revision, draft_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id,
                parent_draft_id,
                normalized["contractVersion"],
                normalized["engine"],
                normalized["metadata"]["name"],
                normalized["metadata"]["projectId"],
                1,
                json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        connection.commit()
    saved = fetch_workflow_design_draft(cfg, draft_id)
    if saved is None:
        raise KeyError(draft_id)
    return saved


def list_workflow_design_drafts(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT * FROM workflow_design_drafts
            ORDER BY updated_at DESC, name ASC, draft_id ASC
            """
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def fetch_workflow_design_draft(cfg: RemoteRunnerConfig, draft_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM workflow_design_drafts WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def update_workflow_design_draft(
    cfg: RemoteRunnerConfig,
    draft_id: str,
    draft: dict[str, Any],
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    normalized = normalize_workflow_design_draft(draft)
    now = now_iso()
    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT revision FROM workflow_design_drafts WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
        if existing is None:
            raise KeyError(draft_id)
        revision = int(existing["revision"])
        if expected_revision is not None and revision != expected_revision:
            raise ValueError("WORKFLOW_DESIGN_REVISION_CONFLICT")
        connection.execute(
            """
            UPDATE workflow_design_drafts
            SET contract_version = ?, engine = ?, name = ?, project_id = ?,
                revision = ?, draft_json = ?, updated_at = ?
            WHERE draft_id = ?
            """,
            (
                normalized["contractVersion"],
                normalized["engine"],
                normalized["metadata"]["name"],
                normalized["metadata"]["projectId"],
                revision + 1,
                json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                now,
                draft_id,
            ),
        )
        connection.commit()
    updated = fetch_workflow_design_draft(cfg, draft_id)
    if updated is None:
        raise KeyError(draft_id)
    return updated


def fork_workflow_design_draft(
    cfg: RemoteRunnerConfig,
    draft_id: str,
    *,
    name: str | None = None,
) -> dict[str, Any]:
    existing = fetch_workflow_design_draft(cfg, draft_id)
    if existing is None:
        raise KeyError(draft_id)
    draft = dict(existing["draft"])
    if name:
        draft["metadata"] = {**dict(draft.get("metadata") or {}), "name": name}
    return create_workflow_design_draft(cfg, draft, parent_draft_id=draft_id)


def delete_workflow_design_draft(cfg: RemoteRunnerConfig, draft_id: str) -> None:
    with get_connection(cfg) as connection:
        cursor = connection.execute(
            "DELETE FROM workflow_design_drafts WHERE draft_id = ?",
            (draft_id,),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError(draft_id)


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "draftId": row["draft_id"],
        "parentDraftId": row["parent_draft_id"],
        "contractVersion": row["contract_version"],
        "engine": row["engine"],
        "name": row["name"],
        "projectId": row["project_id"],
        "revision": int(row["revision"]),
        "draft": json.loads(row["draft_json"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
