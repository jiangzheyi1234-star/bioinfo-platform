"""WorkflowDesignDraft routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from apps.api.models import (
    WorkflowDesignDraftCreateRequest,
    WorkflowDesignDraftCompileRequest,
    WorkflowDesignDraftForkRequest,
    WorkflowDesignDraftPlanRequest,
    WorkflowDesignDraftUpdateRequest,
)
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import cached_runtime_payload, run_runtime_payload, runtime_service
from core.app_runtime.errors import RuntimeServiceError


router = APIRouter()


@router.get("/api/v1/workflow-design-drafts")
async def list_workflow_design_drafts_api(refresh: bool = False, serverId: str | None = None) -> dict[str, Any]:
    return await cached_runtime_payload(
        f"workflow_design_drafts:{serverId or 'default'}",
        10,
        lambda: runtime_service().list_workflow_design_drafts(server_id=serverId),
        status_code=400,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
        force_refresh=refresh,
    )


@router.post("/api/v1/workflow-design-drafts", status_code=201)
async def create_workflow_design_draft_api(payload: WorkflowDesignDraftCreateRequest) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().create_workflow_design_draft(payload.model_dump(by_alias=True, exclude_none=True, mode="json")),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )
    await invalidate_response_cache(prefixes=("workflow_design_drafts",))
    return result


@router.get("/api/v1/workflow-design-drafts/{draft_id}")
async def get_workflow_design_draft_api(draft_id: str, serverId: str | None = None) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_workflow_design_draft(draft_id, server_id=serverId),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )


@router.patch("/api/v1/workflow-design-drafts/{draft_id}")
async def update_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftUpdateRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().update_workflow_design_draft(
            draft_id,
            payload.model_dump(by_alias=True, exclude_none=True, mode="json"),
        ),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )
    await invalidate_response_cache(prefixes=("workflow_design_drafts",))
    return result


@router.post("/api/v1/workflow-design-drafts/{draft_id}/fork", status_code=201)
async def fork_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftForkRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().fork_workflow_design_draft(
            draft_id,
            payload.model_dump(exclude_none=True),
        ),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )
    await invalidate_response_cache(prefixes=("workflow_design_drafts",))
    return result


@router.delete("/api/v1/workflow-design-drafts/{draft_id}")
async def delete_workflow_design_draft_api(draft_id: str, serverId: str | None = None) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().delete_workflow_design_draft(draft_id, server_id=serverId),
        status_code=404,
        handled_errors=(RuntimeServiceError,),
        wrapper="data",
    )
    await invalidate_response_cache(prefixes=("workflow_design_drafts",))
    return result


@router.post("/api/v1/workflow-design-drafts/{draft_id}/plan")
async def plan_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftPlanRequest | None = None,
) -> dict[str, Any]:
    body = payload.model_dump(exclude_none=True) if payload else {}
    return await run_runtime_payload(
        lambda: runtime_service().plan_workflow_design_draft(draft_id, body),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )


@router.post("/api/v1/workflow-design-drafts/{draft_id}/compile")
async def compile_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftCompileRequest | None = None,
) -> dict[str, Any]:
    body = payload.model_dump(exclude_none=True) if payload else {}
    return await run_runtime_payload(
        lambda: runtime_service().compile_workflow_design_draft(draft_id, body),
        status_code=400,
        handled_errors=(RuntimeServiceError, ValueError, TypeError, KeyError),
        wrapper="data",
    )
