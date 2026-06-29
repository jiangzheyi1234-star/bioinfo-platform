from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from core.contracts.remote_endpoints import GOVERNANCE_AUDIT_EVENTS_READ, REMOTE_ENDPOINTS

from .audit_service import list_governance_audit_events_request
from .route_headers import AuthorizationHeader


router = APIRouter()


@router.get("/api/v1/audit/events", operation_id=REMOTE_ENDPOINTS[GOVERNANCE_AUDIT_EVENTS_READ].operation_id)
async def list_governance_audit_events_api(
    subject_kind: str | None = Query(default=None, alias="subjectKind"),
    subject_id: str | None = Query(default=None, alias="subjectId"),
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await list_governance_audit_events_request(
        authorization,
        subject_kind=subject_kind,
        subject_id=subject_id,
        action=action,
        limit=limit,
    )
