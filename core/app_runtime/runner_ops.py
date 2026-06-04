from __future__ import annotations

import shlex
import time
from typing import Any, Optional

from core.app_runtime.runner_database_ops import RunnerDatabaseOperationsMixin
from core.app_runtime.runner_execution_ops import RunnerExecutionOperationsMixin
from core.app_runtime.runner_file_ops import RunnerFileOperationsMixin
from core.app_runtime.runner_tool_ops import RunnerToolOperationsMixin
from core.app_runtime.runner_workflow_design_ops import RunnerWorkflowDesignOperationsMixin
from core.app_runtime.remote_runner_call import call_remote_runner
from core.app_runtime.remote_runner_stop import STOP_REMOTE_RUNNER_COMMAND

from .errors import RuntimeServiceError


class RunnerOperationsMixin(
    RunnerDatabaseOperationsMixin,
    RunnerExecutionOperationsMixin,
    RunnerFileOperationsMixin,
    RunnerToolOperationsMixin,
    RunnerWorkflowDesignOperationsMixin,
):
    def stop_remote_runner_service(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            server_id = str(server["serverId"]) if server is not None else ""
            record = self._get_server_registry_entry(server_id) if server_id else {}
            runner_mode = str(record.get("runner_mode") or "")
            ssh = self._ensure_ssh_connected()

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

        with self._lock:
            if server_id:
                self._save_server_registry_entry(server_id, {"last_health_snapshot": health})
            status = self._get_ssh_status_unlocked()

        if not ok:
            raise RuntimeServiceError(output or "failed to stop remote runner service")
        return {"data": {"ok": True, "output": output, "serverId": server_id}, "item": status}

    @staticmethod
    def _call_remote_runner(func, /, **kwargs):
        return call_remote_runner(func, **kwargs)

    def _require_existing_runner_ready(
        self,
        *,
        preferred_server_id: Optional[str] = None,
    ):
        ssh_status = self._get_ssh_status_unlocked()
        server = self._build_primary_server_identity(ssh_status=ssh_status)
        if server is None:
            raise RuntimeServiceError("No server configured")
        server_id = str(preferred_server_id or server["serverId"] or "").strip() or server["serverId"]
        if server_id != server["serverId"]:
            raise RuntimeServiceError(f"Server not found: {server_id}")
        if not bool(server.get("connected")):
            raise RuntimeServiceError("SSH is not connected")
        record = self._get_server_registry_entry(server_id)
        if not record.get("bootstrap_version"):
            raise RuntimeServiceError("Remote runner is not prepared")
        snapshot = record.get("last_health_snapshot")
        if isinstance(snapshot, dict) and not bool((snapshot.get("ready") or {}).get("ok")):
            message = str((snapshot.get("ready") or {}).get("message") or "Remote runner is not ready.")
            raise RuntimeServiceError(message)
        ssh = self._ensure_ssh_connected()
        return server_id, ssh, record
