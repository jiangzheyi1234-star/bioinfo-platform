"""Governance audit routes for the local API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from apps.api.audit_service import list_governance_audit_events_from_request


router = APIRouter()


@router.get("/api/v1/audit/events")
async def list_governance_audit_events(
    serverId: str | None = None,
    subjectKind: str | None = None,
    subjectId: str | None = None,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    return await list_governance_audit_events_from_request(
        server_id=serverId,
        subject_kind=subjectKind,
        subject_id=subjectId,
        action=action,
        limit=limit,
    )
