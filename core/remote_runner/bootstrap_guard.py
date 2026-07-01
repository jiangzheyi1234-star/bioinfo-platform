from __future__ import annotations

from typing import Any

from core.contracts.execution_activity import summarize_execution_activity
from core.contracts.remote_endpoints import EXECUTION_LIFECYCLE_GUARD_RELEASE
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.lifecycle_guard_owner import execution_lifecycle_guard_owner


UPGRADE_ACTIVE_LEASES_REASON = "RUNNER_UPGRADE_ACTIVE_LEASES"
UPGRADE_EXECUTION_BUSY_REASON = "RUNNER_UPGRADE_EXECUTION_BUSY"
BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON = "RUNNER_BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE"
UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON = "RUNNER_UPGRADE_DIAGNOSTICS_UNAVAILABLE"
UPGRADE_GUARD_SCHEMA_VERSION = "h2ometa.remote-runner-upgrade-guard.v1"
EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION = "h2ometa.execution-lifecycle-guard.v1"
MANUAL_RUNNER_STOP_REASON = "RUNNER_STOPPED"
MANUAL_RUNNER_STOP_INTENT_KEY = "runner_stop_intent"
_ACTIVITY_COUNT_KEYS = (
    "activeLeaseCount",
    "allocatedResourceCount",
    "resourceWaitCount",
    "queuedJobCount",
    "claimedJobCount",
    "runningSlotCount",
)


