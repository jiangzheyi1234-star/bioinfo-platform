from __future__ import annotations

from pathlib import Path
from typing import Any

from .api_models import (
    WorkflowDesignDraftCreateRequest,
    WorkflowDesignDraftForkRequest,
    WorkflowDesignDraftUpdateRequest,
)
from .config import RemoteRunnerConfig
from .route_utils import authorized_config, data_response, request_payload, run_sync
from .workflow_design_compiler import compile_workflow_design_project
from .workflow_design_planner import plan_workflow_design_draft
from .workflow_design_storage import (
    create_workflow_design_draft,
    delete_workflow_design_draft,
    fork_workflow_design_draft,
    list_workflow_design_drafts,
    require_workflow_design_draft,
    update_workflow_design_draft,
)


def create_workflow_design_draft_from_request(
    cfg: RemoteRunnerConfig,
    request: WorkflowDesignDraftCreateRequest,
) -> dict[str, Any]:
    return create_workflow_design_draft(
        cfg,
        request_payload(request.draft),
    )


def update_workflow_design_draft_from_request(
    cfg: RemoteRunnerConfig,
    draft_id: str,
    request: WorkflowDesignDraftUpdateRequest,
) -> dict[str, Any]:
    return update_workflow_design_draft(
        cfg,
        draft_id,
        request_payload(request.draft),
        expected_revision=request.expectedRevision,
    )


def fork_workflow_design_draft_from_request(
    cfg: RemoteRunnerConfig,
    draft_id: str,
    request: WorkflowDesignDraftForkRequest,
) -> dict[str, Any]:
    return fork_workflow_design_draft(cfg, draft_id, name=request.name)


async def list_workflow_design_drafts_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    items = await run_sync(list_workflow_design_drafts, cfg)
    return data_response({"items": items})


async def create_workflow_design_draft_response_from_request(
    request: WorkflowDesignDraftCreateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(create_workflow_design_draft_from_request, cfg, request)
    return data_response(item)


async def get_workflow_design_draft_from_request(
    draft_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(require_workflow_design_draft, cfg, draft_id)
    return data_response(item)


async def update_workflow_design_draft_response_from_request(
    draft_id: str,
    request: WorkflowDesignDraftUpdateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(update_workflow_design_draft_from_request, cfg, draft_id, request)
    return data_response(item)


async def fork_workflow_design_draft_response_from_request(
    draft_id: str,
    request: WorkflowDesignDraftForkRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(fork_workflow_design_draft_from_request, cfg, draft_id, request)
    return data_response(item)


async def delete_workflow_design_draft_from_request(
    draft_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    await run_sync(delete_workflow_design_draft, cfg, draft_id)
    return data_response({"draftId": draft_id, "deleted": True})


async def plan_workflow_design_draft_from_request(
    draft_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(plan_workflow_design_draft_preview, cfg, draft_id)
    return data_response(item)


async def compile_workflow_design_draft_from_request(
    draft_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(compile_workflow_design_draft_export, cfg, draft_id)
    return data_response(item)


def plan_workflow_design_draft_preview(cfg: RemoteRunnerConfig, draft_id: str) -> dict[str, Any]:
    item = require_workflow_design_draft(cfg, draft_id)
    return plan_workflow_design_draft(
        cfg,
        item["draft"],
        preview_root=Path(cfg.work_dir) / "workflow-design-previews" / draft_id,
        draft_id=draft_id,
        revision=int(item["revision"]),
    )


def compile_workflow_design_draft_export(cfg: RemoteRunnerConfig, draft_id: str) -> dict[str, Any]:
    item = require_workflow_design_draft(cfg, draft_id)
    return compile_workflow_design_project(
        cfg,
        item["draft"],
        export_dir=Path(cfg.work_dir) / "workflow-design-exports" / draft_id / f"rev-{item['revision']}",
        draft_id=draft_id,
        revision=int(item["revision"]),
    )
