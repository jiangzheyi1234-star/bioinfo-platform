import json
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QPushButton

from config import DEFAULT_CONFIG
from ui.page_base import BasePage
from ui.widgets import SshSettingsCard, NcbiSettingsCard
from ui.widgets.styles import PAGE_HEADER_TITLE, BUTTON_SUCCESS


class SettingsPage(BasePage):
    def __init__(self):
        super().__init__("\u2699 \u8bbe\u7f6e")
        if hasattr(self, "label"):
            self.label.hide()

        self.config_dir = os.path.join(os.getenv('APPDATA'), "H2OMeta")
        self.config_path = os.path.join(self.config_dir, "config.json")
        os.makedirs(self.config_dir, exist_ok=True)

        # 页面整体背景：浅天蓝（蓝天感）
        self.setStyleSheet("background-color: #f4f9ff;")

        # UI：调度员式构建
        self.init_ui()

        # 数据：加载并刷新 UI
        self.load_config()

        # 启动即自动执行一次连接测试
        QTimer.singleShot(1000, self.ssh_card.auto_check_on_start)

    # -------------------------
    # UI 构建：调度员
    # -------------------------
    def init_ui(self):
        """调度员：只负责页面整体参数与模块调用顺序，不写任何卡片细节。"""
        self.layout.setContentsMargins(40, 30, 40, 30)
        self.layout.setSpacing(25)

        self._init_header()
        self._init_cards()
        self._init_save_area()

        self.layout.addStretch()

    def _init_header(self):
        header_title = QLabel("系统设置")
        header_title.setStyleSheet(PAGE_HEADER_TITLE)
        self.layout.addWidget(header_title)

    def _init_cards(self):
        # SSH 卡片
        self.ssh_card = SshSettingsCard()
        self.layout.addWidget(self.ssh_card)

        # NCBI 卡片
        self.ncbi_card = NcbiSettingsCard()
        self.ncbi_card.request_save.connect(self._save_ncbi_config)
        self.layout.addWidget(self.ncbi_card)

    def _init_save_area(self):
        self.save_btn = QPushButton("保存全部设置")
        self.save_btn.setStyleSheet(BUTTON_SUCCESS)
        self.save_btn.clicked.connect(self.save_config)
        self.layout.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignRight)

    # -------------------------
    # 对外能力：提供共享 SSHClient
    # -------------------------
    def get_active_client(self):
        return self.ssh_card.get_active_client()

    # -------------------------
    # Config IO：标准化读写 + 组件同步
    # -------------------------
    def _read_config_file(self) -> dict:
        if not os.path.exists(self.config_path):
            return {}
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_config_file(self, data: dict) -> None:
        os.makedirs(self.config_dir, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _default_config_for_ui(self) -> dict:
        return {
            "server_ip": DEFAULT_CONFIG.get("ip", ""),
            "ssh_user": DEFAULT_CONFIG.get("user", ""),
            "ssh_pwd": DEFAULT_CONFIG.get("pwd", ""),
            "ncbi_api_key": DEFAULT_CONFIG.get("ncbi_api_key", ""),
        }

    def _load_config_merged(self) -> dict:
        merged = self._default_config_for_ui()
        merged.update({k: v for k, v in self._read_config_file().items() if v is not None})
        return merged

    def _apply_config_to_components(self, merged: dict) -> None:
        self.ssh_card.set_values(
            server_ip=str(merged.get("server_ip", "") or ""),
            ssh_user=str(merged.get("ssh_user", "") or ""),
            ssh_pwd=str(merged.get("ssh_pwd", "") or ""),
        )
        self.ncbi_card.set_values(ncbi_api_key=str(merged.get("ncbi_api_key", "") or ""))

    def _collect_components_config(self) -> dict:
        data = {}
        data.update(self.ssh_card.get_values())
        data.update(self.ncbi_card.get_values())
        return data

    # -------------------------
    # Public config API
    # -------------------------
    def load_config(self):
        merged = self._load_config_merged()
        self._apply_config_to_components(merged)

    def save_config(self):
        data = self._collect_components_config()
        self._write_config_file(data)

        # 旧行为：保存成功在 SSH 卡片区域提示
        try:
            self.ssh_card.status_label.setText("设置已保存")
        except Exception:
            pass

        # 保存后锁定 NCBI（有 key 就锁定，空就保持可编辑）
        self.ncbi_card.lock_if_needed()

    def _save_ncbi_config(self):
        data = self._read_config_file()
        data["ncbi_api_key"] = self.ncbi_card.get_values().get("ncbi_api_key", "")
        self._write_config_file(data)
        self.ncbi_card.lock_if_needed()
