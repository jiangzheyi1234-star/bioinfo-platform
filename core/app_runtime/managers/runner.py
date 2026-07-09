from __future__ import annotations

import shlex
import time
from typing import Any

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.base import BaseRuntimeManager
from core.app_runtime.remote_runner_stop import STOP_REMOTE_RUNNER_COMMAND
from core.app_runtime.runner_stop_state import build_manual_runner_stop_intent
from core.contracts.execution_activity import (
    EXECUTION_ACTIVITY_ACTIVE_WORKFLOW_LEASES_REASON,
    EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
)
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.install_lock import reclaim_orphaned_install_lock
from core.remote_runner.lifecycle_guard_owner import execution_lifecycle_guard_owner
from core.remote_runner.layout import remote_runner_bootstrap_layout


RUNNER_STOP_ACTIVE_LEASES_REASON = "RUNNER_STOP_ACTIVE_LEASES"
RUNNER_STOP_BLOCKED_REASON = "RUNNER_STOP_BLOCKED"
RUNNER_STOP_DIAGNOSTICS_UNAVAILABLE_REASON = "RUNNER_STOP_DIAGNOSTICS_UNAVAILABLE"
RUNNER_DIAGNOSTICS_REPAIR_NOT_PREPARED_REASON = "RUNNER_DIAGNOSTICS_REPAIR_NOT_PREPARED"
RUNNER_DIAGNOSTICS_REPAIR_STOP_FAILED_REASON = "RUNNER_DIAGNOSTICS_REPAIR_STOP_FAILED"
_ACTIVITY_COUNT_KEYS = (
    "activeLeaseCount",
    "allocatedResourceCount",
    "resourceWaitCount",
    "queuedJobCount",
    "claimedJobCount",
    "runningSlotCount",
)


