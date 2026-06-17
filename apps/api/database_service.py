from __future__ import annotations

from typing import Any

from apps.api.models import DatabaseManifestRequest, DatabaseUpdateRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import cached_runtime_payload, request_payload, run_runtime_payload, runtime_service


async def list_databases_from_request(refresh: bool) -> dict[str, Any]:
    return await cached_runtime_payload(
        "databases",
        30,
        runtime_service().list_databases,
        wrapper="raw",
        force_refresh=refresh,
    )


async def list_database_templates_from_request(refresh: bool) -> dict[str, Any]:
    return await cached_runtime_payload(
        "database_templates",
        60,
        runtime_service().list_database_templates,
        wrapper="raw",
        force_refresh=refresh,
    )


async def list_database_packs_from_request(refresh: bool) -> dict[str, Any]:
    return await cached_runtime_payload(
        "database_packs",
        60,
        runtime_service().list_database_packs,
        wrapper="raw",
        force_refresh=refresh,
    )


async def add_database_from_request(request: DatabaseManifestRequest) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().add_database(request_payload(request)),
        wrapper="raw",
    )
    await invalidate_response_cache("databases", "workflow_catalog")
    return result


async def update_database_from_request(
    database_id: str,
    request: DatabaseUpdateRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().update_database(
            database_id,
            request_payload(request),
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("databases", "workflow_catalog")
    return result


async def delete_database_from_request(database_id: str) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().delete_database(database_id),
        wrapper="raw",
    )
    await invalidate_response_cache("databases", "workflow_catalog")
    return result


async def check_database_from_request(database_id: str) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().check_database(database_id),
        wrapper="raw",
    )
    await invalidate_response_cache("databases")
    return result
