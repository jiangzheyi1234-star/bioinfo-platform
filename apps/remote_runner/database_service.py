from __future__ import annotations

from typing import Any

from .api_models import DatabaseManifestRequest, DatabaseUpdateRequest
from .database_pack_catalog import database_pack_catalog_response
from .database_templates import list_database_templates
from .governance_audit import record_governance_audit_event
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
    cfg = authorized_config(authorization, action="database.create")
    item = await run_sync(add_verified_reference_database, cfg, request_payload(payload))
    await _record_database_governance_event(cfg, action="database.create", item=item)
    return data_response(item)


async def delete_database_from_request(
    database_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="database.delete")
    await run_sync(remove_reference_database, cfg, database_id)
    await run_sync(
        record_governance_audit_event,
        cfg,
        action="database.delete",
        subject_kind="database",
        subject_id=database_id,
        actor="remote-runner-api",
        details={"databaseId": database_id},
    )
    return data_response({"id": database_id, "deleted": True})


async def update_database_from_request(
    database_id: str,
    payload: DatabaseUpdateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="database.update")
    body = request_payload(payload)
    item = await run_sync(update_reference_database, cfg, database_id, body)
    await _record_database_governance_event(
        cfg,
        action="database.update",
        item=item,
        extra_details={"changedFields": sorted(body)},
    )
    return data_response(item)


async def check_database_from_request(
    database_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization, action="database.check")
    item = await run_sync(check_reference_database, cfg, database_id)
    await _record_database_governance_event(cfg, action="database.check", item=item)
    return data_response(item)


async def _record_database_governance_event(
    cfg: Any,
    *,
    action: str,
    item: dict[str, Any],
    extra_details: dict[str, Any] | None = None,
) -> None:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    database_id = str(item.get("id") or item.get("databaseId") or "")
    await run_sync(
        record_governance_audit_event,
        cfg,
        action=action,
        subject_kind="database",
        subject_id=database_id,
        actor="remote-runner-api",
        details={
            "databaseId": database_id,
            "templateId": str(metadata.get("templateId") or item.get("templateId") or ""),
            "type": str(item.get("type") or ""),
            "version": str(item.get("version") or ""),
            "status": str(item.get("status") or ""),
            **(extra_details or {}),
        },
    )
