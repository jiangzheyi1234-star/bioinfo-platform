"""Service locator for runtime services."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from core.runtime_primitives import RuntimeObject, signal

from config import get_config
from core.data.data_registry import DataRegistry
from core.plugins.plugin_registry import PluginRegistry
from core.remote.ssh_service import SSHService
from core.remote.server_capabilities import ServerCapabilities
from core.utils import get_app_root

logger = logging.getLogger(__name__)

_DEFAULT_PLUGINS_DIR = get_app_root() / "plugins"


class ServiceLocator(QObject):
    """Connect core services into a runnable application graph."""

    ssh_changed = signal(bool)

    def __init__(
        self,
        ssh_service: Optional[SSHService] = None,
        plugins_dir: Optional[Path] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)

        self._ssh: Optional[SSHService] = ssh_service
        self._plugins_dir = plugins_dir or _DEFAULT_PLUGINS_DIR
        self._plugin_registry = PluginRegistry(self._plugins_dir)
        self._data_registry: Optional[DataRegistry] = None
        self._conda_executable: str = ""
        self._server_capabilities: Optional[ServerCapabilities] = None
        self._server_capability_error: str = ""

    def initialize(self) -> int:
        self._hydrate_conda_executable_from_config()
        count = self._plugin_registry.scan()
        logger.info("ServiceLocator initialized: scanned %d plugins", count)
        return count

    def _hydrate_conda_executable_from_config(self) -> None:
        if self._conda_executable:
            return
        try:
            cfg = get_config()
            linux = cfg.get("linux", {}) if isinstance(cfg, dict) else {}
            conda_path = str(linux.get("conda_executable", "") or "").strip()
        except Exception:
            logger.exception("Failed to read conda path from config")
            return

        if not conda_path:
            return

        self.conda_executable = conda_path

    @property
    def ssh_service(self) -> Optional[SSHService]:
        return self._ssh

    @ssh_service.setter
    def ssh_service(self, ssh: Optional[SSHService]) -> None:
        previous = self._ssh
        if previous is ssh:
            return
        if previous is not None:
            try:
                previous.connection_status_changed.disconnect(self.ssh_changed.emit)
            except (TypeError, RuntimeError, AttributeError):
                pass
        self._ssh = ssh
        if ssh is not None:
            try:
                ssh.connection_status_changed.connect(self.ssh_changed.emit)
            except (TypeError, RuntimeError, AttributeError):
                logger.debug(
                    "Failed to wire SSH connection_status_changed", exc_info=True
                )
        self.ssh_changed.emit(
            bool(ssh is not None and getattr(ssh, "is_connected", False))
        )
        if previous is not None and previous is not ssh:
            try:
                previous.close()
            except Exception:
                logger.debug("Failed to close previous SSH service", exc_info=True)
        logger.info("SSH service updated")

    @property
    def plugin_registry(self) -> PluginRegistry:
        return self._plugin_registry

    @property
    def data_registry(self) -> Optional[DataRegistry]:
        return self._data_registry

    def set_data_registry(self, registry: Optional[DataRegistry]) -> None:
        self._data_registry = registry

    @property
    def conda_executable(self) -> str:
        return self._conda_executable

    @conda_executable.setter
    def conda_executable(self, path: str) -> None:
        self._conda_executable = path or ""
        logger.info(
            "conda_executable updated: %s",
            self._conda_executable or "(empty)",
        )

    @property
    def server_capabilities(self) -> Optional[ServerCapabilities]:
        return self._server_capabilities

    @server_capabilities.setter
    def server_capabilities(self, caps: Optional[ServerCapabilities]) -> None:
        self._server_capabilities = caps

    @property
    def server_capability_error(self) -> str:
        return self._server_capability_error

    @server_capability_error.setter
    def server_capability_error(self, message: str) -> None:
        self._server_capability_error = str(message or "")

    def shutdown(self) -> None:
        if self._ssh is not None and hasattr(self._ssh, "close"):
            try:
                self._ssh.close()
            except Exception:
                logger.debug("SSH service close failed during shutdown", exc_info=True)
        self._ssh = None
        self._data_registry = None
        logger.info("ServiceLocator closed")


class _NullSSH:
    """Empty SSH implementation."""

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        raise RuntimeError("SSH 未连接")

    def upload(self, local_path: str, remote_path: str) -> None:
        raise RuntimeError("SSH 未连接")
