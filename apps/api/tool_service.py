from __future__ import annotations

from typing import Any

from apps.api.models import ToolManifestRequest, ToolRuleTemplateRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import (
    cached_runtime_payload,
    request_payload,
    run_runtime_payload,
    runtime_service,
)


async def list_tools_from_request(refresh: bool) -> dict[str, Any]:
    return await cached_runtime_payload(
        "tools",
        30,
        runtime_service().list_tools,
        wrapper="raw",
        force_refresh=refresh,
    )


async def list_tool_index_from_request(
    *,
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    source: str | None = None,
    state: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    cache_key = f"tools:index:{query}:{limit}:{offset}:{source or ''}:{state or ''}"
    return await cached_runtime_payload(
        cache_key,
        30,
        lambda: runtime_service().list_tool_index(
            query=query,
            limit=limit,
            offset=offset,
            source=source,
            state=state,
        ),
        wrapper="raw",
        force_refresh=refresh,
    )


async def add_tool_from_request(request: ToolManifestRequest) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().add_tool(request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result


async def create_tool_prepare_job_from_request(
    request: ToolManifestRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().create_tool_prepare_job(
            request_payload(request)
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result


async def get_tool_prepare_job_from_request(job_id: str) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_tool_prepare_job(job_id),
        wrapper="raw",
    )


async def cancel_tool_prepare_job_from_request(job_id: str) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().cancel_tool_prepare_job(job_id),
        wrapper="raw",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result


async def update_tool_rule_template_from_request(
    tool_id: str,
    request: ToolRuleTemplateRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().update_tool_rule_template(
            tool_id,
            request_payload(request),
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result


async def delete_tool_from_request(tool_id: str) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().delete_tool(tool_id),
        wrapper="raw",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result