class RemoteRunnerBootstrapGuardMixin:
    def _guard_bootstrap_when_execution_idle(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        bootstrap_metadata: dict[str, Any],
        bootstrap_action: str = "ensure",
    ) -> None:
        if not str(server_record.get("bootstrap_version") or "").strip():
            return
        action = str(bootstrap_action or "").strip() or "ensure"
        if action == "start":
            activity = self._bootstrap_start_activity(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
            )
            existing_guard = bootstrap_metadata.get("upgradeGuard")
            if isinstance(existing_guard, dict) and existing_guard.get("checked") is False:
                return
        else:
            activity = self._request_bootstrap_lifecycle_guard(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
            )
        try:
            protected_leases = [_protected_lease_summary(item) for item in activity["activeLeases"]]
        except RemoteRunnerManagerError as exc:
            self._raise_diagnostics_unavailable(
                server_id=server_id,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                reason="execution-diagnostics-invalid",
                exc=exc,
            )
        block_reasons = [str(item) for item in activity["blockReasons"]]
        bootstrap_metadata["upgradeGuard"] = {
            "schemaVersion": UPGRADE_GUARD_SCHEMA_VERSION,
            "checked": True,
            "idle": not block_reasons,
            "activeLeaseCount": activity["activeLeaseCount"],
            "allocatedResourceCount": activity["allocatedResourceCount"],
            "resourceWaitCount": activity["resourceWaitCount"],
            "queuedJobCount": activity["queuedJobCount"],
            "claimedJobCount": activity["claimedJobCount"],
            "runningSlotCount": activity["runningSlotCount"],
            "blockReasons": block_reasons,
            "protectedLeases": protected_leases,
        }
        lifecycle_guard = activity.get("lifecycleGuard") if isinstance(activity.get("lifecycleGuard"), dict) else {}
        _attach_lifecycle_guard_metadata(bootstrap_metadata["upgradeGuard"], lifecycle_guard)
        if block_reasons:
            detail = {
                "reasonCode": _execution_busy_reason_code(block_reasons),
                "serverId": server_id,
                "blockReasons": block_reasons,
                "activeLeaseCount": activity["activeLeaseCount"],
                "allocatedResourceCount": activity["allocatedResourceCount"],
                "resourceWaitCount": activity["resourceWaitCount"],
                "queuedJobCount": activity["queuedJobCount"],
                "claimedJobCount": activity["claimedJobCount"],
                "runningSlotCount": activity["runningSlotCount"],
                "nextAction": _execution_busy_next_action(action),
            }
            if protected_leases:
                detail["activeLeases"] = protected_leases
            raise self._manager_error(
                "remote runner bootstrap blocked because runner execution state is not idle",
                bootstrap_metadata=bootstrap_metadata,
                status_code=409,
                detail=detail,
            )

    def _bootstrap_start_activity(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        bootstrap_metadata: dict[str, Any],
        action: str,
    ) -> dict[str, Any]:
        try:
            diagnostics = self.get_execution_diagnostics(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
            )
        except (RemoteRunnerClientError, RemoteRunnerManagerError) as exc:
            if _is_manual_runner_stop_record(server_record):
                _record_diagnostics_unavailable(
                    bootstrap_metadata=bootstrap_metadata,
                    reason="execution-diagnostics-unavailable",
                    exc=exc,
                )
                return _empty_activity()
            self._raise_diagnostics_unavailable(
                server_id=server_id,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                reason="execution-diagnostics-unavailable",
                exc=exc,
            )
        try:
            return summarize_execution_activity(
                diagnostics,
                make_error=self._manager_error,
                block_queued_jobs=False,
            )
        except RemoteRunnerManagerError as exc:
            self._raise_diagnostics_unavailable(
                server_id=server_id,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                reason="execution-diagnostics-invalid",
                exc=exc,
            )

    def _request_bootstrap_lifecycle_guard(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        bootstrap_metadata: dict[str, Any],
        action: str,
    ) -> dict[str, Any]:
        owner = execution_lifecycle_guard_owner(server_id=server_id, action=action)
        try:
            guard = self.request_execution_lifecycle_guard(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                action=action,
                owner=owner,
                ttl_seconds=600,
                timeout=30,
            )
        except RemoteRunnerManagerError as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict) and exc.detail.get("schemaVersion") == EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION:
                try:
                    activity = _activity_from_lifecycle_guard_payload(exc.detail, make_error=self._manager_error)
                except RemoteRunnerManagerError as invalid_exc:
                    self._raise_diagnostics_unavailable(
                        server_id=server_id,
                        bootstrap_metadata=bootstrap_metadata,
                        action=action,
                        reason="execution-diagnostics-invalid",
                        exc=invalid_exc,
                    )
                try:
                    self._record_lifecycle_guard_metadata(
                        bootstrap_metadata=bootstrap_metadata,
                        activity=activity,
                        guard=exc.detail,
                    )
                except RemoteRunnerManagerError as invalid_exc:
                    self._raise_diagnostics_unavailable(
                        server_id=server_id,
                        bootstrap_metadata=bootstrap_metadata,
                        action=action,
                        reason="execution-diagnostics-invalid",
                        exc=invalid_exc,
                    )
                block_reasons = [str(item) for item in activity["blockReasons"]]
                detail = {
                    "reasonCode": _execution_busy_reason_code(block_reasons),
                    "serverId": server_id,
                    "blockReasons": block_reasons,
                    "activeLeaseCount": activity["activeLeaseCount"],
                    "allocatedResourceCount": activity["allocatedResourceCount"],
                    "resourceWaitCount": activity["resourceWaitCount"],
                    "queuedJobCount": activity["queuedJobCount"],
                    "claimedJobCount": activity["claimedJobCount"],
                    "runningSlotCount": activity["runningSlotCount"],
                    "nextAction": _execution_busy_next_action(action),
                }
                try:
                    active_leases = [_protected_lease_summary(item) for item in activity["activeLeases"]]
                except RemoteRunnerManagerError as invalid_exc:
                    self._raise_diagnostics_unavailable(
                        server_id=server_id,
                        bootstrap_metadata=bootstrap_metadata,
                        action=action,
                        reason="execution-diagnostics-invalid",
                        exc=invalid_exc,
                    )
                if active_leases:
                    detail["activeLeases"] = active_leases
                raise self._manager_error(
                    "remote runner bootstrap blocked because runner execution state is not idle",
                    bootstrap_metadata=bootstrap_metadata,
                    status_code=409,
                    detail=detail,
                ) from exc
            self._raise_diagnostics_unavailable(
                server_id=server_id,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                reason="execution-lifecycle-guard-unavailable",
                exc=exc,
            )
        except RemoteRunnerClientError as exc:
            self._raise_diagnostics_unavailable(
                server_id=server_id,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                reason="execution-lifecycle-guard-unavailable",
                exc=exc,
            )
        try:
            activity = _activity_from_lifecycle_guard_payload(guard, make_error=self._manager_error)
        except RemoteRunnerManagerError as exc:
            self._raise_diagnostics_unavailable(
                server_id=server_id,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                reason="execution-diagnostics-invalid",
                exc=exc,
            )
        activity["lifecycleGuard"] = guard
        return activity

    def _record_lifecycle_guard_metadata(
        self,
        *,
        bootstrap_metadata: dict[str, Any],
        activity: dict[str, Any],
        guard: dict[str, Any],
    ) -> None:
        protected_leases = [_protected_lease_summary(item) for item in activity["activeLeases"]]
        bootstrap_metadata["upgradeGuard"] = {
            "schemaVersion": UPGRADE_GUARD_SCHEMA_VERSION,
            "checked": True,
            "idle": not activity["blockReasons"],
            "activeLeaseCount": activity["activeLeaseCount"],
            "allocatedResourceCount": activity["allocatedResourceCount"],
            "resourceWaitCount": activity["resourceWaitCount"],
            "queuedJobCount": activity["queuedJobCount"],
            "claimedJobCount": activity["claimedJobCount"],
            "runningSlotCount": activity["runningSlotCount"],
            "blockReasons": [str(item) for item in activity["blockReasons"]],
            "protectedLeases": protected_leases,
        }
        _attach_lifecycle_guard_metadata(bootstrap_metadata["upgradeGuard"], guard)

    def _release_bootstrap_lifecycle_guard(
        self,
        *,
        client,
        server_id: str,
        bootstrap_action: str,
        bootstrap_metadata: dict[str, Any],
    ) -> None:
        guard = bootstrap_metadata.get("upgradeGuard") if isinstance(bootstrap_metadata.get("upgradeGuard"), dict) else {}
        owner = str(guard.get("maintenanceOwner") or "").strip()
        action = str(bootstrap_action or "").strip() or "ensure"
        release_action = action
        if not owner and action == "start":
            release_action = "stop"
            owner = execution_lifecycle_guard_owner(server_id=server_id, action=release_action)
        if not owner:
            return
        try:
            release = self._call_lifecycle_guard_endpoint_with_client(
                client=client,
                endpoint_id=EXECUTION_LIFECYCLE_GUARD_RELEASE,
                payload={"action": release_action, "owner": owner},
            )
        except (RemoteRunnerClientError, RemoteRunnerManagerError) as exc:
            bootstrap_metadata["upgradeGuardRelease"] = {
                "schemaVersion": "h2ometa.remote-runner-upgrade-guard-release.v1",
                "released": False,
                "reason": "execution-lifecycle-guard-release-failed",
                "message": str(exc) or exc.__class__.__name__,
            }
            raise self._manager_error(
                "remote runner bootstrap guard release failed",
                bootstrap_metadata=bootstrap_metadata,
                status_code=409,
                detail={
                    "reasonCode": BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON,
                    "serverId": server_id,
                    "nextAction": "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_BOOTSTRAP",
                },
            ) from exc
        bootstrap_metadata["upgradeGuardRelease"] = release

    def _raise_diagnostics_unavailable(
        self,
        *,
        server_id: str,
        bootstrap_metadata: dict[str, Any],
        action: str,
        reason: str,
        exc: Exception,
    ) -> None:
        _record_diagnostics_unavailable(bootstrap_metadata=bootstrap_metadata, reason=reason, exc=exc)
        reason_code = (
            UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON
            if action == "upgrade"
            else BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON
        )
        next_action = (
            "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_UPGRADE"
            if action == "upgrade"
            else "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_BOOTSTRAP"
        )
        raise self._manager_error(
            "remote runner bootstrap guard failed because execution diagnostics are unavailable",
            bootstrap_metadata=bootstrap_metadata,
            status_code=409,
            detail={
                "reasonCode": reason_code,
                "serverId": server_id,
                "nextAction": next_action,
            },
        ) from exc