class RunnerManager(BaseRuntimeManager):
    def repair_remote_runner_diagnostics(self, server_id: str) -> dict[str, Any]:
        with self._service._lock:
            self._service._ensure_initialized()
            ssh_status = self._service._get_ssh_status_unlocked()
            server = self._service._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            record = self._service._get_server_registry_entry(server_id)
            if not record.get("bootstrap_version"):
                raise RuntimeServiceError(
                    "Remote runner is not prepared; start it before diagnostics repair.",
                    status_code=409,
                    detail={
                        "reasonCode": RUNNER_DIAGNOSTICS_REPAIR_NOT_PREPARED_REASON,
                        "serverId": server_id,
                        "nextAction": "START_RUNNER_BEFORE_DIAGNOSTICS_REPAIR",
                    },
                )
            runner_mode = str(record.get("runner_mode") or "")
            ssh = self._service._ensure_ssh_connected()
            manager = self._service._service_locator.remote_runner_manager

        command = f"H2OMETA_RUNNER_MODE={shlex.quote(runner_mode)}\n{STOP_REMOTE_RUNNER_COMMAND}"
        exit_code, stdout, stderr = ssh.run(command, timeout=30)
        stop_output = (stdout or stderr or "").strip()
        stopped_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if exit_code != 0:
            raise RuntimeServiceError(
                stop_output or "remote runner diagnostics repair failed to stop the current service",
                status_code=409,
                detail={
                    "reasonCode": RUNNER_DIAGNOSTICS_REPAIR_STOP_FAILED_REASON,
                    "serverId": server_id,
                    "nextAction": "CHECK_OPERATOR_DIAGNOSTICS",
                    "output": stop_output,
                },
            )

        close_tunnel = getattr(ssh, "close_local_tunnel", None)
        if callable(close_tunnel):
            close_tunnel(f"runner-{server_id}")

        lock_status = "not-checked"
        lock_reclaimed = False
        try:
            home_dir = manager._resolve_remote_home(ssh)
            lock_dir = remote_runner_bootstrap_layout(home_dir, REMOTE_RUNNER_VERSION).install_lock
            lock_reclaimed, lock_status = reclaim_orphaned_install_lock(
                ssh_service=ssh,
                lock_dir=lock_dir,
            )
        except Exception as exc:  # pragma: no cover - diagnostic evidence only
            lock_status = f"error:{exc.__class__.__name__}:{str(exc)}"

        stop_intent = build_manual_runner_stop_intent(server_id=server_id, stopped_at=stopped_at)
        stop_intent["source"] = "diagnostics-repair"
        repair_record = {
            "schemaVersion": "h2ometa.runner-diagnostics-repair.v1",
            "serverId": server_id,
            "startedAt": stopped_at,
            "stopOutput": stop_output,
            "installLockReclaimed": lock_reclaimed,
            "installLockStatus": lock_status,
        }
        with self._service._lock:
            self._service._save_server_registry_entry(
                server_id,
                {
                    "last_health_snapshot": _repairing_health(server_id, checked_at=stopped_at),
                    "runner_stop_intent": stop_intent,
                    "runner_diagnostics_repair": repair_record,
                },
            )

        try:
            result = self._service.start_remote_runner(server_id)
        except RuntimeServiceError:
            with self._service._lock:
                failed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                self._service._save_server_registry_entry(
                    server_id,
                    {
                        "runner_diagnostics_repair": {
                            **repair_record,
                            "finishedAt": failed_at,
                            "status": "failed",
                        }
                    },
                )
            raise

        finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._service._lock:
            self._service._save_server_registry_entry(
                server_id,
                {
                    "runner_diagnostics_repair": {
                        **repair_record,
                        "finishedAt": finished_at,
                        "status": "succeeded",
                    }
                },
            )
        data = result.get("data") if isinstance(result, dict) else None
        if isinstance(data, dict):
            data["lifecycleAction"] = "repair-diagnostics"
            data["repair"] = {
                **repair_record,
                "finishedAt": finished_at,
                "status": "succeeded",
            }
        return result

    def stop_remote_runner_service(self, server_id: str) -> dict[str, Any]:
        with self._service._lock:
            self._service._ensure_initialized()
            ssh_status = self._service._get_ssh_status_unlocked()
            server = self._service._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            record = self._service._get_server_registry_entry(server_id)
            if not record.get("bootstrap_version"):
                raise RuntimeServiceError(
                    "Remote runner is not prepared; start it before stop.",
                    status_code=409,
                    detail={
                        "reasonCode": "RUNNER_STOP_NOT_PREPARED",
                        "serverId": server_id,
                        "nextAction": "START_RUNNER_BEFORE_STOP",
                    },
                )
            runner_mode = str(record.get("runner_mode") or "")
            ssh = self._service._ensure_ssh_connected()
            manager = self._service._service_locator.remote_runner_manager

        self._guard_runner_stop_when_execution_idle(
            server_id=server_id,
            ssh=ssh,
            manager=manager,
            record=record,
        )

        command = f"H2OMETA_RUNNER_MODE={shlex.quote(runner_mode)}\n{STOP_REMOTE_RUNNER_COMMAND}"
        exit_code, stdout, stderr = ssh.run(command, timeout=30)

        output = (stdout or stderr or "").strip()
        ok = exit_code == 0
        health = {
            "serverId": server_id,
            "state": "stopped" if ok else "failed",
            "startup": {"ok": ok, "message": "远程服务停止命令已执行。" if ok else "远程服务停止失败。"},
            "live": {"ok": False, "message": "远程服务已停止。" if ok else "远程服务停止失败。"},
            "ready": {"ok": False, "message": "远程服务已手动停止。" if ok else output or "远程服务停止失败。"},
            "reasonCode": "RUNNER_STOPPED" if ok else "RUNNER_STOP_FAILED",
            "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        with self._service._lock:
            patch: dict[str, Any] = {"last_health_snapshot": health}
            if ok:
                patch["runner_stop_intent"] = build_manual_runner_stop_intent(
                    server_id=server_id,
                    stopped_at=str(health["checkedAt"]),
                )
            record = self._service._save_server_registry_entry(server_id, patch)

        if not ok:
            raise RuntimeServiceError(output or "failed to stop remote runner service")
        close_tunnel = getattr(ssh, "close_local_tunnel", None)
        if callable(close_tunnel):
            close_tunnel(f"runner-{server_id}")
        return {
            "data": {
                "ok": True,
                "output": output,
                "serverId": server_id,
                "runner": self._service._compose_runner_payload(
                    registry_entry=record,
                    health=health,
                    local_tunnels=self._service._local_tunnel_snapshots(ssh),
                ),
                "health": health,
                "lifecycleAction": "stop",
                "completedAt": health["checkedAt"],
            }
        }

    def _guard_runner_stop_when_execution_idle(
        self,
        *,
        server_id: str,
        ssh,
        manager,
        record: dict[str, Any],
    ) -> None:
        try:
            guard = self._service._call_remote_runner(
                manager.request_execution_lifecycle_guard,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                action="stop",
                owner=execution_lifecycle_guard_owner(server_id=server_id, action="stop"),
                ttl_seconds=600,
                timeout=30,
            )
            activity = _activity_from_lifecycle_guard_payload(guard)
        except RuntimeServiceError as exc:
            if exc.status_code == 409 and isinstance(exc.detail, dict) and exc.detail.get("schemaVersion") == EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION:
                activity = _activity_from_lifecycle_guard_payload(exc.detail)
                block_reasons = [str(item) for item in activity["blockReasons"]]
                raise _runner_stop_blocked_error(
                    server_id=server_id,
                    activity=activity,
                    block_reasons=block_reasons,
                ) from exc
            raise RuntimeServiceError(
                "remote runner stop guard failed because execution diagnostics are unavailable",
                status_code=409,
                detail={
                    "reasonCode": RUNNER_STOP_DIAGNOSTICS_UNAVAILABLE_REASON,
                    "serverId": server_id,
                    "nextAction": "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_STOP",
                },
            ) from exc
        block_reasons = [str(item) for item in activity["blockReasons"]]
        if not block_reasons:
            return
        raise _runner_stop_blocked_error(
            server_id=server_id,
            activity=activity,
            block_reasons=block_reasons,
        )


def _stop_block_reason_code(block_reasons: list[str]) -> str:
    if EXECUTION_ACTIVITY_ACTIVE_WORKFLOW_LEASES_REASON in block_reasons:
        return RUNNER_STOP_ACTIVE_LEASES_REASON
    return RUNNER_STOP_BLOCKED_REASON


def _runner_stop_blocked_error(
    *,
    server_id: str,
    activity: dict[str, Any],
    block_reasons: list[str],
) -> RuntimeServiceError:
    return RuntimeServiceError(
        "remote runner stop blocked because runner execution state is not idle",
        status_code=409,
        detail={
            "reasonCode": _stop_block_reason_code(block_reasons),
            "serverId": server_id,
            "blockReasons": block_reasons,
            "activeLeaseCount": activity["activeLeaseCount"],
            "allocatedResourceCount": activity["allocatedResourceCount"],
            "resourceWaitCount": activity["resourceWaitCount"],
            "queuedJobCount": activity["queuedJobCount"],
            "claimedJobCount": activity["claimedJobCount"],
            "runningSlotCount": activity["runningSlotCount"],
            "nextAction": "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_STOP",
        },
    )


def _repairing_health(server_id: str, *, checked_at: str) -> dict[str, Any]:
    return {
        "serverId": server_id,
        "state": "recovering",
        "startup": {"ok": True, "message": "Remote runner diagnostics repair is restarting the service."},
        "live": {"ok": False, "message": "Remote runner service is being restarted."},
        "ready": {"ok": False, "message": "Remote runner diagnostics repair is in progress."},
        "workflowRuntime": {},
        "pipelineRegistry": {},
        "reasonCode": "RUNNER_DIAGNOSTICS_REPAIRING",
        "checkedAt": checked_at,
    }


def _activity_from_lifecycle_guard_payload(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION:
        raise RuntimeServiceError("remote runner execution lifecycle guard response is invalid")
    block_reasons = value.get("blockReasons")
    if not isinstance(block_reasons, list):
        raise RuntimeServiceError("remote runner execution lifecycle guard blockReasons is not a list")
    for key in _ACTIVITY_COUNT_KEYS:
        if key not in value:
            raise RuntimeServiceError(f"remote runner execution lifecycle guard {key} is missing")
    return {
        "activeLeaseCount": _non_negative_int(value.get("activeLeaseCount")),
        "allocatedResourceCount": _non_negative_int(value.get("allocatedResourceCount")),
        "resourceWaitCount": _non_negative_int(value.get("resourceWaitCount")),
        "queuedJobCount": _non_negative_int(value.get("queuedJobCount")),
        "claimedJobCount": _non_negative_int(value.get("claimedJobCount")),
        "runningSlotCount": _non_negative_int(value.get("runningSlotCount")),
        "blockReasons": [str(item) for item in block_reasons],
    }


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
