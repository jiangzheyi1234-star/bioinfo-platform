from __future__ import annotations

from typing import Any

from .api_models import DatabaseManifestRequest, DatabaseUpdateRequest
from .database_pack_catalog import database_pack_catalog_response
from .database_templates import list_database_templates
from .databases import (
    add_verified_reference_database,
    check_reference_database,
    list_reference_databases,
    remove_reference_database,
    update_reference_database,
)
from .route_utils import authorized_config, data_response, request_payload, run_sync


async def list_databases_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    items = await run_sync(list_reference_databases, cfg)
    return data_response({"items": items})


async def list_database_templates_from_request(authorization: str | None) -> dict[str, Any]:
    authorized_config(authorization)
    items = await run_sync(list_database_templates)
    return data_response({"items": items})


async def list_database_packs_from_request(authorization: str | None) -> dict[str, Any]:
    authorized_config(authorization)
    catalog = await run_sync(database_pack_catalog_response)
    return data_response(catalog)


async def add_database_from_request(
    payload: DatabaseManifestRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(add_verified_reference_database, cfg, request_payload(payload))
    return data_response(item)


async def delete_database_from_request(
    database_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    await run_sync(remove_reference_database, cfg, database_id)
    return data_response({"id": database_id, "deleted": True})


async def update_database_from_request(
    database_id: str,
    payload: DatabaseUpdateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(update_reference_database, cfg, database_id, request_payload(payload))
    return data_response(item)


async def check_database_from_request(
    database_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(check_reference_database, cfg, database_id)
    return data_response(item)
