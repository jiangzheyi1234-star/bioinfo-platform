"""FastAPI routes for online and local tool capability search."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from apps.api.tool_capability_service import (
    get_tool_candidate_target_acceptance_from_request,
    get_tool_capabilities_index_status_from_request,
    list_snakemake_wrapper_catalog_from_request,
    list_tool_profile_catalog_from_request,
    recommend_tool_candidates_from_request,
    refresh_tool_capabilities_index_from_request,
    search_tool_candidates_from_request,
    search_tool_capabilities_from_request,
)


router = APIRouter()


@router.get("/api/v1/tool-capabilities/search", operation_id="searchToolCapabilities")
async def search_tool_capabilities_api(
    q: str = "",
    targetPlatform: str = "",
    limit: int = Query(default=20, ge=1, le=50),
    page: int = Query(default=1, ge=1),
    pageSize: int | None = Query(default=None, ge=1, le=50),
) -> dict[str, Any]:
    return await search_tool_capabilities_from_request(
        q=q,
        target_platform=targetPlatform,
        limit=limit,
        page=page,
        page_size=pageSize,
    )


@router.get("/api/v1/tool-capabilities/candidates", operation_id="searchToolCandidates")
async def search_tool_candidates_api(
    q: str = "",
    targetPlatform: str = "",
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    return await search_tool_candidates_from_request(
        q=q,
        target_platform=targetPlatform,
        page=page,
        page_size=pageSize,
    )


@router.get("/api/v1/tool-capabilities/candidate-recommendations", operation_id="recommendToolCandidates")
async def recommend_tool_candidates_api(
    q: str = "",
    outputType: str = "",
    outputKind: str = "",
    outputMimeType: str = "",
    outputData: str = "",
    outputFormat: str = "",
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    return await recommend_tool_candidates_from_request(
        q=q,
        output_port={
            "type": outputType,
            "kind": outputKind,
            "mimeType": outputMimeType,
            "data": outputData,
            "format": outputFormat,
        },
        page=page,
        page_size=pageSize,
    )


@router.get("/api/v1/tool-capabilities/target-acceptance", operation_id="getToolCandidateTargetAcceptance")
async def tool_candidate_target_acceptance_api(
    targetPlatform: str = "linux-64",
) -> dict[str, Any]:
    return await get_tool_candidate_target_acceptance_from_request(
        target_platform=targetPlatform,
    )


@router.get("/api/v1/tool-capabilities/snakemake-wrappers", operation_id="listSnakemakeWrapperCatalog")
async def list_snakemake_wrapper_catalog_api(
    q: str = "",
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    return await list_snakemake_wrapper_catalog_from_request(
        q=q,
        page=page,
        page_size=pageSize,
    )


@router.get("/api/v1/tool-capabilities/tool-profiles", operation_id="listToolProfileCatalog")
async def list_tool_profile_catalog_api(
    q: str = "",
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    return await list_tool_profile_catalog_from_request(
        q=q,
        page=page,
        page_size=pageSize,
    )


@router.get("/api/v1/tool-capabilities/index/status", operation_id="getToolCapabilitiesIndexStatus")
async def tool_capabilities_index_status_api() -> dict[str, Any]:
    return await get_tool_capabilities_index_status_from_request()


@router.post("/api/v1/tool-capabilities/index/refresh", operation_id="refreshToolCapabilitiesIndex")
async def refresh_tool_capabilities_index_api() -> dict[str, Any]:
    return await refresh_tool_capabilities_index_from_request()
