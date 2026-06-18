"""FastAPI routes for online and local tool capability search."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from apps.api.tool_capability_service import (
    delete_bio_tool_pack_from_request,
    disable_bio_tool_pack_from_request,
    enable_bio_tool_pack_from_request,
    get_capability_graph_snapshot_from_request,
    get_tool_capabilities_index_status_from_request,
    import_bio_tool_pack_from_request,
    list_bio_tool_packs_from_request,
    list_snakemake_wrapper_catalog_from_request,
    list_tool_profile_catalog_from_request,
    prepare_tool_validation_queue_from_request,
    review_bio_tool_pack_from_request,
    refresh_tool_capabilities_index_from_request,
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


@router.get("/api/v1/tool-capabilities/capability-graph", operation_id="getCapabilityGraphSnapshot")
async def capability_graph_snapshot_api(
    q: str = "",
    targetPlatform: str = "linux-64",
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=100),
    agentSelectableOnly: bool = False,
) -> dict[str, Any]:
    return await get_capability_graph_snapshot_from_request(
        q=q,
        target_platform=targetPlatform,
        page=page,
        page_size=pageSize,
        agent_selectable_only=agentSelectableOnly,
    )


@router.post("/api/v1/tool-capabilities/validation-queue/prepare", operation_id="prepareToolValidationQueue")
async def prepare_tool_validation_queue_api(
    targetPlatform: str = "linux-64",
    maxItems: int = Query(default=3, ge=1, le=30),
) -> dict[str, Any]:
    return await prepare_tool_validation_queue_from_request(
        target_platform=targetPlatform,
        max_items=maxItems,
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


@router.get("/api/v1/tool-capabilities/tool-packs", operation_id="listBioToolPacks")
async def list_bio_tool_packs_api() -> dict[str, Any]:
    return await list_bio_tool_packs_from_request()


@router.post("/api/v1/tool-capabilities/tool-packs/review", operation_id="reviewBioToolPack")
async def review_bio_tool_pack_api(payload: dict[str, Any]) -> dict[str, Any]:
    return await review_bio_tool_pack_from_request(payload)


@router.post("/api/v1/tool-capabilities/tool-packs", operation_id="importBioToolPack")
async def import_bio_tool_pack_api(
    payload: dict[str, Any],
    enable: bool = False,
) -> dict[str, Any]:
    return await import_bio_tool_pack_from_request(payload, enable=enable)


@router.post("/api/v1/tool-capabilities/tool-packs/{pack_id}/enable", operation_id="enableBioToolPack")
async def enable_bio_tool_pack_api(pack_id: str) -> dict[str, Any]:
    return await enable_bio_tool_pack_from_request(pack_id)


@router.post("/api/v1/tool-capabilities/tool-packs/{pack_id}/disable", operation_id="disableBioToolPack")
async def disable_bio_tool_pack_api(pack_id: str) -> dict[str, Any]:
    return await disable_bio_tool_pack_from_request(pack_id)


@router.delete("/api/v1/tool-capabilities/tool-packs/{pack_id}", operation_id="deleteBioToolPack")
async def delete_bio_tool_pack_api(pack_id: str) -> dict[str, Any]:
    return await delete_bio_tool_pack_from_request(pack_id)


@router.get("/api/v1/tool-capabilities/index/status", operation_id="getToolCapabilitiesIndexStatus")
async def tool_capabilities_index_status_api() -> dict[str, Any]:
    return await get_tool_capabilities_index_status_from_request()


@router.post("/api/v1/tool-capabilities/index/refresh", operation_id="refreshToolCapabilitiesIndex")
async def refresh_tool_capabilities_index_api() -> dict[str, Any]:
    return await refresh_tool_capabilities_index_from_request()
