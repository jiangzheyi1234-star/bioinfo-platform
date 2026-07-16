from __future__ import annotations

from typing import Any

from core.contracts.execution_activity import (
    EXECUTION_ACTIVITY_ACTIVE_WORKFLOW_LEASES_REASON,
    EXECUTION_LIFECYCLE_GUARD_ALREADY_ACTIVE_REASON,
    EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
    EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
    require_execution_lifecycle_quiescence_coverage,
    summarize_execution_activity,
)
from core.contracts.remote_endpoints import EXECUTION_LIFECYCLE_GUARD_RELEASE, RemoteEndpointContractError
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.layout import REMOTE_RUNNER_SERVICE_NAME
from core.remote_runner.lifecycle_guard_owner import execution_lifecycle_guard_owner


UPGRADE_ACTIVE_LEASES_REASON = "RUNNER_UPGRADE_ACTIVE_LEASES"
UPGRADE_EXECUTION_BUSY_REASON = "RUNNER_UPGRADE_EXECUTION_BUSY"
BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON = "RUNNER_BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE"
UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON = "RUNNER_UPGRADE_DIAGNOSTICS_UNAVAILABLE"
UPGRADE_GUARD_SCHEMA_VERSION = "h2ometa.remote-runner-upgrade-guard.v1"
MANUAL_RUNNER_STOP_REASON = "RUNNER_STOPPED"
MANUAL_RUNNER_STOP_INTENT_KEY = "runner_stop_intent"
COLD_STOP_RECOVERY_REASON = "runner-cold-stopped"
COLD_STOP_PROOF_SCHEMA_VERSION = "h2ometa.remote-runner-cold-stop-proof.v1"
_ACTIVITY_COUNT_KEYS = (
    "activeLeaseCount",
    "allocatedResourceCount",
    "resourceWaitCount",
    "queuedJobCount",
    "claimedJobCount",
    "runningSlotCount",
    "queuedToolPrepareJobCount",
    "runningToolPrepareJobCount",
    "activeToolPrepareClaimCount",
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
        previous_release: str = "",
        target_release: str = "",
        previous_config_present: bool = False,
    ) -> None:
        action = str(bootstrap_action or "").strip() or "ensure"
        existing_guard = bootstrap_metadata.get("upgradeGuard")
        if (
            action == "upgrade"
            and isinstance(existing_guard, dict)
            and existing_guard.get("checked") is True
            and existing_guard.get("idle") is True
        ):
            return
        if not _has_prior_runner_evidence(
            server_record,
            previous_release=previous_release,
            previous_config_present=previous_config_present,
        ):
            return
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
                previous_release=previous_release,
                target_release=target_release,
            )
            existing_guard = bootstrap_metadata.get("upgradeGuard")
            if (
                isinstance(existing_guard, dict)
                and existing_guard.get("checked") is False
                and existing_guard.get("reason") == COLD_STOP_RECOVERY_REASON
            ):
                return
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
            "queuedToolPrepareJobCount": activity["queuedToolPrepareJobCount"],
            "runningToolPrepareJobCount": activity["runningToolPrepareJobCount"],
            "activeToolPrepareClaimCount": activity["activeToolPrepareClaimCount"],
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
                "queuedToolPrepareJobCount": activity["queuedToolPrepareJobCount"],
                "runningToolPrepareJobCount": activity["runningToolPrepareJobCount"],
                "activeToolPrepareClaimCount": activity["activeToolPrepareClaimCount"],
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
        previous_release: str,
        target_release: str,
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
            if (
                exc.status_code == 409
                and isinstance(exc.detail, dict)
                and exc.detail.get("schemaVersion") == EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION
                and exc.detail.get("reasonCode") == EXECUTION_LIFECYCLE_GUARD_ALREADY_ACTIVE_REASON
                and not isinstance(exc.detail.get("blockReasons"), list)
            ):
                active = exc.detail.get("activeMaintenance")
                active = active if isinstance(active, dict) else {}
                bootstrap_metadata["upgradeGuard"] = {
                    "schemaVersion": UPGRADE_GUARD_SCHEMA_VERSION,
                    "checked": False,
                    "reason": "execution-lifecycle-guard-already-active",
                    "message": str(exc) or "remote runner lifecycle guard is already active",
                    "activeAction": str(active.get("action") or ""),
                    "activeOwner": str(active.get("owner") or ""),
                    "activeExpiresAt": str(active.get("expiresAt") or ""),
                }
                raise
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
                    "queuedToolPrepareJobCount": activity["queuedToolPrepareJobCount"],
                    "runningToolPrepareJobCount": activity["runningToolPrepareJobCount"],
                    "activeToolPrepareClaimCount": activity["activeToolPrepareClaimCount"],
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
            if self._record_cold_stopped_recovery_if_safe(
                ssh_service=ssh_service,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                previous_release=previous_release,
                target_release=target_release,
                exc=exc,
            ):
                return _empty_activity()
            self._raise_diagnostics_unavailable(
                server_id=server_id,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                reason="execution-lifecycle-guard-unavailable",
                exc=exc,
            )
        except RemoteRunnerClientError as exc:
            if self._record_cold_stopped_recovery_if_safe(
                ssh_service=ssh_service,
                bootstrap_metadata=bootstrap_metadata,
                action=action,
                previous_release=previous_release,
                target_release=target_release,
                exc=exc,
            ):
                return _empty_activity()
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

    @staticmethod
    def _record_cold_stopped_recovery_if_safe(
        *,
        ssh_service,
        bootstrap_metadata: dict[str, Any],
        action: str,
        previous_release: str,
        target_release: str,
        exc: Exception,
    ) -> bool:
        previous = str(previous_release or "").strip().rstrip("/")
        target = str(target_release or "").strip().rstrip("/")
        if action != "ensure" or not previous or previous != target:
            return False
        proof = _probe_remote_runner_cold_stop(ssh_service)
        if proof is None:
            return False
        bootstrap_metadata["upgradeGuard"] = {
            "schemaVersion": UPGRADE_GUARD_SCHEMA_VERSION,
            "checked": False,
            "reason": COLD_STOP_RECOVERY_REASON,
            "message": str(exc) or exc.__class__.__name__,
            "coldStopProof": proof,
        }
        return True

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
            "queuedToolPrepareJobCount": activity["queuedToolPrepareJobCount"],
            "runningToolPrepareJobCount": activity["runningToolPrepareJobCount"],
            "activeToolPrepareClaimCount": activity["activeToolPrepareClaimCount"],
            "blockReasons": [str(item) for item in activity["blockReasons"]],
            "protectedLeases": protected_leases,
        }
        _attach_lifecycle_guard_metadata(bootstrap_metadata["upgradeGuard"], guard)

    @classmethod
    def _release_bootstrap_lifecycle_guard(
        cls,
        *,
        client,
        server_id: str,
        bootstrap_action: str,
        bootstrap_metadata: dict[str, Any],
        allow_absent: bool = False,
    ) -> dict[str, Any] | None:
        guard = bootstrap_metadata.get("upgradeGuard") if isinstance(bootstrap_metadata.get("upgradeGuard"), dict) else {}
        owner = str(guard.get("maintenanceOwner") or "").strip()
        action = str(bootstrap_action or "").strip() or "ensure"
        release_action = action
        if not owner and action == "start":
            release_action = "stop"
            owner = execution_lifecycle_guard_owner(server_id=server_id, action=release_action)
        if not owner:
            return None
        try:
            release = cls._call_lifecycle_guard_endpoint_with_client(
                client=client,
                endpoint_id=EXECUTION_LIFECYCLE_GUARD_RELEASE,
                payload={"action": release_action, "owner": owner},
            )
        except (RemoteEndpointContractError, RemoteRunnerClientError, RemoteRunnerManagerError) as exc:
            bootstrap_metadata["upgradeGuardRelease"] = {
                "schemaVersion": "h2ometa.remote-runner-upgrade-guard-release.v1",
                "released": False,
                "reason": "execution-lifecycle-guard-release-failed",
                "message": str(exc) or exc.__class__.__name__,
            }
            raise cls._manager_error(
                "remote runner bootstrap guard release failed",
                bootstrap_metadata=bootstrap_metadata,
                status_code=409,
                detail={
                    "reasonCode": BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON,
                    "serverId": server_id,
                    "nextAction": "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_BOOTSTRAP",
                },
            ) from exc
        release_absent = (
            allow_absent
            and release.get("released") is False
            and not bool(release.get("previous"))
        )
        if (
            release.get("schemaVersion") != EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION
            or (release.get("released") is not True and not release_absent)
            or str(release.get("action") or "") != release_action
            or str(release.get("owner") or "") != owner
        ):
            bootstrap_metadata["upgradeGuardRelease"] = {
                "schemaVersion": "h2ometa.remote-runner-upgrade-guard-release.v1",
                "released": False,
                "reason": "execution-lifecycle-guard-release-unconfirmed",
                "message": "remote runner lifecycle guard release response did not match the requested owner",
                "response": release,
            }
            raise cls._manager_error(
                "remote runner bootstrap guard release was not confirmed",
                bootstrap_metadata=bootstrap_metadata,
                status_code=409,
            )
        bootstrap_metadata["upgradeGuardRelease"] = release
        return release

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
        detail = {
            "reasonCode": reason_code,
            "serverId": server_id,
            "nextAction": next_action,
        }
        remote_detail = getattr(exc, "detail", None)
        if isinstance(remote_detail, dict):
            detail["lifecycleGuardError"] = remote_detail
        raise self._manager_error(
            "remote runner bootstrap guard failed because execution diagnostics are unavailable",
            bootstrap_metadata=bootstrap_metadata,
            status_code=409,
            detail=detail,
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
    remote_detail = getattr(exc, "detail", None)
    if isinstance(remote_detail, dict):
        bootstrap_metadata["upgradeGuard"]["lifecycleGuardError"] = remote_detail


def _probe_remote_runner_cold_stop(ssh_service) -> dict[str, Any] | None:
    command = (
        "if ! command -v pgrep >/dev/null 2>&1; then printf 'unknown\\n'; "
        "elif pgrep -f '[r]emote_runner.run' >/dev/null 2>&1; then printf 'running\\n'; "
        "elif command -v systemctl >/dev/null 2>&1 "
        "&& systemctl --user show-environment >/dev/null 2>&1; then "
        f"state=$(systemctl --user is-active {REMOTE_RUNNER_SERVICE_NAME} 2>/dev/null || true); "
        "case \"$state\" in active|activating|reloading|deactivating) printf 'running\\n';; "
        "*) printf 'stopped\\n';; esac; else printf 'stopped\\n'; fi"
    )
    try:
        exit_code, stdout, _stderr = ssh_service.run(command, timeout=10)
    except Exception:
        return None
    if exit_code != 0 or str(stdout or "").strip() != "stopped":
        return None
    return {
        "schemaVersion": COLD_STOP_PROOF_SCHEMA_VERSION,
        "checked": True,
        "runnerProcessAbsent": True,
        "activeServiceAbsent": True,
    }


def _execution_busy_reason_code(block_reasons: list[str]) -> str:
    if EXECUTION_ACTIVITY_ACTIVE_WORKFLOW_LEASES_REASON in block_reasons:
        return UPGRADE_ACTIVE_LEASES_REASON
    return UPGRADE_EXECUTION_BUSY_REASON


def _execution_busy_next_action(action: str) -> str:
    if action == "upgrade":
        return "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_UPGRADE"
    return "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_BOOTSTRAP"


def _activity_from_lifecycle_guard_payload(value: dict[str, Any], *, make_error: type[Exception]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION:
        raise make_error("remote runner execution lifecycle guard response is invalid")
    require_execution_lifecycle_quiescence_coverage(value, make_error=make_error)
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
        "queuedToolPrepareJobCount": _non_negative_int(value.get("queuedToolPrepareJobCount")),
        "runningToolPrepareJobCount": _non_negative_int(value.get("runningToolPrepareJobCount")),
        "activeToolPrepareClaimCount": _non_negative_int(value.get("activeToolPrepareClaimCount")),
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
        "queuedToolPrepareJobCount": 0,
        "runningToolPrepareJobCount": 0,
        "activeToolPrepareClaimCount": 0,
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
    return (
        isinstance(intent, dict)
        and bool(intent.get("active"))
        and str(intent.get("reasonCode") or "") == MANUAL_RUNNER_STOP_REASON
    )


def _has_prior_runner_evidence(
    server_record: dict[str, Any],
    *,
    previous_release: str,
    previous_config_present: bool,
) -> bool:
    return (
        bool(str(server_record.get("bootstrap_version") or "").strip())
        or bool(str(previous_release or "").strip())
        or (
            bool(previous_config_present)
            and bool(str(server_record.get("token_ref") or "").strip())
        )
    )
