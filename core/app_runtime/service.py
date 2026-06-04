"""Runtime service layer shared by API and desktop shell."""

import threading
import time
import uuid
from typing import Any, Optional

from config import (
    store_runner_token,
)
from core.remote.ssh_service import SSHService, TerminalSession
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.runner_ops import RunnerOperationsMixin
from core.app_runtime.server_state import RuntimeServerStateMixin
from core.app_runtime.ssh_connection import RuntimeSshConnectionMixin
from core.app_runtime.terminal_sessions import RuntimeTerminalSessionMixin


class ServiceLocator:
    def __init__(
        self,
        ssh_service: Optional[SSHService] = None,
        remote_runner_manager: Optional[RemoteRunnerManager] = None,
    ):
        self._ssh = ssh_service
        self.remote_runner_manager = remote_runner_manager or RemoteRunnerManager()

    def initialize(self):
        return 0

    @property
    def ssh_service(self):
        return self._ssh

    @ssh_service.setter
    def ssh_service(self, ssh):
        if self._ssh and self._ssh is not ssh:
            self._ssh.close()
        self._ssh = ssh

    def shutdown(self):
        if self._ssh:
            self._ssh.close()
            self._ssh = None


class RuntimeService(
    RuntimeServerStateMixin,
    RunnerOperationsMixin,
    RuntimeSshConnectionMixin,
    RuntimeTerminalSessionMixin,
):
    def __init__(
        self,
        service_locator: Optional[ServiceLocator] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._service_locator = service_locator or ServiceLocator()
        self._initialized = False
        self._terminal_sessions: dict[str, TerminalSession] = {}
        self._runner_ensure_mutex = threading.Lock()
        self._runner_ensure_inflight: set[str] = set()
        self._connect_in_progress = False
        self._auto_connect_attempted = False
        self._auto_connect_in_progress = False
        self._auto_connect_failed = False
        self._auto_connect_error = ""
        self._auto_connect_notice_key = ""
        self._server_action_state: dict[str, dict[str, Any]] = {}

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._service_locator.initialize()
            self._initialized = True
            self._attempt_startup_auto_connect_in_background()

    def shutdown(self) -> None:
        with self._lock:
            if not self._initialized:
                return
            self._close_all_terminal_sessions()
            self._service_locator.shutdown()
            self._initialized = False

    def list_servers(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None:
                return []
            registry_entry = self._get_server_registry_entry(server["serverId"])
            ssh = self._service_locator.ssh_service if server["connected"] else None
        health = self._build_server_health(
            server_id=server["serverId"],
            ssh_status=ssh_status,
            registry_entry=registry_entry,
            ssh=ssh,
        )
        return [self._compose_server_payload(server=server, registry_entry=registry_entry, health=health)]

    def get_server(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            registry_entry = self._get_server_registry_entry(server_id)
            ssh = self._service_locator.ssh_service if server["connected"] else None
        health = self._build_server_health(
            server_id=server_id,
            ssh_status=ssh_status,
            registry_entry=registry_entry,
            ssh=ssh,
        )
        return self._compose_server_payload(server=server, registry_entry=registry_entry, health=health)

    def get_server_health(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            registry_entry = self._get_server_registry_entry(server_id)
            ssh = self._service_locator.ssh_service if server["connected"] else None
        return self._build_server_health(
            server_id=server_id,
            ssh_status=ssh_status,
            registry_entry=registry_entry,
            ssh=ssh,
        )

    def refresh_server_health(self, server_id: str) -> dict[str, Any]:
        return {"data": self.get_server_health(server_id)}

    def list_remote_listening_ports(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh = self._ensure_ssh_connected()
        command = (
            "if command -v ss >/dev/null 2>&1; then "
            "printf 'COMMAND ss -lntup\\n'; ss -lntup 2>/dev/null || ss -lntu; "
            "elif command -v lsof >/dev/null 2>&1; then "
            "printf 'COMMAND lsof -nP -iTCP -iUDP\\n'; lsof -nP -iTCP -iUDP 2>/dev/null; "
            "elif command -v netstat >/dev/null 2>&1; then "
            "printf 'COMMAND netstat -tulpen\\n'; netstat -tulpen 2>/dev/null || netstat -tuln; "
            "else "
            "printf 'No ss, lsof, or netstat command is available on the remote host.\\n'; exit 127; "
            "fi"
        )
        exit_code, stdout, stderr = ssh.run(command, timeout=15)
        output = (stdout or stderr or "").strip()
        return {
            "data": {
                "exitCode": exit_code,
                "ok": exit_code == 0,
                "output": output,
            }
        }

    def ensure_remote_runner_ready(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            ssh = self._ensure_ssh_connected()
            manager = self._service_locator.remote_runner_manager
            server_record = self._get_server_registry_entry(server_id)
        try:
            with self._runner_ensure_mutex:
                result = self._call_remote_runner(
                    manager.bootstrap,
                    server_id=server_id,
                    server=server,
                    ssh_service=ssh,
                    server_record=server_record,
                )
        except RuntimeServiceError as exc:
            bootstrap_metadata = {}
            cause = exc.__cause__
            if isinstance(cause, RemoteRunnerManagerError) and isinstance(cause.bootstrap_metadata, dict):
                bootstrap_metadata = dict(cause.bootstrap_metadata)
            failure_snapshot = self._build_runner_ensure_failure_snapshot(
                server_id=server_id,
                detail=str(exc),
            )
            with self._lock:
                self._save_server_registry_entry(
                    server_id,
                    {
                        "last_health_snapshot": failure_snapshot,
                        "bootstrap_metadata": bootstrap_metadata or None,
                    },
                )
            raise
        health = result["health"]
        ensured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            self._save_server_registry_entry(
                server_id,
                {
                    "bootstrap_version": result["bootstrap_version"],
                    "runner_mode": result["runner_mode"],
                    "tunnel_port": result["tunnel_port"],
                    "service_port": result["service_port"],
                    "token_ref": result["token_ref"],
                    "last_health_snapshot": health,
                    "bootstrap_metadata": dict(result.get("bootstrap_metadata") or {}),
                    "runner_ensured_at": ensured_at,
                },
            )
        if not bool((health.get("ready") or {}).get("ok")):
            raise RuntimeServiceError(
                str((health.get("ready") or {}).get("message") or "Remote runner control plane is not ready.")
            )
        runner = self._compose_runner_payload(
            registry_entry={
                "bootstrap_version": result["bootstrap_version"],
                "runner_mode": result["runner_mode"],
                "tunnel_port": result["tunnel_port"],
                "service_port": result["service_port"],
                "bootstrap_metadata": dict(result.get("bootstrap_metadata") or {}),
            },
            health=health,
        )
        return {"data": {"serverId": server_id, "runner": runner, "health": health}}

    def accept_server_host_key(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            state = self._server_action_state.setdefault(server_id, {})
            state["host_key_trusted"] = True
            return {"data": {"serverId": server_id, "hostKeyTrusted": True}}

    def rotate_server_token(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            record = self._get_server_registry_entry(server_id)
            if record.get("bootstrap_version"):
                ssh = self._ensure_ssh_connected()
                manager = self._service_locator.remote_runner_manager
            else:
                ssh = None
                manager = None
        rotated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if record.get("bootstrap_version"):
            result = self._call_remote_runner(
                manager.rotate_token,
                server_id=server_id,
                server=server,
                ssh_service=ssh,
                server_record=record,
            )
            token_ref = result["token_ref"]
        else:
            token_ref = store_runner_token(server_id=server_id, token=uuid.uuid4().hex)
        with self._lock:
            self._save_server_registry_entry(
                server_id,
                {
                    "token_ref": token_ref,
                    "token_rotated_at": rotated_at,
                },
            )
        return {"data": {"serverId": server_id, "tokenRotated": True, "rotatedAt": rotated_at}}

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeServiceError("not initialized")
