from __future__ import annotations

from typing import Any

from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.errors import RemoteRunnerManagerError


UPGRADE_ACTIVE_LEASES_REASON = "RUNNER_UPGRADE_ACTIVE_LEASES"
UPGRADE_GUARD_SCHEMA_VERSION = "h2ometa.remote-runner-upgrade-guard.v1"


class RemoteRunnerBootstrapGuardMixin:
    def _guard_bootstrap_without_active_leases(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        bootstrap_metadata: dict[str, Any],
    ) -> None:
        if not str(server_record.get("bootstrap_version") or "").strip():
            return
        try:
            diagnostics = self.get_execution_diagnostics(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
            )
        except (RemoteRunnerClientError, RemoteRunnerManagerError) as exc:
            bootstrap_metadata["upgradeGuard"] = {
                "schemaVersion": UPGRADE_GUARD_SCHEMA_VERSION,
                "checked": False,
                "reason": "execution-diagnostics-unavailable",
                "message": str(exc) or exc.__class__.__name__,
            }
            return
        active_leases = diagnostics.get("activeLeases")
        if not isinstance(active_leases, list):
            raise self._manager_error(
                "remote runner upgrade guard failed: execution diagnostics activeLeases is not a list",
                bootstrap_metadata=bootstrap_metadata,
            )
        protected_leases = [_protected_lease_summary(item) for item in active_leases]
        bootstrap_metadata["upgradeGuard"] = {
            "schemaVersion": UPGRADE_GUARD_SCHEMA_VERSION,
            "checked": True,
            "activeLeaseCount": len(protected_leases),
            "protectedLeases": protected_leases,
        }
        if protected_leases:
            raise self._manager_error(
                "remote runner upgrade blocked because active workflow run leases exist",
                bootstrap_metadata=bootstrap_metadata,
                status_code=409,
                detail={
                    "reasonCode": UPGRADE_ACTIVE_LEASES_REASON,
                    "serverId": server_id,
                    "activeLeaseCount": len(protected_leases),
                    "activeLeases": protected_leases,
                    "nextAction": "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_UPGRADE",
                },
            )


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
