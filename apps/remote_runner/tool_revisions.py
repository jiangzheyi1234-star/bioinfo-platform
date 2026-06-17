from __future__ import annotations

import json
import hashlib
from typing import Any

from .config import RemoteRunnerConfig
from .storage import get_connection, now_iso
from .tool_contract import build_tool_contract
from .tool_platform_storage import latest_validation_summary_for_tool_revision


def publish_tool_revision(cfg: RemoteRunnerConfig, tool: dict[str, Any]) -> dict[str, Any]:
    tool_id = str(tool.get("id") or "").strip()
    if not tool_id:
        raise ValueError("TOOL_ID_REQUIRED")
    spec_hash = tool_spec_hash(tool)
    tool_revision_id = f"{tool_id}#{spec_hash[:12]}"

    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT tool_json FROM tool_revisions WHERE tool_revision_id = ?",
            (tool_revision_id,),
        ).fetchone()
        if existing is not None:
            saved = json.loads(existing["tool_json"] or "{}")
            return saved if isinstance(saved, dict) else {}
        row = connection.execute(
            "SELECT COALESCE(MAX(revision), 0) AS latest_revision FROM tool_revisions WHERE tool_id = ?",
            (tool_id,),
        ).fetchone()
        revision = int(row["latest_revision"] or 0) + 1
        published_at = now_iso()
        environment_lock = build_environment_lock(tool)
        revision_tool = {
            **tool,
            "id": tool_id,
            "toolId": tool_id,
            "toolRevisionId": tool_revision_id,
            "revision": revision,
            "specHash": spec_hash,
            "publishedAt": published_at,
            "status": "published",
            "message": str(tool.get("message") or "Tool revision published."),
        }
        if environment_lock:
            revision_tool["environmentLock"] = environment_lock
        revision_tool["toolContract"] = build_tool_contract(revision_tool)
        connection.execute(
            """
            INSERT INTO tool_revisions (tool_revision_id, tool_id, revision, tool_json, published_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                tool_revision_id,
                tool_id,
                revision,
                json.dumps(revision_tool, ensure_ascii=False, sort_keys=True),
                published_at,
            ),
        )
        connection.commit()
    return revision_tool


def build_environment_lock(tool: dict[str, Any]) -> dict[str, Any]:
    environment_spec = tool.get("environmentSpec")
    if not isinstance(environment_spec, dict):
        return {}
    adapter_name = str(environment_spec.get("adapter") or "conda").strip()
    if adapter_name == "apptainer":
        image = str(environment_spec.get("image") or "").strip()
        digest = str(environment_spec.get("digest") or "").strip()
        return {
            "adapter": "apptainer",
            "image": image,
            "digest": digest,
        }
    if adapter_name == "native":
        return {"adapter": "native"}
    env_name = str(environment_spec.get("name") or "").strip()
    env_file = str(environment_spec.get("file") or "").strip()
    channels = list(environment_spec.get("channels") or [])
    dependencies = list(environment_spec.get("dependencies") or [])
    return {
        "adapter": "conda",
        "name": env_name,
        "file": env_file,
        "channels": channels,
        "dependencies": dependencies,
    }


def tool_spec_hash(tool: dict[str, Any]) -> str:
    stable = {
        "toolId": str(tool.get("id") or tool.get("toolId") or "").strip(),
        "source": str(tool.get("source") or "").strip(),
        "version": str(tool.get("version") or "").strip(),
        "packageSpec": str(tool.get("packageSpec") or "").strip(),
        "targetPlatform": str(tool.get("targetPlatform") or "linux-64").strip() or "linux-64",
        "ruleTemplate": tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {},
        "ruleSpecDraft": tool.get("ruleSpecDraft") if isinstance(tool.get("ruleSpecDraft"), dict) else {},
        "capabilities": tool.get("capabilities") if isinstance(tool.get("capabilities"), list) else [],
        "environmentLock": tool.get("environmentLock") if isinstance(tool.get("environmentLock"), dict) else {},
    }
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fetch_tool_revision(cfg: RemoteRunnerConfig, tool_revision_id: str) -> dict[str, Any] | None:
    normalized = str(tool_revision_id or "").strip()
    if not normalized:
        return None
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT tool_json FROM tool_revisions WHERE tool_revision_id = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        tool = json.loads(row["tool_json"] or "{}")
        if not isinstance(tool, dict):
            return None
        summary = latest_validation_summary_for_tool_revision(
            connection,
            tool_revision_id=normalized,
            tool_id=str(tool.get("id") or tool.get("toolId") or "").strip(),
        )
    if summary:
        tool["validationSummary"] = summary
        tool["validationResultId"] = str(summary.get("latestResultId") or "").strip()
        tool["evidenceId"] = str(summary.get("evidenceId") or "").strip()
    return tool
