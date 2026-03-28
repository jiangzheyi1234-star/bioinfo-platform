"""SSH binding/orchestration for MainWindow."""

from __future__ import annotations

import logging
import shlex
import time
from typing import Any, Callable, Optional

import paramiko
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from config import get_config, save_config
from core.environment import env_detector
from core.environment.env_detector import CondaStatus
from core.environment.h2o_env_paths import is_managed_conda_executable
from core.environment.server_preflight import run_preflight
from core.remote.ssh_service import SSHService
from core.remote.server_capabilities import ServerCapabilities

logger = logging.getLogger(__name__)


class CondaBindWorker(QObject):
    """Resolve and validate remote conda executable without blocking the UI thread."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str, object)

    def __init__(self, *, ssh: SSHService, client: Any, ssh_cfg: dict, token: int) -> None:
        super().__init__()
        self._ssh = ssh
        self._client = client
        self._ssh_cfg = dict(ssh_cfg or {})
        self._token = int(token)
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    @staticmethod
    def _resolve_executable_path(ssh: SSHService, executable: str) -> str:
        candidate = str(executable or "").strip()
        if not candidate:
            return ""
        if candidate.startswith("~/") or candidate.startswith("$HOME/"):
            try:
                rc, out, _ = ssh.run('printf "%s" "$HOME"', timeout=10)
                home = out.strip() if rc == 0 else ""
            except Exception:
                home = ""
            if home:
                if candidate.startswith("~/"):
                    return f"{home.rstrip('/')}/{candidate[2:]}"
                return f"{home.rstrip('/')}/{candidate[len('$HOME/'):]}"
        return candidate

    @staticmethod
    def _validate_cached_executable(ssh: SSHService, executable: str) -> bool:
        candidate = str(executable or "").strip()
        if not candidate or not is_managed_conda_executable(candidate):
            return False
        cmd = f"{shlex.quote(candidate)} --version"
        try:
            rc, _, _ = ssh.run(cmd, timeout=15)
            return rc == 0
        except Exception:
            return False

    def _emit_finished(
        self,
        *,
        identity: str,
        fingerprint: str,
        user: str,
        port: int,
        host: str,
        resolved_executable: str,
        profile_action: str,
        status: str,
        source: str,
    ) -> None:
        if self._cancelled:
            return
        self.finished.emit(
            {
                "token": self._token,
                "identity": identity,
                "fingerprint": fingerprint,
                "user": user,
                "port": int(port),
                "host": host,
                "resolved_executable": str(resolved_executable or ""),
                "profile_action": str(profile_action or "none"),
                "status": str(status or "error"),
                "source": str(source or "detect"),
            }
        )

    @pyqtSlot()
    def run(self) -> None:
        identity, fingerprint, user, port = MainWindowSSHController._build_server_identity(self._client, self._ssh_cfg)
        host = str(self._ssh_cfg.get("ip", "") or "")
        had_cached_profile = False
        if identity:
            profile = MainWindowSSHController._read_conda_profile(identity)
            cached_executable = str((profile or {}).get("conda_executable", "") or "").strip()
            had_cached_profile = bool(cached_executable)
            cached_resolved = self._resolve_executable_path(self._ssh, cached_executable)
            if (
                cached_resolved
                and is_managed_conda_executable(cached_resolved)
                and self._validate_cached_executable(self._ssh, cached_resolved)
            ):
                self._emit_finished(
                    identity=identity,
                    fingerprint=fingerprint,
                    user=user,
                    port=port,
                    host=host,
                    resolved_executable=cached_resolved,
                    profile_action="save",
                    status="ok",
                    source="cache_hit",
                )
                return

        detect_source = "cache_invalid" if had_cached_profile else "detect"
        try:
            result = env_detector.detect(self._ssh.run)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("conda detect failed while binding SSH client")
            self.error.emit(
                str(exc),
                {
                    "token": self._token,
                    "identity": identity,
                    "fingerprint": fingerprint,
                    "user": user,
                    "port": int(port),
                    "host": host,
                    "profile_action": "remove" if identity else "none",
                    "status": "error",
                    "source": detect_source,
                },
            )
            return

        if (
            not self._cancelled
            and result is not None
            and result.status == CondaStatus.OK
            and is_managed_conda_executable(result.executable or "")
        ):
            resolved = self._resolve_executable_path(self._ssh, result.executable or "")
            self._emit_finished(
                identity=identity,
                fingerprint=fingerprint,
                user=user,
                port=port,
                host=host,
                resolved_executable=resolved,
                profile_action="save" if identity else "none",
                status="ok",
                source=detect_source,
            )
            return

        self._emit_finished(
            identity=identity,
            fingerprint=fingerprint,
            user=user,
            port=port,
            host=host,
            resolved_executable="",
            profile_action="remove" if identity else "none",
            status="not_found",
            source=detect_source,
        )


class CapabilityBindWorker(QObject):
    """Resolve remote server capabilities without blocking the UI thread."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, *, ssh: SSHService) -> None:
        super().__init__()
        self._ssh = ssh
        self._cancelled = False

    @pyqtSlot()
    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        if self._cancelled:
            return
        try:
            caps = run_preflight(self._ssh.run)
            if self._cancelled:
                return
            self.finished.emit(caps)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("server capability preflight failed while binding SSH client")
            self.error.emit(str(exc))