def _record_diagnostics_unavailable(
    *,
    bootstrap_metadata: dict[str, Any],
    reason: str,
    exc: Exception,
) -> None:
    bootstrap_metadata["upgradeGuard"] = {
        "schemaVersion": UPGRADE_GUARD_SCHEMA_VERSION,
        "checked": False,
        "reason": reason,
        "message": str(exc) or exc.__class__.__name__,
    }


def _execution_busy_reason_code(block_reasons: list[str]) -> str:
    if "active-workflow-leases" in block_reasons:
        return UPGRADE_ACTIVE_LEASES_REASON
    return UPGRADE_EXECUTION_BUSY_REASON


def _execution_busy_next_action(action: str) -> str:
    if action == "upgrade":
        return "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_UPGRADE"
    return "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_BOOTSTRAP"


def _activity_from_lifecycle_guard_payload(value: dict[str, Any], *, make_error: type[Exception]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION:
        raise make_error("remote runner execution lifecycle guard response is invalid")
    block_reasons = value.get("blockReasons")
    if not isinstance(block_reasons, list):
        raise make_error("remote runner execution lifecycle guard blockReasons is not a list")
    active_leases = value.get("activeLeases") or []
    if not isinstance(active_leases, list):
        raise make_error("remote runner execution lifecycle guard activeLeases is not a list")
    for key in _ACTIVITY_COUNT_KEYS:
        if key not in value:
            raise make_error(f"remote runner execution lifecycle guard {key} is missing")
    return {
        "activeLeases": active_leases,
        "allocatedResources": [],
        "resourceWaits": [],
        "workerHealth": {},
        "queueMetrics": {},
        "activeLeaseCount": _non_negative_int(value.get("activeLeaseCount")),
        "allocatedResourceCount": _non_negative_int(value.get("allocatedResourceCount")),
        "resourceWaitCount": _non_negative_int(value.get("resourceWaitCount")),
        "queuedJobCount": _non_negative_int(value.get("queuedJobCount")),
        "claimedJobCount": _non_negative_int(value.get("claimedJobCount")),
        "runningSlotCount": _non_negative_int(value.get("runningSlotCount")),
        "blockReasons": [str(item) for item in block_reasons],
    }


def _attach_lifecycle_guard_metadata(target: dict[str, Any], guard: dict[str, Any]) -> None:
    owner = str(guard.get("owner") or "").strip()
    if owner:
        target["maintenanceOwner"] = owner
    requested_at = str(guard.get("requestedAt") or "").strip()
    if requested_at:
        target["maintenanceRequestedAt"] = requested_at
    expires_at = str(guard.get("expiresAt") or "").strip()
    if expires_at:
        target["maintenanceExpiresAt"] = expires_at
    if "drainRequestedWorkerCount" in guard:
        target["drainRequestedWorkerCount"] = _non_negative_int(guard.get("drainRequestedWorkerCount"))


def _empty_activity() -> dict[str, Any]:
    return {
        "activeLeases": [],
        "allocatedResources": [],
        "resourceWaits": [],
        "workerHealth": {},
        "queueMetrics": {},
        "activeLeaseCount": 0,
        "allocatedResourceCount": 0,
        "resourceWaitCount": 0,
        "queuedJobCount": 0,
        "claimedJobCount": 0,
        "runningSlotCount": 0,
        "blockReasons": [],
    }


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _protected_lease_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RemoteRunnerManagerError("remote runner upgrade guard failed: active lease is not an object")
    return {
        "runId": str(value.get("runId") or ""),
        "attemptId": str(value.get("attemptId") or ""),
        "leaseGeneration": int(value.get("leaseGeneration") or 0),
        "workerId": str(value.get("workerId") or ""),
        "slotId": str(value.get("slotId") or ""),
        "expiresAt": str(value.get("expiresAt") or ""),
    }


def _is_manual_runner_stop_record(server_record: dict[str, Any]) -> bool:
    intent = server_record.get(MANUAL_RUNNER_STOP_INTENT_KEY)
    if isinstance(intent, dict) and bool(intent.get("active")) and str(intent.get("reasonCode") or "") == MANUAL_RUNNER_STOP_REASON:
        return True
    snapshot = server_record.get("last_health_snapshot")
    reason_code = str(snapshot.get("reasonCode") or "") if isinstance(snapshot, dict) else ""
    return reason_code == MANUAL_RUNNER_STOP_REASON
