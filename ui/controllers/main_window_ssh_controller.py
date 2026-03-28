"""SSH binding/orchestration for MainWindow."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import paramiko
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from core.environment.server_preflight import run_preflight
from core.remote.server_capabilities import ServerCapabilities
from core.remote.ssh_service import SSHService

logger = logging.getLogger(__name__)


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
        self._capability_bind_token = 0

    @property
    def ssh_service_wrapper(self) -> Optional[SSHService]:
        return self._ssh_service_wrapper

    def apply_active_client(self, client: Any) -> Optional[SSHService]:
        self._disconnect_wrapper_signals()
        self._capability_bind_token += 1
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
        self._locator.conda_executable = ""
        self._locator.server_capabilities = None
        self._locator.server_capability_error = ""
        self._bind_server_capabilities()
        self._status_bar.update_ssh_status(self._ssh_service_wrapper.is_connected)
        self._on_ssh_changed_for_disk(self._ssh_service_wrapper.is_connected)
        self._notify_pages_context_changed()
        return self._ssh_service_wrapper

    def shutdown(self) -> None:
        self._disconnect_wrapper_signals()
        self._capability_bind_token += 1
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

    def _bind_server_capabilities(self) -> None:
        ssh = self._ssh_service_wrapper
        if ssh is None or not getattr(ssh, "is_connected", False):
            self._locator.server_capabilities = None
            self._locator.server_capability_error = ""
            return
        self._locator.server_capabilities = None
        self._locator.server_capability_error = ""
        self._start_capability_bind_job(token=self._capability_bind_token)

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
