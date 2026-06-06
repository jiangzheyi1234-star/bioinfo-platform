from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from .api_models import ToolManifestRequest, ToolProductionEvidenceRequest, ToolRuleTemplateRequest
from .route_utils import authorized_config, data_response, request_payload, run_sync
from .tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    create_tool_prepare_job,
    list_latest_tool_prepare_jobs_by_tool_id,
    require_tool_prepare_job,
)
from .tool_prepare_jobs import run_tool_prepare_job
from .tools import (
    add_registered_tool,
    list_registered_tools,
    mark_registered_tool_production_enabled,
    remove_registered_tool,
    update_registered_tool_rule_template,
)


class BackgroundTaskScheduler(Protocol):
    def add_task(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None: ...


async def list_tools_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    items = await run_sync(list_registered_tools, cfg)
    return data_response({"items": items})


async def add_tool_from_request(
    payload: ToolManifestRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(add_registered_tool, cfg, request_payload(payload))
    return data_response(item)


async def create_tool_prepare_job_response_from_request(
    payload: ToolManifestRequest,
    background_tasks: BackgroundTaskScheduler,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    job = await run_sync(create_tool_prepare_job, cfg, request_payload(payload))
    if not job.get("reusedExisting"):
        background_tasks.add_task(run_tool_prepare_job, cfg, job["jobId"])
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


async def cancel_tool_prepare_job_from_request(
    job_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    job = await run_sync(cancel_tool_prepare_job, cfg, job_id)
    return data_response(job)


def _tool_ids_from_query(value: str) -> list[str]:
    return [item for item in (part.strip() for part in str(value or "").split(",")) if item]


async def update_tool_rule_template_from_request(
    tool_id: str,
    payload: ToolRuleTemplateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(
        update_registered_tool_rule_template,
        cfg,
        tool_id,
        payload.ruleTemplate,
    )
    return data_response(item)


async def delete_tool_from_request(
    tool_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    await run_sync(remove_registered_tool, cfg, tool_id)
    return data_response({"id": tool_id, "deleted": True})


async def mark_tool_production_from_request(
    tool_id: str,
    payload: ToolProductionEvidenceRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(
        mark_registered_tool_production_enabled,
        cfg,
        tool_id,
        request_payload(payload),
    )
    return data_response(item)
