import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QMessageBox, QScrollArea, QWidget, QVBoxLayout, QFrame

from config import (
    CONFIG_VERSION,
    default_settings_schema,
    get_config,
    get_config_path,
    load_raw_config,
    migrate_legacy_config,
    save_config,
    sync_default_from_schema,
)
from ui.page_base import BasePage
from ui.widgets import SshSettingsCard, NcbiSettingsCard, LinuxSettingsCard
from ui.widgets.styles import PAGE_HEADER_TITLE, COLOR_BG_APP

_SCROLL_BAR_GRAY = """
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 10px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: rgba(100, 116, 139, 0.22);
        border-radius: 5px;
        min-height: 40px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(100, 116, 139, 0.35);
    }
    QScrollBar::handle:vertical:pressed {
        background: rgba(100, 116, 139, 0.48);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
        background: transparent;
        border: none;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: transparent;
    }
"""

def _is_test_mode() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules)


class SettingsPage(BasePage):
    """Settings page backed by the v2 config schema."""

    active_client_changed = pyqtSignal(object)

    def __init__(self):
        super().__init__("系统设置")
        if hasattr(self, "label"):
            self.label.hide()

        self.config_path = get_config_path()
        self.setStyleSheet(f"background-color: {COLOR_BG_APP};")
        self._auto_check_timer = QTimer(self)
        self._auto_check_timer.setSingleShot(True)

        self.init_ui()
        self.load_config()

        self._auto_check_timer.timeout.connect(self.ssh_card.auto_check_on_start)
        if not _is_test_mode():
            self._auto_check_timer.start(1000)

    def init_ui(self) -> None:
        self.layout.setContentsMargins(40, 30, 40, 30)
        self.layout.setSpacing(20)

        self._init_header()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setStyleSheet(f"background-color: {COLOR_BG_APP};")
        scroll_area.verticalScrollBar().setStyleSheet(_SCROLL_BAR_GRAY)

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet(f"background-color: {COLOR_BG_APP};")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 10, 0)
        self.scroll_layout.setSpacing(25)

        self._init_cards()

        scroll_area.setWidget(self.scroll_content)
        self.layout.addWidget(scroll_area)

    def _init_header(self) -> None:
        header_title = QLabel("系统设置")
        header_title.setStyleSheet(PAGE_HEADER_TITLE)
        self.layout.addWidget(header_title)

    def _init_cards(self) -> None:
        self.ssh_card = SshSettingsCard()
        self.ssh_card.request_save.connect(self.save_config)
        self.scroll_layout.addWidget(self.ssh_card)

        self.linux_card = LinuxSettingsCard()
        self.linux_card.request_save.connect(self.save_config)
        self.scroll_layout.addWidget(self.linux_card)

        self.ncbi_card = NcbiSettingsCard()
        self.ncbi_card.request_save.connect(self.save_config)
        self.scroll_layout.addWidget(self.ncbi_card)

        self.scroll_layout.addStretch()

        self.ssh_card.connection_state_changed.connect(self._on_ssh_state_changed)
        self.ssh_card.deploy_requested.connect(self.linux_card.start_deploy)
        self.linux_card.deploy_state_changed.connect(self._on_linux_deploy_state_changed)

    def _on_ssh_state_changed(self, connected: bool) -> None:
        client = self.ssh_card.get_active_client() if connected else None
        self.linux_card.set_active_client(client)
        self.ssh_card.set_deploy_state("checking" if connected else "hidden")
        self.active_client_changed.emit(client)

    def _on_linux_deploy_state_changed(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        self.ssh_card.set_deploy_state(str(data.get("state", "hidden") or "hidden"))

    def get_active_client(self):
        return self.ssh_card.get_active_client()


    def set_global_lock(self, locked: bool, reason: str = "SSH 未连接，设置已锁定") -> None:
        self.ssh_card.set_external_lock(locked, reason)
        if hasattr(self.linux_card, "set_external_lock"):
            self.linux_card.set_external_lock(locked)
        self.ncbi_card.set_external_lock(locked)

    def _is_legacy_raw_config(self, raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        return raw.get("version") != CONFIG_VERSION

    def _backup_legacy_config(self, raw: dict[str, Any]) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = self.config_path.parent / f"config.legacy.{ts}.bak.json"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(backup, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        return backup

    def _apply_schema_to_components(self, schema: dict[str, Any]) -> None:
        ssh = schema.get("ssh", {})
        linux = schema.get("linux", {})
        ncbi = schema.get("ncbi", {})

        port = ssh.get("port", 22)
        try:
            ssh_port = int(port) if port else 22
        except (ValueError, TypeError):
            ssh_port = 22
        self.ssh_card.set_values(
            server_ip=str(ssh.get("host", "") or ""),
            ssh_port=ssh_port,
            ssh_user=str(ssh.get("user", "") or ""),
            ssh_pwd=str(ssh.get("password", "") or ""),
            use_key=bool(ssh.get("use_key", False)),
            key_file=str(ssh.get("key_file", "") or ""),
        )
        self.linux_card.set_values(
            conda_executable=str(linux.get("conda_executable", "") or ""),
        )
        self.ncbi_card.set_values(
            ncbi_api_key=str(ncbi.get("api_key", "") or ""),
            email=str(ncbi.get("email", "") or ""),
        )

    def _collect_schema_from_components(self) -> dict[str, Any]:
        current = get_config()

        ssh_values = self.ssh_card.get_values()
        linux_values = self.linux_card.get_values()
        ncbi_values = self.ncbi_card.get_values()

        port_val = ssh_values.get("ssh_port", 22)
        try:
            ssh_port = int(port_val) if port_val else 22
        except (ValueError, TypeError):
            ssh_port = 22
        return {
            "version": CONFIG_VERSION,
            "ssh": {
                "host": str(ssh_values.get("server_ip", "") or ""),
                "port": ssh_port,
                "user": str(ssh_values.get("ssh_user", "") or ""),
                "password": str(ssh_values.get("ssh_pwd", "") or ""),
                "use_key": bool(ssh_values.get("use_key", False)),
                "key_file": str(ssh_values.get("key_file", "") or ""),
            },
            "linux": {
                "conda_executable": str(linux_values.get("conda_executable", "") or ""),
            },
            "databases": current.get("databases", {"db_root": "", "overrides": {}}),
            "blast": {
                "db_path": str(current.get("blast", {}).get("db_path", "") or ""),
                "bin_path": str(current.get("blast", {}).get("bin_path", "") or ""),
                "remote_work_dir": str(current.get("blast", {}).get("remote_work_dir", "") or ""),
                "remote_script": str(
                    current.get("blast", default_settings_schema()["blast"]).get("remote_script", "") or ""
                ),
            },
            "ncbi": {
                "api_key": str(ncbi_values.get("ncbi_api_key", "") or ""),
                "email": str(ncbi_values.get("email", "") or ""),
            },
            "runtime": current.get("runtime", default_settings_schema()["runtime"]),
        }

    def load_config(self) -> None:
        try:
            raw = load_raw_config()
        except Exception:
            raw = {}

        if self._is_legacy_raw_config(raw) and raw:
            result = QMessageBox.question(
                self,
                "检测到旧版配置",
                "发现旧版设置文件，是否立即迁移到当前配置结构？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if result == QMessageBox.StandardButton.Yes:
                backup = self._backup_legacy_config(raw)
                migrated = migrate_legacy_config(raw)
                save_config(migrated)
                sync_default_from_schema(migrated)
                self._apply_schema_to_components(migrated)
                QMessageBox.information(self, "迁移完成", f"旧版配置备份已保存到：\n{backup}")
                return

            defaults = default_settings_schema()
            sync_default_from_schema(defaults)
            self._apply_schema_to_components(defaults)
            QMessageBox.information(self, "已加载默认值", "你已跳过旧配置迁移，系统已加载默认设置。")
            return

        schema = get_config()
        sync_default_from_schema(schema)
        self._apply_schema_to_components(schema)

    def save_config(self) -> None:
        schema = self._collect_schema_from_components()
        save_config(schema)
        sync_default_from_schema(schema)

        window = self.window()
        locator = getattr(window, "service_locator", None)
        if locator is not None and hasattr(locator, "conda_executable"):
            locator.conda_executable = schema["linux"].get("conda_executable", "")

        try:
            self.ssh_card.status_label.setText("设置已保存")
        except Exception:
            pass

        if hasattr(self.ncbi_card, "lock_if_needed"):
            self.ncbi_card.lock_if_needed()

    def closeEvent(self, event) -> None:
        if self._auto_check_timer.isActive():
            self._auto_check_timer.stop()
        super().closeEvent(event)
