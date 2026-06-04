from __future__ import annotations

from typing import Any

from apps.api.models import (
    WorkflowDesignDraftCompileRequest,
    WorkflowDesignDraftCreateRequest,
    WorkflowDesignDraftForkRequest,
    WorkflowDesignDraftPlanRequest,
    WorkflowDesignDraftUpdateRequest,
)
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import cached_runtime_payload, request_payload, run_runtime_payload, runtime_service


async def list_workflow_design_drafts_from_request(
    *,
    refresh: bool,
    server_id: str | None,
) -> dict[str, Any]:
    return await cached_runtime_payload(
        f"workflow_design_drafts:{server_id or 'default'}",
        10,
        lambda: runtime_service().list_workflow_design_drafts(server_id=server_id),
        wrapper="raw",
        force_refresh=refresh,
    )


async def get_workflow_design_draft_from_request(
    draft_id: str,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_workflow_design_draft(
            draft_id,
            server_id=server_id,
        ),
        wrapper="raw",
    )


async def create_workflow_design_draft_from_request(
    request: WorkflowDesignDraftCreateRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().create_workflow_design_draft(
            request_payload(request)
        ),
        wrapper="raw",
    )
    await invalidate_response_cache(prefixes=("workflow_design_drafts",))
    return result


async def update_workflow_design_draft_from_request(
    draft_id: str,
    request: WorkflowDesignDraftUpdateRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().update_workflow_design_draft(
            draft_id,
            request_payload(request),
        ),
        wrapper="raw",
    )
    await invalidate_response_cache(prefixes=("workflow_design_drafts",))
    return result


async def fork_workflow_design_draft_from_request(
    draft_id: str,
    request: WorkflowDesignDraftForkRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().fork_workflow_design_draft(
            draft_id,
            request_payload(request),
        ),
        wrapper="raw",
    )
    await invalidate_response_cache(prefixes=("workflow_design_drafts",))
    return result


async def delete_workflow_design_draft_from_request(
    draft_id: str,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().delete_workflow_design_draft(
            draft_id,
            server_id=server_id,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache(prefixes=("workflow_design_drafts",))
    return result


async def plan_workflow_design_draft_from_request(
    draft_id: str,
    request: WorkflowDesignDraftPlanRequest | None,
) -> dict[str, Any]:
    body = request_payload(request)
    return await run_runtime_payload(
        lambda: runtime_service().plan_workflow_design_draft(draft_id, body),
        wrapper="raw",
    )


async def compile_workflow_design_draft_from_request(
    draft_id: str,
    request: WorkflowDesignDraftCompileRequest | None,
) -> dict[str, Any]:
    body = request_payload(request)
    return await run_runtime_payload(
        lambda: runtime_service().compile_workflow_design_draft(draft_id, body),
        wrapper="raw",
    )
