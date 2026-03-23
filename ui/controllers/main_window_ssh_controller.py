"""SSH binding/orchestration for MainWindow."""

from __future__ import annotations

from typing import Any, Callable, Optional

import paramiko

from core.remote.ssh_service import SSHService


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
        if self._ssh_service_wrapper is not None:
            try:
                self._ssh_service_wrapper.connection_status_changed.disconnect(self._on_ssh_status_changed)
            except (TypeError, RuntimeError):
                pass
            try:
                self._ssh_service_wrapper.connection_status_changed.disconnect(self._on_ssh_changed_for_disk)
            except (TypeError, RuntimeError):
                pass

        if client is None:
            self._ssh_service_wrapper = None
            self._locator.ssh_service = None  # type: ignore[assignment]
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
        self._status_bar.update_ssh_status(self._ssh_service_wrapper.is_connected)
        self._on_ssh_changed_for_disk(self._ssh_service_wrapper.is_connected)
        self._notify_pages_context_changed()
        return self._ssh_service_wrapper

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

