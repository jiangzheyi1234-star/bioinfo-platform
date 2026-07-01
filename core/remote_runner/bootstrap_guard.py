from __future__ import annotations

from typing import Any

from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.release_prune import summarize_execution_activity


UPGRADE_ACTIVE_LEASES_REASON = "RUNNER_UPGRADE_ACTIVE_LEASES"
UPGRADE_EXECUTION_BUSY_REASON = "RUNNER_UPGRADE_EXECUTION_BUSY"
BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON = "RUNNER_BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE"
UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON = "RUNNER_UPGRADE_DIAGNOSTICS_UNAVAILABLE"
UPGRADE_GUARD_SCHEMA_VERSION = "h2ometa.remote-runner-upgrade-guard.v1"
MANUAL_RUNNER_STOP_REASON = "RUNNER_STOPPED"
MANUAL_RUNNER_STOP_INTENT_KEY = "runner_stop_intent"


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
        try:
            diagnostics = self.get_execution_diagnostics(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
            )
        except (RemoteRunnerClientError, RemoteRunnerManagerError) as exc:
            if action == "start" and _is_manual_runner_stop_record(server_record):
                _record_diagnostics_unavailable(
                    bootstrap_metadata=bootstrap_metadata,
                    reason="execution-diagnostics-unavailable",
                    exc=exc,
                )
                return
            self._raise_diagnostics_unavailable(
                server_id=server_id,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                reason="execution-diagnostics-unavailable",
                exc=exc,
            )
        try:
            activity = summarize_execution_activity(diagnostics, make_error=self._manager_error)
        except RemoteRunnerManagerError as exc:
            self._raise_diagnostics_unavailable(
                server_id=server_id,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                reason="execution-diagnostics-invalid",
                exc=exc,
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
            "claimedJobCount": activity["claimedJobCount"],
            "runningSlotCount": activity["runningSlotCount"],
            "blockReasons": block_reasons,
            "protectedLeases": protected_leases,
        }
        if block_reasons:
            detail = {
                "reasonCode": _execution_busy_reason_code(block_reasons),
                "serverId": server_id,
                "blockReasons": block_reasons,
                "activeLeaseCount": activity["activeLeaseCount"],
                "allocatedResourceCount": activity["allocatedResourceCount"],
                "resourceWaitCount": activity["resourceWaitCount"],
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
