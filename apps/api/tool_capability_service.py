from __future__ import annotations

from typing import Any

from apps.api.bioconda_tool_index import bioconda_index_status, refresh_bioconda_index
from apps.api.route_utils import run_sync
from apps.api.tool_capabilities import search_tool_capabilities


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


async def get_tool_capabilities_index_status_from_request() -> dict[str, Any]:
    return await run_sync(lambda: {"data": bioconda_index_status()})


async def refresh_tool_capabilities_index_from_request() -> dict[str, Any]:
    return await run_sync(_refresh_bioconda_index_status)


def _refresh_bioconda_index_status() -> dict[str, Any]:
    refresh_bioconda_index()
    return {"data": bioconda_index_status()}
