from __future__ import annotations

import shlex
import time
from typing import Any

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.base import BaseRuntimeManager
from core.app_runtime.remote_runner_stop import STOP_REMOTE_RUNNER_COMMAND


class RunnerManager(BaseRuntimeManager):
    def stop_remote_runner_service(self) -> dict[str, Any]:
        with self._service._lock:
            self._service._ensure_initialized()
            ssh_status = self._service._get_ssh_status_unlocked()
            server = self._service._build_primary_server_identity(ssh_status=ssh_status)
            server_id = str(server["serverId"]) if server is not None else ""
            record = self._service._get_server_registry_entry(server_id) if server_id else {}
            runner_mode = str(record.get("runner_mode") or "")
            ssh = self._service._ensure_ssh_connected()

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
            if server_id:
                self._service._save_server_registry_entry(server_id, {"last_health_snapshot": health})
            status = self._service._get_ssh_status_unlocked()

        if not ok:
            raise RuntimeServiceError(output or "failed to stop remote runner service")
        return {"data": {"ok": True, "output": output, "serverId": server_id}, "item": status}
