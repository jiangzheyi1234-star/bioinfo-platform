from __future__ import annotations

from typing import Any

from apps.api.bioconda_tool_index import bioconda_index_status, refresh_bioconda_index
from apps.api.route_utils import run_sync, runtime_service
from apps.api.snakemake_wrappers import catalog_snakemake_wrappers
from apps.api.tool_candidate_catalog import search_tool_candidates
from apps.api.tool_candidate_recommendations import recommend_tool_candidates
from apps.api.tool_candidate_target_acceptance import bio_agent_catalog_target_acceptance
from apps.api.tool_capabilities import search_tool_capabilities
from apps.api.tool_profile_catalog import catalog_tool_profiles


async def search_tool_capabilities_from_request(
    *,
    q: str,
    target_platform: str,
    limit: int,
    page: int,
    page_size: int | None,
) -> dict[str, Any]:
    resolved_page_size = page_size or limit
    return await run_sync(
        lambda: search_tool_capabilities(
            q,
            target_platform=target_platform,
            limit=resolved_page_size,
            page=page,
            page_size=resolved_page_size,
        ),
    )


async def search_tool_candidates_from_request(
    *,
    q: str,
    target_platform: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    return await run_sync(
        lambda: {
            "data": search_tool_candidates(
                q,
                target_platform=target_platform,
                page=page,
                page_size=page_size,
            )
        },
    )


async def recommend_tool_candidates_from_request(
    *,
    q: str,
    output_port: dict[str, Any],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    runtime = runtime_service()
    return await run_sync(
        lambda: {
            "data": _recommend_tool_candidates_with_registered_tools(
                runtime=runtime,
                output_port=output_port,
                query=q,
                page=page,
                page_size=page_size,
            )
        },
    )


def _recommend_tool_candidates_with_registered_tools(
    *,
    runtime: Any,
    output_port: dict[str, Any],
    query: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    return recommend_tool_candidates(
        output_port=output_port,
        query=query,
        page=page,
        page_size=page_size,
        registered_tools=_registered_tools_from_runtime_payload(runtime.list_tools()),
    )


def _registered_tools_from_runtime_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            items = data.get("items")
        else:
            items = payload.get("items")
    else:
        items = None
    if not isinstance(items, list):
        raise ValueError("Invalid tools registry payload: expected an items list")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("Invalid tools registry payload: tool items must be objects")
    return items


async def get_tool_candidate_target_acceptance_from_request(*, target_platform: str) -> dict[str, Any]:
    return await run_sync(
        lambda: {
            "data": bio_agent_catalog_target_acceptance(
                target_platform=target_platform,
            )
        },
    )


async def get_tool_capabilities_index_status_from_request() -> dict[str, Any]:
    return await run_sync(lambda: {"data": bioconda_index_status()})


async def list_snakemake_wrapper_catalog_from_request(
    *,
    q: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    return await run_sync(
        lambda: {
            "data": catalog_snakemake_wrappers(
                query=q,
                page=page,
                page_size=page_size,
            )
        },
    )


async def list_tool_profile_catalog_from_request(
    *,
    q: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    return await run_sync(
        lambda: {
            "data": catalog_tool_profiles(
                query=q,
                page=page,
                page_size=page_size,
            )
        },
    )


async def refresh_tool_capabilities_index_from_request() -> dict[str, Any]:
    return await run_sync(_refresh_bioconda_index_status)


def _refresh_bioconda_index_status() -> dict[str, Any]:
    refresh_bioconda_index()
    return {"data": bioconda_index_status()}
