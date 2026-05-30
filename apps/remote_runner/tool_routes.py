"""Tool registry routes for the remote runner API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from .api_models import ToolManifestRequest, ToolProductionEvidenceRequest, ToolRuleTemplateRequest
from .route_utils import authorized_config, data_response
from .tools import (
    ToolRegistryError,
    add_registered_tool,
    check_registered_tool,
    list_registered_tools,
    mark_registered_tool_production_enabled,
    remove_registered_tool,
    update_registered_tool_rule_template,
)


router = APIRouter()


def _tool_production_status_code(detail: str) -> int:
    if detail == "TOOL_NOT_FOUND":
        return 404
    if detail in {
        "TOOL_PRODUCTION_REQUIRES_OUTPUT_VALIDATION",
        "TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY",
        "TOOL_PRODUCTION_EVIDENCE_RUN_NOT_FOUND",
        "TOOL_PRODUCTION_EVIDENCE_RUN_NOT_COMPLETED",
        "TOOL_PRODUCTION_EVIDENCE_PIPELINE_MISMATCH",
        "TOOL_PRODUCTION_EVIDENCE_TOOL_MISMATCH",
        "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_REQUIRED",
        "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_NOT_FOUND",
        "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_EMPTY",
        "TOOL_PRODUCTION_EVIDENCE_DATABASE_MISMATCH",
        "TOOL_PRODUCTION_EVIDENCE_DATABASE_UNAVAILABLE",
    }:
        return 409
    return 400


@router.get("/api/v1/tools")
async def get_tools(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    return data_response({"items": list_registered_tools(cfg)})


@router.post("/api/v1/tools", status_code=201)
async def add_tool(payload: ToolManifestRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        item = add_registered_tool(cfg, payload.model_dump(exclude_none=True))
    except ToolRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return data_response(item)


@router.patch("/api/v1/tools/{tool_id}/rule-template")
async def update_tool_rule_template_api(
    tool_id: str,
    payload: ToolRuleTemplateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        item = update_registered_tool_rule_template(cfg, tool_id, payload.ruleTemplate)
    except ToolRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "TOOL_NOT_FOUND" else 400, detail=detail) from exc
    return data_response(item)


@router.delete("/api/v1/tools/{tool_id}")
async def delete_tool_api(tool_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        remove_registered_tool(cfg, tool_id)
    except ToolRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "TOOL_NOT_FOUND" else 400, detail=detail) from exc
    return data_response({"id": tool_id, "deleted": True})


@router.post("/api/v1/tools/{tool_id}/check")
async def check_tool_api(tool_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        item = await run_in_threadpool(check_registered_tool, cfg, tool_id)
    except ToolRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if detail == "TOOL_NOT_FOUND" else 400, detail=detail) from exc
    return data_response(item)


@router.post("/api/v1/tools/{tool_id}/production")
async def mark_tool_production_api(
    tool_id: str,
    payload: ToolProductionEvidenceRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    try:
        item = await run_in_threadpool(
            mark_registered_tool_production_enabled,
            cfg,
            tool_id,
            payload.model_dump(exclude_none=True),
        )
    except ToolRegistryError as exc:
        detail = str(exc)
        raise HTTPException(status_code=_tool_production_status_code(detail), detail=detail) from exc
    return data_response(item)
