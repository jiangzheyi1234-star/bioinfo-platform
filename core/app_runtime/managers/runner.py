from __future__ import annotations

import shlex
import time
from typing import Any

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.base import BaseRuntimeManager
from core.app_runtime.remote_runner_stop import STOP_REMOTE_RUNNER_COMMAND
from core.app_runtime.runner_stop_state import build_manual_runner_stop_intent
from core.remote_runner.release_prune import summarize_execution_activity


RUNNER_STOP_ACTIVE_LEASES_REASON = "RUNNER_STOP_ACTIVE_LEASES"
RUNNER_STOP_BLOCKED_REASON = "RUNNER_STOP_BLOCKED"
RUNNER_STOP_DIAGNOSTICS_UNAVAILABLE_REASON = "RUNNER_STOP_DIAGNOSTICS_UNAVAILABLE"


class RunnerManager(BaseRuntimeManager):
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
            diagnostics = self._service._call_remote_runner(
                manager.get_execution_diagnostics,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
            )
            activity = summarize_execution_activity(diagnostics, make_error=RuntimeServiceError)
        except RuntimeServiceError as exc:
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
        raise RuntimeServiceError(
            "remote runner stop blocked because runner execution state is not idle",
            status_code=409,
            detail={
                "reasonCode": _stop_block_reason_code(block_reasons),
                "serverId": server_id,
                "blockReasons": block_reasons,
                "activeLeaseCount": activity["activeLeaseCount"],
                "allocatedResourceCount": activity["allocatedResourceCount"],
                "resourceWaitCount": activity["resourceWaitCount"],
                "claimedJobCount": activity["claimedJobCount"],
                "runningSlotCount": activity["runningSlotCount"],
                "nextAction": "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_STOP",
            },
        )


def _stop_block_reason_code(block_reasons: list[str]) -> str:
    if "active-workflow-leases" in block_reasons:
        return RUNNER_STOP_ACTIVE_LEASES_REASON
    return RUNNER_STOP_BLOCKED_REASON
