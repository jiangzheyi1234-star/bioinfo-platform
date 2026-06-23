from __future__ import annotations

from typing import Any

from .api_models import ToolManifestRequest, ToolProductionEvidenceRequest, ToolRuleTemplateRequest
from .governance_audit import record_governance_audit_event
from .route_utils import authorized_config, data_response, request_payload, run_sync
from .tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    create_tool_prepare_job,
    list_latest_tool_prepare_jobs_by_tool_id,
    list_tool_prepare_jobs,
    require_tool_prepare_job,
)
from .tool_platform_storage import search_tool_index
from .tools import (
    add_registered_tool,
    list_registered_tools,
    mark_registered_tool_production_enabled,
    remove_registered_tool,
    update_registered_tool_rule_template,
)


async def list_tools_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    items = await run_sync(list_registered_tools, cfg)
    return data_response({"items": items})


async def list_tool_index_from_request(
    authorization: str | None,
    *,
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    source: str | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    page = await run_sync(
        search_tool_index,
        cfg,
        query=query,
        limit=limit,
        offset=offset,
        source=source,
        state=state,
    )
    return data_response(page)


async def add_tool_from_request(
    payload: ToolManifestRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="tool.create")
    item = await run_sync(add_registered_tool, cfg, request_payload(payload))
    await _record_tool_governance_event(cfg, action="tool.create", item=item)
    return data_response(item)


async def create_tool_prepare_job_response_from_request(
    payload: ToolManifestRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="tool.prepare")
    job = await run_sync(create_tool_prepare_job, cfg, request_payload(payload))
    await run_sync(
        record_governance_audit_event,
        cfg,
        action="tool.prepare",
        subject_kind="tool_prepare_job",
        subject_id=str(job.get("jobId") or ""),
        actor="remote-runner-api",
        details={
            "toolId": str(job.get("toolId") or job.get("id") or ""),
            "status": str(job.get("status") or ""),
            "reusedExisting": bool(job.get("reusedExisting")),
        },
    )
    return data_response(job)


async def get_tool_prepare_job_from_request(
    job_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    job = await run_sync(require_tool_prepare_job, cfg, job_id)
    return data_response(job)


async def list_latest_tool_prepare_jobs_from_request(
    tool_ids: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    latest_jobs = await run_sync(
        list_latest_tool_prepare_jobs_by_tool_id,
        cfg,
        _tool_ids_from_query(tool_ids),
    )
    return data_response({"items": list(latest_jobs.values()), "byToolId": latest_jobs})


async def list_tool_prepare_job_queue_from_request(
    authorization: str | None,
    *,
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    page = await run_sync(
        list_tool_prepare_jobs,
        cfg,
        status=status,
        limit=limit,
        offset=offset,
    )
    return data_response(page)


async def cancel_tool_prepare_job_from_request(
    job_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="tool.prepare.cancel")
    job = await run_sync(cancel_tool_prepare_job, cfg, job_id)
    await run_sync(
        record_governance_audit_event,
        cfg,
        action="tool.prepare.cancel",
        subject_kind="tool_prepare_job",
        subject_id=str(job.get("jobId") or job_id),
        actor="remote-runner-api",
        details={
            "toolId": str(job.get("toolId") or ""),
            "status": str(job.get("status") or ""),
        },
    )
    return data_response(job)


def _tool_ids_from_query(value: str) -> list[str]:
    return [item for item in (part.strip() for part in str(value or "").split(",")) if item]


async def update_tool_rule_template_from_request(
    tool_id: str,
    payload: ToolRuleTemplateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="tool.rule_template.update")
    item = await run_sync(
        update_registered_tool_rule_template,
        cfg,
        tool_id,
        payload.ruleTemplate,
    )
    await _record_tool_governance_event(
        cfg,
        action="tool.rule_template.update",
        item=item,
        extra_details=_rule_template_audit_details(item.get("ruleTemplate")),
    )
    return data_response(item)


async def delete_tool_from_request(
    tool_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="tool.delete")
    await run_sync(remove_registered_tool, cfg, tool_id)
    await run_sync(
        record_governance_audit_event,
        cfg,
        action="tool.delete",
        subject_kind="tool",
        subject_id=tool_id,
        actor="remote-runner-api",
        details={"toolId": tool_id},
    )
    return data_response({"id": tool_id, "deleted": True})


async def mark_tool_production_from_request(
    tool_id: str,
    payload: ToolProductionEvidenceRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="tool.production.enable")
    item = await run_sync(
        mark_registered_tool_production_enabled,
        cfg,
        tool_id,
        request_payload(payload),
    )
    production = (
        item.get("contractStatus", {}).get("production", {})
        if isinstance(item.get("contractStatus"), dict)
        else {}
    )
    await _record_tool_governance_event(
        cfg,
        action="tool.production.enable",
        item=item,
        extra_details={
            "runId": str(production.get("runId") or payload.runId or ""),
            "evidenceId": str(production.get("evidenceId") or ""),
            "toolRevisionId": str(item.get("toolRevisionId") or ""),
        },
    )
    return data_response(item)


async def _record_tool_governance_event(
    cfg: Any,
    *,
    action: str,
    item: dict[str, Any],
    extra_details: dict[str, Any] | None = None,
) -> None:
    tool_id = str(item.get("id") or item.get("toolId") or "")
    await run_sync(
        record_governance_audit_event,
        cfg,
        action=action,
        subject_kind="tool",
        subject_id=tool_id,
        actor="remote-runner-api",
        details={
            "toolId": tool_id,
            "status": str(item.get("status") or ""),
            **(extra_details or {}),
        },
    )


def _rule_template_audit_details(raw: Any) -> dict[str, int]:
    template = raw if isinstance(raw, dict) else {}
    inputs = template.get("inputs") if isinstance(template.get("inputs"), list) else []
    outputs = template.get("outputs") if isinstance(template.get("outputs"), list) else []
    return {"ruleInputCount": len(inputs), "ruleOutputCount": len(outputs)}
