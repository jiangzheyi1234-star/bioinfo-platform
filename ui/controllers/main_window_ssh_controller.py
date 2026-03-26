"""SSH binding/orchestration for MainWindow."""

from __future__ import annotations

import logging
import shlex
import time
from typing import Any, Callable, Optional

import paramiko

from config import get_config, save_config
from core.environment import env_detector
from core.environment.env_detector import CondaStatus
from core.environment.h2o_env_paths import is_managed_conda_executable
from core.remote.ssh_service import SSHService

logger = logging.getLogger(__name__)


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

    @property
    def ssh_service_wrapper(self) -> Optional[SSHService]:
        return self._ssh_service_wrapper

    def apply_active_client(self, client: Any) -> Optional[SSHService]:
        # Disconnect old wrapper signals to avoid dangling references.
        self._disconnect_wrapper_signals()

        if client is None:
            self._ssh_service_wrapper = None
            self._locator.ssh_service = None  # type: ignore[assignment]
            self._locator.conda_executable = ""
            self._status_bar.update_ssh_status(False)
            self._on_ssh_changed_for_disk(False)
            self._notify_pages_context_changed()
            return None

        ssh_cfg = self._settings_page.ssh_card.last_stable_config
        connect_fn = self._build_connect_fn(ssh_cfg) if ssh_cfg else None
        self._ssh_service_wrapper = SSHService(
            lambda c=client: c,
            connect_fn=connect_fn,
        )
        self._ssh_service_wrapper.connection_status_changed.connect(self._on_ssh_status_changed)
        self._ssh_service_wrapper.connection_status_changed.connect(self._on_ssh_changed_for_disk)
        self._locator.ssh_service = self._ssh_service_wrapper
        self._bind_conda_executable(client=client, ssh_cfg=ssh_cfg or {})
        self._status_bar.update_ssh_status(self._ssh_service_wrapper.is_connected)
        self._on_ssh_changed_for_disk(self._ssh_service_wrapper.is_connected)
        self._notify_pages_context_changed()
        return self._ssh_service_wrapper

    def shutdown(self) -> None:
        self._disconnect_wrapper_signals()

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

        identity, fingerprint, user, port = self._build_server_identity(client, ssh_cfg)
        if identity:
            profile = self._read_conda_profile(identity)
            cached_executable = str((profile or {}).get("conda_executable", "") or "").strip()
            cached_resolved = self._resolve_executable_path(ssh, cached_executable)
            if (
                cached_resolved
                and is_managed_conda_executable(cached_resolved)
                and self._validate_cached_executable(ssh, cached_resolved)
            ):
                self._locator.conda_executable = cached_resolved
                self._save_conda_profile(
                    identity=identity,
                    conda_executable=cached_resolved,
                    fingerprint=fingerprint,
                    user=user,
                    port=port,
                    host=str(ssh_cfg.get("ip", "") or ""),
                )
                return

        try:
            result = env_detector.detect(ssh.run)
        except Exception:
            logger.exception("conda detect failed while binding SSH client")
            result = None

        if (
            result is not None
            and result.status == CondaStatus.OK
            and is_managed_conda_executable(result.executable or "")
        ):
            executable = self._resolve_executable_path(ssh, result.executable or "")
            self._locator.conda_executable = executable
            if identity:
                self._save_conda_profile(
                    identity=identity,
                    conda_executable=executable,
                    fingerprint=fingerprint,
                    user=user,
                    port=port,
                    host=str(ssh_cfg.get("ip", "") or ""),
                )
            return

        self._locator.conda_executable = ""
        if identity:
            self._remove_conda_profile(identity)

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
        if not candidate:
            return False
        if not is_managed_conda_executable(candidate):
            return False
        cmd = f"{shlex.quote(candidate)} --version"
        try:
            rc, _, _ = ssh.run(cmd, timeout=15)
            return rc == 0
        except Exception:
            return False
