from __future__ import annotations

import json
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso
from .tool_contract import build_tool_contract, default_contract_status, normalize_contract_status


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


def delete_tool(cfg: RemoteRunnerConfig, tool_id: str) -> None:
    with get_connection(cfg) as connection:
        cursor = connection.execute("DELETE FROM tools WHERE tool_id = ?", (tool_id,))
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError(tool_id)


def _latest_contract_checked_at(contract_status: dict[str, dict[str, str]]) -> str | None:
    values = [
        str(item.get("checkedAt") or "").strip()
        for item in contract_status.values()
        if isinstance(item, dict) and str(item.get("checkedAt") or "").strip()
    ]
    return max(values) if values else None
