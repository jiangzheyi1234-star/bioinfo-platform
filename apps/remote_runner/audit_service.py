from __future__ import annotations

from typing import Any

from .governance_audit import list_governance_audit_events
from .route_utils import authorized_config, data_response, run_sync


async def list_governance_audit_events_request(
    authorization: str | None,
    *,
    subject_kind: str | None,
    subject_id: str | None,
    action: str | None,
    limit: int,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization, action="audit.events.read")
    events = await run_sync(
        list_governance_audit_events,
        cfg,
        subject_kind=subject_kind,
        subject_id=subject_id,
        action=action,
        limit=limit,
    )
    return data_response(events)


async def _authorized_config_from_request(authorization: str | None, *, action: str | None = None):
    return await run_sync(authorized_config, authorization, action=action)
