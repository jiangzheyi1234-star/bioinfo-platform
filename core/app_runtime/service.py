"""Runtime service layer shared by API and desktop shell."""

import threading
import time
import uuid
from typing import Any, Optional

from config import (
    normalize_ssh_config,
    resolve_ssh_config_target,
    store_runner_token,
)
from core.app_runtime import runtime_config
from core.app_runtime.managers.database import DatabaseManager
from core.app_runtime.managers.execution import ExecutionManager
from core.app_runtime.managers.file import FileManager
from core.app_runtime.managers.pipeline import PipelineManager
from core.app_runtime.managers.runner import RunnerManager
from core.app_runtime.managers.tool import ToolManager
from core.app_runtime.managers.workflow import WorkflowManager
from core.remote.ssh_service import SSHService, TerminalSession
from core.remote.ssh_connector import scan_ssh_host_key as scan_remote_ssh_host_key
from core.remote.ssh_connector import trust_ssh_host_key
from core.remote_runner.bootstrap_guard import UPGRADE_ACTIVE_LEASES_REASON, UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.runner_stop_state import is_runner_manually_stopped, raise_if_runner_manually_stopped
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
        self.databases = DatabaseManager(self)
        self.execution = ExecutionManager(self)
        self.files = FileManager(self)
        self.pipelines = PipelineManager(self)
        self.runner = RunnerManager(self)
        self.tools = ToolManager(self)
        self.workflows = WorkflowManager(self)

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

    def list_server_listening_ports(self, server_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            ssh = self._ensure_ssh_connected()
        return self._list_remote_listening_ports_with_ssh(ssh)

    def _list_remote_listening_ports_with_ssh(self, ssh) -> dict[str, Any]:
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
        return self._bootstrap_remote_runner(server_id=server_id, action="ensure")

    def upgrade_remote_runner(self, server_id: str) -> dict[str, Any]:
        return self._bootstrap_remote_runner(server_id=server_id, action="upgrade")

    def _bootstrap_remote_runner(self, *, server_id: str, action: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            if server is None or server["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")
            ssh = self._ensure_ssh_connected()
            manager = self._service_locator.remote_runner_manager
            server_record = self._get_server_registry_entry(server_id)
            if action == "ensure":
                raise_if_runner_manually_stopped(server_id=server_id, record=server_record)
            if action == "upgrade" and not server_record.get("bootstrap_version"):
                raise RuntimeServiceError(
                    "Remote runner is not prepared; start it before upgrade.",
                    status_code=409,
                    detail={
                        "reasonCode": "RUNNER_UPGRADE_NOT_PREPARED",
                        "serverId": server_id,
                        "nextAction": "START_RUNNER_BEFORE_UPGRADE",
                    },
                )
        if action in {"ensure", "start"}:
            existing = self._ready_existing_runner_payload(
                server_id=server_id,
                ssh_service=ssh,
                manager=manager,
                server_record=server_record,
                action=action,
            )
            if existing is not None:
                return existing
        try:
            with self._runner_ensure_mutex:
                result = self._call_remote_runner(
                    manager.bootstrap,
                    server_id=server_id,
                    server=server,
                    ssh_service=ssh,
                    server_record=server_record,
                    bootstrap_action=action,
                )
        except RuntimeServiceError as exc:
            bootstrap_metadata = {}
            cause = exc.__cause__
            if isinstance(cause, RemoteRunnerManagerError) and isinstance(cause.bootstrap_metadata, dict):
                bootstrap_metadata = dict(cause.bootstrap_metadata)
            if _runtime_error_reason_code(exc) in {
                UPGRADE_ACTIVE_LEASES_REASON,
                UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON,
            }:
                blocked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                with self._lock:
                    self._save_server_registry_entry(
                        server_id,
                        {
                            "bootstrap_metadata": bootstrap_metadata or None,
                            "runner_upgrade_blocked_at": blocked_at,
                        },
                    )
                raise
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
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        action_timestamp_key = {
            "ensure": "runner_ensured_at",
            "start": "runner_started_at",
            "upgrade": "runner_upgraded_at",
        }[action]
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
                    action_timestamp_key: completed_at,
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
        return {
            "data": {
                "serverId": server_id,
                "runner": runner,
                "health": health,
                "lifecycleAction": action,
                "completedAt": completed_at,
            }
        }

    def _ready_existing_runner_payload(
        self,
        *,
        server_id: str,
        ssh_service,
        manager,
        server_record: dict[str, Any],
        action: str = "ensure",
    ) -> dict[str, Any] | None:
        if not server_record.get("bootstrap_version"):
            return None
        if is_runner_manually_stopped(server_record):
            return None
        snapshot = server_record.get("last_health_snapshot")
        if isinstance(snapshot, dict) and not bool((snapshot.get("ready") or {}).get("ok")):
            return None
        try:
            health = self._call_remote_runner(
                manager.get_health,
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
            )
        except RuntimeServiceError:
            return None
        if not bool((health.get("ready") or {}).get("ok")):
            return None
        checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            registry_entry = self._save_runner_health_snapshot(server_id=server_id, health=health)
        runner = self._compose_runner_payload(registry_entry=registry_entry, health=health)
        return {
            "data": {
                "serverId": server_id,
                "runner": runner,
                "health": health,
                "lifecycleAction": action,
                "completedAt": checked_at,
            }
        }

    def _resolve_ssh_host_key_target(self, patch: Optional[dict] = None) -> dict[str, Any]:
        current = runtime_config.get_runtime_config()
        merged = normalize_ssh_config(current.get("ssh", {}))
        allowed_keys = {
            "auth_mode",
            "ssh_host_alias",
            "host",
            "port",
            "user",
            "timeout_sec",
            "confirmation",
            "fingerprintSha256",
        }
        if patch:
            unsupported = sorted(set(patch) - allowed_keys)
            if unsupported:
                raise RuntimeServiceError(
                    "SSH host key request contains unsupported fields",
                    status_code=400,
                    detail={
                        "reasonCode": "SSH_HOST_KEY_UNSUPPORTED_FIELD",
                        "field": unsupported[0],
                    },
                )
            for key in (
                "auth_mode",
                "ssh_host_alias",
                "host",
                "port",
                "user",
                "timeout_sec",
            ):
                if key in patch and patch[key] is not None:
                    merged[key] = patch[key]
        merged = normalize_ssh_config(merged)
        auth_mode = str(merged.get("auth_mode", "password_ref") or "password_ref")
        resolved = resolve_ssh_config_target(merged) if auth_mode == "ssh_config" else merged
        host = str(resolved.get("host", "") or "").strip()
        port = int(resolved.get("port", 22) or 22)
        user = str(resolved.get("user", "") or "").strip()
        timeout = int(resolved.get("timeout_sec", 5) or 5)
        identity_status = merged if auth_mode == "ssh_config" else resolved
        server = self._build_primary_server_identity(
            ssh_status={
                "connected": False,
                "host": identity_status.get("host", ""),
                "port": identity_status.get("port", 22),
                "user": identity_status.get("user", ""),
                "ssh_host_alias": identity_status.get("ssh_host_alias", ""),
            }
        )
        if server is None:
            raise RuntimeServiceError("ssh.host or ssh_host_alias required before scanning an SSH host key")
        if not host:
            raise RuntimeServiceError("ssh.host required before scanning an SSH host key")
        if auth_mode != "ssh_config" and not user:
            raise RuntimeServiceError("ssh.user required before scanning an SSH host key")
        return {
            "serverId": str(server["serverId"]),
            "host": host,
            "port": port,
            "user": user,
            "timeout": timeout,
        }

    def scan_ssh_host_key_for_request(self, patch: Optional[dict] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            target = self._resolve_ssh_host_key_target(patch)

        scanned = scan_remote_ssh_host_key(target["host"], target["port"], timeout=target["timeout"])
        if not scanned.ok:
            raise RuntimeServiceError(
                scanned.message,
                status_code=409,
                detail={
                    "reasonCode": scanned.code or "SSH_HOST_KEY_SCAN_FAILED",
                    "message": scanned.message,
                    "serverId": target["serverId"],
                    "host": target["host"],
                    "port": target["port"],
                },
            )
        return {
            "data": {
                "serverId": target["serverId"],
                "host": target["host"],
                "port": target["port"],
                "hostKeyTrusted": False,
                "hostKeyType": scanned.key_type,
                "hostKeyFingerprintSha256": scanned.fingerprint_sha256,
                "knownHostsPath": scanned.known_hosts_path,
            }
        }

    def accept_server_host_key(self, server_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            target = self._resolve_ssh_host_key_target(patch)
            if target["serverId"] != server_id:
                raise RuntimeServiceError(f"Server not found: {server_id}")

        if str(patch.get("confirmation") or "") != "trust-ssh-host-key":
            raise RuntimeServiceError(
                "SSH host key confirmation is required",
                status_code=409,
                detail={
                    "reasonCode": "SSH_HOST_KEY_CONFIRMATION_REQUIRED",
                    "message": "SSH host key confirmation is required",
                    "serverId": server_id,
                    "host": target["host"],
                    "port": target["port"],
                },
            )
        fingerprint = str(patch.get("fingerprintSha256") or "").strip()
        trusted = trust_ssh_host_key(
            target["host"],
            target["port"],
            timeout=target["timeout"],
            expected_fingerprint_sha256=fingerprint,
        )
        if not trusted.ok:
            raise RuntimeServiceError(
                trusted.message,
                status_code=409,
                detail={
                    "reasonCode": trusted.code or "SSH_HOST_KEY_ACCEPT_FAILED",
                    "message": trusted.message,
                    "serverId": server_id,
                    "host": target["host"],
                    "port": target["port"],
                    "hostKeyFingerprintSha256": trusted.fingerprint_sha256,
                },
            )

        with self._lock:
            state = self._server_action_state.setdefault(server_id, {})
            state["host_key_trusted"] = True
            state["host_key_fingerprint_sha256"] = trusted.fingerprint_sha256
            state["known_hosts_path"] = trusted.known_hosts_path
            return {
                "data": {
                    "serverId": server_id,
                    "host": target["host"],
                    "port": target["port"],
                    "hostKeyTrusted": True,
                    "hostKeyType": trusted.key_type,
                    "hostKeyFingerprintSha256": trusted.fingerprint_sha256,
                    "knownHostsPath": trusted.known_hosts_path,
                }
            }

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


def _runtime_error_reason_code(error: RuntimeServiceError) -> str:
    detail = error.detail
    if isinstance(detail, dict):
        return str(detail.get("reasonCode") or "")
    return ""