class MainWindowSSHController:
    """Manage active SSH client binding and SSHService wrapper lifecycle."""

    def __init__(
        self,
        *,
        locator,
        settings_page,
        status_bar,
        on_ssh_status_changed: Callable[[bool], None],
        on_ssh_changed_for_disk: Callable[[bool], None],
        notify_pages_context_changed: Callable[[], None],
    ) -> None:
        self._locator = locator
        self._settings_page = settings_page
        self._status_bar = status_bar
        self._on_ssh_status_changed = on_ssh_status_changed
        self._on_ssh_changed_for_disk = on_ssh_changed_for_disk
        self._notify_pages_context_changed = notify_pages_context_changed
        self._ssh_service_wrapper: Optional[SSHService] = None
        self._conda_bind_token = 0
        self._capability_bind_token = 0

    @property
    def ssh_service_wrapper(self) -> Optional[SSHService]:
        return self._ssh_service_wrapper

    def apply_active_client(self, client: Any) -> Optional[SSHService]:
        # Disconnect old wrapper signals to avoid dangling references.
        self._disconnect_wrapper_signals()
        self._conda_bind_token += 1
        self._capability_bind_token += 1
        self._cleanup_conda_bind_resources()
        self._cleanup_capability_bind_resources()

        if client is None:
            self._ssh_service_wrapper = None
            self._locator.ssh_service = None  # type: ignore[assignment]
            self._locator.conda_executable = ""
            self._locator.server_capabilities = None
            self._locator.server_capability_error = ""
            self._status_bar.update_ssh_status(False)
            self._on_ssh_changed_for_disk(False)
            self._notify_pages_context_changed()
            return None

        ssh_cfg = self._settings_page.ssh_card.last_stable_config
        connect_fn = self._build_connect_fn(ssh_cfg) if ssh_cfg else None
        self._ssh_service_wrapper = SSHService(
            initial_client=client,
            connect_fn=connect_fn,
        )
        self._ssh_service_wrapper.connection_status_changed.connect(self._on_ssh_status_changed)
        self._ssh_service_wrapper.connection_status_changed.connect(self._on_ssh_changed_for_disk)
        self._locator.ssh_service = self._ssh_service_wrapper
        self._locator.server_capabilities = None
        self._locator.server_capability_error = ""
        self._bind_conda_executable(client=client, ssh_cfg=ssh_cfg or {})
        self._bind_server_capabilities()
        self._status_bar.update_ssh_status(self._ssh_service_wrapper.is_connected)
        self._on_ssh_changed_for_disk(self._ssh_service_wrapper.is_connected)
        self._notify_pages_context_changed()
        return self._ssh_service_wrapper

    def shutdown(self) -> None:
        self._disconnect_wrapper_signals()
        self._conda_bind_token += 1
        self._capability_bind_token += 1
        self._cleanup_conda_bind_resources()
        self._cleanup_capability_bind_resources()

    def _disconnect_wrapper_signals(self) -> None:
        if self._ssh_service_wrapper is None:
            return
        try:
            self._ssh_service_wrapper.connection_status_changed.disconnect(self._on_ssh_status_changed)
        except (TypeError, RuntimeError):
            pass
        try:
            self._ssh_service_wrapper.connection_status_changed.disconnect(self._on_ssh_changed_for_disk)
        except (TypeError, RuntimeError):
            pass

    @staticmethod
    def _build_connect_fn(cfg: dict) -> Callable[[], paramiko.SSHClient]:
        def _connect() -> paramiko.SSHClient:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            kwargs: dict = {
                "hostname": cfg.get("ip", ""),
                "port": cfg.get("port", 22),
                "username": cfg.get("user", ""),
                "timeout": 5,
                "allow_agent": False,
                "look_for_keys": False,
            }
            if cfg.get("use_key") and cfg.get("key_file"):
                kwargs["key_filename"] = cfg["key_file"]
            else:
                kwargs["password"] = cfg.get("pwd", "")
            c.connect(**kwargs)
            c.get_transport().set_keepalive(30)
            return c

        return _connect

    def _bind_conda_executable(self, *, client: Any, ssh_cfg: dict) -> None:
        """Bind conda executable for current SSH target using server identity cache."""
        ssh = self._ssh_service_wrapper
        if ssh is None or not getattr(ssh, "is_connected", False):
            self._locator.conda_executable = ""
            return
        self._locator.conda_executable = ""
        self._start_conda_bind_job(client=client, ssh_cfg=ssh_cfg, token=self._conda_bind_token)

    def _bind_server_capabilities(self) -> None:
        ssh = self._ssh_service_wrapper
        if ssh is None or not getattr(ssh, "is_connected", False):
            self._locator.server_capabilities = None
            self._locator.server_capability_error = ""
            return
        self._locator.server_capabilities = None
        self._locator.server_capability_error = ""
        self._start_capability_bind_job(token=self._capability_bind_token)

    @staticmethod
    def _build_server_identity(client: Any, ssh_cfg: dict) -> tuple[str, str, str, int]:
        """Build stable cache key by fingerprint + user + port."""
        try:
            transport = client.get_transport()
            host_key = transport.get_remote_server_key() if transport is not None else None
            raw_fingerprint = host_key.get_fingerprint() if host_key is not None else None
            fingerprint = raw_fingerprint.hex() if raw_fingerprint else ""
        except Exception:
            fingerprint = ""

        user = str(ssh_cfg.get("user", "") or "").strip()
        port_raw = ssh_cfg.get("port", 22)
        try:
            port = int(port_raw)
        except (TypeError, ValueError):
            port = 22

        if not fingerprint or not user:
            return "", fingerprint, user, port

        identity = f"fp:{fingerprint}|u:{user}|p:{port}"
        return identity, fingerprint, user, port

    @staticmethod
    def _read_conda_profile(identity: str) -> Optional[dict]:
        if not identity:
            return None
        try:
            cfg = get_config()
        except Exception:
            logger.exception("failed to read config for conda profile")
            return None
        runtime = cfg.get("runtime", {}) if isinstance(cfg, dict) else {}
        profiles = runtime.get("conda_profiles", {}) if isinstance(runtime, dict) else {}
        if not isinstance(profiles, dict):
            return None
        profile = profiles.get(identity)
        if isinstance(profile, dict):
            return profile
        return None

    @staticmethod
    def _save_conda_profile(
        *,
        identity: str,
        conda_executable: str,
        fingerprint: str,
        user: str,
        port: int,
        host: str,
    ) -> None:
        if not identity:
            return
        try:
            cfg = get_config()
        except Exception:
            logger.exception("failed to read config before writing conda profile")
            return
        if not isinstance(cfg, dict):
            return

        runtime = cfg.get("runtime", {})
        if not isinstance(runtime, dict):
            runtime = {}
            cfg["runtime"] = runtime

        profiles = runtime.get("conda_profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
            runtime["conda_profiles"] = profiles

        profiles[identity] = {
            "conda_executable": str(conda_executable or ""),
            "fingerprint": str(fingerprint or ""),
            "user": str(user or ""),
            "port": int(port),
            "host": str(host or ""),
            "updated_at": float(time.time()),
        }
        runtime["conda_profiles"] = profiles
        try:
            save_config(cfg)
        except Exception:
            logger.exception("failed to persist conda profile")

    @staticmethod
    def _remove_conda_profile(identity: str) -> None:
        if not identity:
            return
        try:
            cfg = get_config()
        except Exception:
            logger.exception("failed to read config before removing conda profile")
            return
        if not isinstance(cfg, dict):
            return

        runtime = cfg.get("runtime", {})
        if not isinstance(runtime, dict):
            return

        profiles = runtime.get("conda_profiles", {})
        if not isinstance(profiles, dict):
            return

        if identity not in profiles:
            return

        profiles.pop(identity, None)
        runtime["conda_profiles"] = profiles
        cfg["runtime"] = runtime
        try:
            save_config(cfg)
        except Exception:
            logger.exception("failed to persist conda profile removal")

    def _start_conda_bind_job(self, *, client: Any, ssh_cfg: dict, token: int) -> None:
        ssh = self._ssh_service_wrapper
        if ssh is None:
            return
        self._conda_bind_thread = QThread()
        self._conda_bind_worker = CondaBindWorker(
            ssh=ssh,
            client=client,
            ssh_cfg=ssh_cfg,
            token=token,
        )
        self._conda_bind_worker.moveToThread(self._conda_bind_thread)
        self._conda_bind_thread.started.connect(self._conda_bind_worker.run)
        self._conda_bind_worker.finished.connect(self._on_conda_bind_finished)
        self._conda_bind_worker.error.connect(self._on_conda_bind_error)
        self._conda_bind_worker.finished.connect(self._cleanup_conda_bind_resources)
        self._conda_bind_worker.error.connect(self._cleanup_conda_bind_resources)
        self._conda_bind_thread.start()

    def _cleanup_conda_bind_resources(self) -> None:
        worker = getattr(self, "_conda_bind_worker", None)
        if worker is not None:
            cancel = getattr(worker, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except RuntimeError:
                    logger.debug("Conda bind worker already deleted", exc_info=True)
        thread = getattr(self, "_conda_bind_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3000)
        if thread is not None:
            thread.deleteLater()
            delattr(self, "_conda_bind_thread")
        if worker is not None:
            worker.deleteLater()
            delattr(self, "_conda_bind_worker")

    def _start_capability_bind_job(self, *, token: int) -> None:
        ssh = self._ssh_service_wrapper
        if ssh is None:
            return
        self._capability_bind_thread = QThread()
        self._capability_bind_worker = CapabilityBindWorker(ssh=ssh)
        self._capability_bind_worker.moveToThread(self._capability_bind_thread)
        self._capability_bind_thread.started.connect(self._capability_bind_worker.run)
        self._capability_bind_worker.finished.connect(
            lambda caps, _token=token: self._on_capability_bind_finished(_token, caps)
        )
        self._capability_bind_worker.error.connect(
            lambda message, _token=token: self._on_capability_bind_error(_token, message)
        )
        self._capability_bind_worker.finished.connect(self._cleanup_capability_bind_resources)
        self._capability_bind_worker.error.connect(self._cleanup_capability_bind_resources)
        self._capability_bind_thread.start()

    def _cleanup_capability_bind_resources(self) -> None:
        worker = getattr(self, "_capability_bind_worker", None)
        if worker is not None:
            cancel = getattr(worker, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except RuntimeError:
                    logger.debug("Capability bind worker already deleted", exc_info=True)
        thread = getattr(self, "_capability_bind_thread", None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3000)
        if thread is not None:
            thread.deleteLater()
            delattr(self, "_capability_bind_thread")
        if worker is not None:
            worker.deleteLater()
            delattr(self, "_capability_bind_worker")

    def _on_conda_bind_finished(self, result: object) -> None:
        payload = result if isinstance(result, dict) else {}
        if int(payload.get("token", -1)) != self._conda_bind_token:
            return
        ssh = self._ssh_service_wrapper
        if ssh is None or not getattr(ssh, "is_connected", False):
            return

        identity = str(payload.get("identity", "") or "").strip()
        executable = str(payload.get("resolved_executable", "") or "").strip()
        profile_action = str(payload.get("profile_action", "") or "none").strip()
        status = str(payload.get("status", "") or "error").strip()

        if status == "ok" and executable and is_managed_conda_executable(executable):
            self._locator.conda_executable = executable
            if profile_action == "save" and identity:
                self._save_conda_profile(
                    identity=identity,
                    conda_executable=executable,
                    fingerprint=str(payload.get("fingerprint", "") or ""),
                    user=str(payload.get("user", "") or ""),
                    port=int(payload.get("port", 22) or 22),
                    host=str(payload.get("host", "") or ""),
                )
            return

        self._locator.conda_executable = ""
        if profile_action == "remove" and identity:
            self._remove_conda_profile(identity)

    def _on_conda_bind_error(self, message: str, context: object) -> None:
        payload = context if isinstance(context, dict) else {}
        if int(payload.get("token", -1)) != self._conda_bind_token:
            return
        logger.debug("conda bind failed: %s", message)
        ssh = self._ssh_service_wrapper
        if ssh is None or not getattr(ssh, "is_connected", False):
            return
        self._locator.conda_executable = ""
        identity = str(payload.get("identity", "") or "").strip()
        if str(payload.get("profile_action", "") or "") == "remove" and identity:
            self._remove_conda_profile(identity)

    def _on_capability_bind_finished(self, token: int, caps: object) -> None:
        if int(token) != self._capability_bind_token:
            return
        ssh = self._ssh_service_wrapper
        if ssh is None or not getattr(ssh, "is_connected", False):
            return
        if not isinstance(caps, ServerCapabilities):
            self._locator.server_capabilities = None
            self._locator.server_capability_error = "服务器预检返回了无效结果"
        else:
            self._locator.server_capabilities = caps
            self._locator.server_capability_error = ""
        self._notify_pages_context_changed()

    def _on_capability_bind_error(self, token: int, message: str) -> None:
        if int(token) != self._capability_bind_token:
            return
        ssh = self._ssh_service_wrapper
        if ssh is None or not getattr(ssh, "is_connected", False):
            return
        self._locator.server_capabilities = None
        self._locator.server_capability_error = str(message or "服务器预检失败")
        self._notify_pages_context_changed()
