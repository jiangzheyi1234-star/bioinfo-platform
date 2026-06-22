from __future__ import annotations

from typing import Any

from apps.api.route_utils import run_runtime_payload, runtime_service


async def list_governance_audit_events_from_request(
    *,
    server_id: str | None,
    subject_kind: str | None,
    subject_id: str | None,
    action: str | None,
    limit: int,
) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().list_governance_audit_events(
            server_id=server_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            action=action,
            limit=limit,
        ),
        wrapper="raw",
    )
