"""WorkflowDesignDraft routes for the remote runner API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from .api_models import (
    WorkflowDesignDraftCreateRequest,
    WorkflowDesignDraftCompileRequest,
    WorkflowDesignDraftForkRequest,
    WorkflowDesignDraftPlanRequest,
    WorkflowDesignDraftUpdateRequest,
)
from .route_utils import authorized_config, data_response
from .workflow_design_compiler import compile_workflow_design_project
from .workflow_design_planner import plan_workflow_design_draft
from .workflow_design_storage import (
    create_workflow_design_draft,
    delete_workflow_design_draft,
    fetch_workflow_design_draft,
    fork_workflow_design_draft,
    list_workflow_design_drafts,
    update_workflow_design_draft,
)


router = APIRouter()


@router.get("/api/v1/workflow-design-drafts")
async def get_workflow_design_drafts(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    return data_response({"items": list_workflow_design_drafts(cfg)})


@router.post("/api/v1/workflow-design-drafts", status_code=201)
async def create_workflow_design_draft_api(
    payload: WorkflowDesignDraftCreateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = create_workflow_design_draft(cfg, payload.draft.model_dump(by_alias=True, exclude_none=True, mode="json"))
    return data_response(item)


@router.get("/api/v1/workflow-design-drafts/{draft_id}")
async def get_workflow_design_draft_api(
    draft_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = fetch_workflow_design_draft(cfg, draft_id)
    if item is None:
        raise HTTPException(status_code=404, detail="WORKFLOW_DESIGN_DRAFT_NOT_FOUND")
    return data_response(item)


@router.patch("/api/v1/workflow-design-drafts/{draft_id}")
async def update_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftUpdateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        item = update_workflow_design_draft(
            cfg,
            draft_id,
            payload.draft.model_dump(by_alias=True, exclude_none=True, mode="json"),
            expected_revision=payload.expectedRevision,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="WORKFLOW_DESIGN_DRAFT_NOT_FOUND") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return data_response(item)


@router.post("/api/v1/workflow-design-drafts/{draft_id}/fork", status_code=201)
async def fork_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftForkRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        item = fork_workflow_design_draft(cfg, draft_id, name=payload.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="WORKFLOW_DESIGN_DRAFT_NOT_FOUND") from exc
    return data_response(item)


@router.delete("/api/v1/workflow-design-drafts/{draft_id}")
async def delete_workflow_design_draft_api(
    draft_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        delete_workflow_design_draft(cfg, draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="WORKFLOW_DESIGN_DRAFT_NOT_FOUND") from exc
    return data_response({"draftId": draft_id, "deleted": True})


@router.post("/api/v1/workflow-design-drafts/{draft_id}/plan")
async def plan_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftPlanRequest | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = fetch_workflow_design_draft(cfg, draft_id)
    if item is None:
        raise HTTPException(status_code=404, detail="WORKFLOW_DESIGN_DRAFT_NOT_FOUND")
    plan = await run_in_threadpool(
        plan_workflow_design_draft,
        cfg,
        item["draft"],
        preview_root=Path(cfg.work_dir) / "workflow-design-previews" / draft_id,
        draft_id=draft_id,
        revision=int(item["revision"]),
    )
    return data_response(plan)


@router.post("/api/v1/workflow-design-drafts/{draft_id}/compile")
async def compile_workflow_design_draft_api(
    draft_id: str,
    payload: WorkflowDesignDraftCompileRequest | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = fetch_workflow_design_draft(cfg, draft_id)
    if item is None:
        raise HTTPException(status_code=404, detail="WORKFLOW_DESIGN_DRAFT_NOT_FOUND")
    try:
        compiled = await run_in_threadpool(
            compile_workflow_design_project,
            cfg,
            item["draft"],
            export_dir=Path(cfg.work_dir) / "workflow-design-exports" / draft_id / f"rev-{item['revision']}",
            draft_id=draft_id,
            revision=int(item["revision"]),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return data_response(compiled)
