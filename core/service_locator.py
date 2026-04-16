"""Service locator for runtime services."""

from __future__ import annotations

import logging
from typing import Optional

from config import get_config
from core.remote.ssh_service import SSHService

logger = logging.getLogger(__name__)


class ServiceLocator:
    """Connect core services into a runnable application graph."""

    def __init__(self, ssh_service: Optional[SSHService] = None) -> None:
        self._ssh: Optional[SSHService] = ssh_service
        self._conda_executable: str = ""

    def initialize(self) -> int:
        self._hydrate_conda_executable_from_config()
        logger.info("ServiceLocator initialized")
        return 0

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
        if previous is not None and previous is not ssh:
            try:
                previous.close()
            except Exception:
                logger.debug("Failed to close previous SSH service", exc_info=True)
        self._ssh = ssh
        logger.info("SSH service updated")

    @property
    def conda_executable(self) -> str:
        return self._conda_executable

    @conda_executable.setter
    def conda_executable(self, path: str) -> None:
        self._conda_executable = path or ""
        logger.info("conda_executable updated: %s", self._conda_executable or "(empty)")

    def shutdown(self) -> None:
        if self._ssh is not None and hasattr(self._ssh, "close"):
            try:
                self._ssh.close()
            except Exception:
                logger.debug("SSH service close failed during shutdown", exc_info=True)
        self._ssh = None
        logger.info("ServiceLocator closed")
