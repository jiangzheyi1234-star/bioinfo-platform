from __future__ import annotations

from typing import Any

from .api_models import ExecutionLifecycleGuardReleaseRequest, ExecutionLifecycleGuardRequest
from .errors import RemoteRunnerOperationBlockedError
from .execution_lifecycle_guard import release_execution_lifecycle_guard, request_execution_lifecycle_guard
from .governance_audit import record_governance_audit_event
from .route_utils import authorized_config, data_response, run_sync


async def request_execution_lifecycle_guard_from_request(
    payload: ExecutionLifecycleGuardRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await run_sync(_authorized_lifecycle_guard_config, authorization)
    try:
        result = await run_sync(
            request_execution_lifecycle_guard,
            cfg,
            action=payload.action,
            owner=payload.owner,
            ttl_seconds=payload.ttlSeconds,
        )
    except RemoteRunnerOperationBlockedError as exc:
        await run_sync(
            _record_lifecycle_audit,
            cfg,
            action="execution.lifecycle_guard",
            owner=payload.owner,
            decision="deny",
            reason_code=str(exc.payload.get("reasonCode") or str(exc)),
            details=exc.payload,
        )
        raise
    await run_sync(
        _record_lifecycle_audit,
        cfg,
        action="execution.lifecycle_guard",
        owner=payload.owner,
        decision="allow",
        reason_code="",
        details=result,
    )
    return data_response(result)


async def release_execution_lifecycle_guard_from_request(
    payload: ExecutionLifecycleGuardReleaseRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await run_sync(_authorized_lifecycle_guard_release_config, authorization)
    result = await run_sync(
        release_execution_lifecycle_guard,
        cfg,
        action=payload.action,
        owner=payload.owner,
    )
    await run_sync(
        _record_lifecycle_audit,
        cfg,
        action="execution.lifecycle_guard.release",
        owner=payload.owner,
        decision="allow",
        reason_code="",
        details=result,
    )
    return data_response(result)


def _record_lifecycle_audit(
    cfg,
    *,
    action: str,
    owner: str,
    decision: str,
    reason_code: str,
    details: dict[str, Any],
) -> None:
    record_governance_audit_event(
        cfg,
        action=action,
        actor=cfg.api_token_actor or "remote-runner-api",
        subject_kind="execution_lifecycle",
        subject_id=str(owner or "execution-lifecycle"),
        decision=decision,
        reason_code=reason_code,
        details=_audit_details(details),
    )


def _authorized_lifecycle_guard_config(authorization: str | None):
    return authorized_config(authorization, action="execution.lifecycle_guard")


def _authorized_lifecycle_guard_release_config(authorization: str | None):
    return authorized_config(authorization, action="execution.lifecycle_guard.release")


def _audit_details(details: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": str(details.get("action") or ""),
        "owner": str(details.get("owner") or details.get("requestedOwner") or ""),
        "idle": bool(details.get("idle")),
        "maintenanceActive": bool(details.get("maintenanceActive") or details.get("activeMaintenance")),
        "released": bool(details.get("released")),
        "reasonCode": str(details.get("reasonCode") or ""),
        "blockReasons": list(details.get("blockReasons") or []),
        "activeLeaseCount": int(details.get("activeLeaseCount") or 0),
        "queuedJobCount": int(details.get("queuedJobCount") or 0),
        "claimedJobCount": int(details.get("claimedJobCount") or 0),
        "runningSlotCount": int(details.get("runningSlotCount") or 0),
    }
