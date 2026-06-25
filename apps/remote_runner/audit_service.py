from __future__ import annotations

from typing import Any

from .governance_audit import list_governance_audit_events, record_governance_audit_event
from .route_utils import authorized_config, data_response, remote_runner_principal, run_sync


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
    principal = remote_runner_principal(cfg)
    await run_sync(
        record_governance_audit_event,
        cfg,
        action="audit.events.read",
        actor=principal.actor,
        subject_kind="governance_audit",
        subject_id="query",
        decision="allow",
        details={
            "filteredBySubjectKind": _present(subject_kind),
            "filteredBySubjectId": _present(subject_id),
            "filteredByAction": _present(action),
            "limit": int(limit),
            "returnedCount": len(events.get("items") if isinstance(events.get("items"), list) else []),
        },
    )
    return data_response(events)


async def _authorized_config_from_request(authorization: str | None, *, action: str | None = None):
    return await run_sync(authorized_config, authorization, action=action)


def _present(value: str | None) -> bool:
    return bool(str(value or "").strip())
