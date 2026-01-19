import json
import os
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QLabel, QPushButton, QScrollArea, QWidget, QVBoxLayout, QFrame

from config import DEFAULT_CONFIG
from ui.page_base import BasePage
from ui.widgets import SshSettingsCard, NcbiSettingsCard, BlastSettingsCard, LinuxSettingsCard
from ui.widgets.styles import PAGE_HEADER_TITLE, BUTTON_SUCCESS, COLOR_BG_APP, SCROLL_BAR_ELEGANT

class SettingsPage(BasePage):
    def __init__(self):
        super().__init__("\u2699 \u8bbe\u7f6e")
        if hasattr(self, "label"):
            self.label.hide()

        self.config_dir = os.path.join(os.getenv('APPDATA'), "H2OMeta")
        self.config_path = os.path.join(self.config_dir, "config.json")
        os.makedirs(self.config_dir, exist_ok=True)

        self.setStyleSheet(f"background-color: {COLOR_BG_APP};")

        self.init_ui()
        self.load_config()

        # 启动即自动执行一次连接测试
        QTimer.singleShot(1000, self.ssh_card.auto_check_on_start)

    # -------------------------
    # UI 构建：调度员
    # -------------------------
    def init_ui(self):
        """重构调度员：引入滚动机制"""
        self.layout.setContentsMargins(40, 30, 40, 30)
        self.layout.setSpacing(20)

        # 1. 初始化页面标题 (保持在滚动区域上方，固定不动)
        self._init_header()

        # 2. 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True) # 关键：让内部组件随滚动区域缩放
        scroll_area.setFrameShape(QFrame.Shape.NoFrame) # 去掉滚动区域边框
        scroll_area.setStyleSheet("background-color: transparent;") # 保持透明背景

        # 应用优雅的滚动条样式
        scroll_area.verticalScrollBar().setStyleSheet(SCROLL_BAR_ELEGANT)

        # 3. 创建容器 Widget
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background-color: transparent;")
        
        # 4. 创建内部滚动布局
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 10, 0) # 留出一点右边距给滚动条
        self.scroll_layout.setSpacing(25) # 卡片间距

        # 5. 将卡片加入滚动布局
        self._init_cards()

        # 6. 完成装配
        scroll_area.setWidget(self.scroll_content)
        self.layout.addWidget(scroll_area) # 将滚动区域加入页面主布局

        self._init_save_area()

    def _init_header(self):
        header_title = QLabel("系统设置")
        header_title.setStyleSheet(PAGE_HEADER_TITLE)
        self.layout.addWidget(header_title)

    def _init_cards(self):
        # SSH 卡片
        self.ssh_card = SshSettingsCard()
        self.scroll_layout.addWidget(self.ssh_card) # 关键：使用 scroll_layout

        # Linux 设置卡片 (你新创建的)
        self.linux_card = LinuxSettingsCard()
        self.linux_card.request_save.connect(self.save_config)  # 连接保存信号
        self.scroll_layout.addWidget(self.linux_card)

        # BLAST 数据库设置卡片
        self.blast_card = BlastSettingsCard(
            self.ssh_card.get_active_client,
            self.linux_card.get_values  # 传递获取配置的方法，可以从中提取项目路径
        )
        self.blast_card.request_save.connect(self.save_config)
        self.scroll_layout.addWidget(self.blast_card)

        # NCBI 卡片
        self.ncbi_card = NcbiSettingsCard()
        self.ncbi_card.request_save.connect(self._save_ncbi_config)
        self.scroll_layout.addWidget(self.ncbi_card)

        # 在滚动布局底部添加弹簧，确保卡片靠上排列
        self.scroll_layout.addStretch()
        
        # 建立 SSH 与 Linux 配置的联动
        self.ssh_card.connection_state_changed.connect(
            lambda connected: self.linux_card.set_active_client(
                self.ssh_card.get_active_client() if connected else None
            )
        )

    def _init_save_area(self):
        # 移除单独的保存按钮，因为现在保存功能集成在BLAST设置卡片中
        pass

    # -------------------------
    # 对外能力：提供共享 SSHClient
    # -------------------------
    def get_active_client(self):
        return self.ssh_card.get_active_client()

    def set_global_lock(self, locked: bool, reason: str = "SSH 正在使用中，系统设置已锁定") -> None:
        self.ssh_card.set_external_lock(locked, reason)
        self.blast_card.set_external_lock(locked)
        if hasattr(self.linux_card, "_toggle_lock"):
            self.linux_card._toggle_lock(locked)
        self.ncbi_card.set_external_lock(locked)

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
        """补充默认配置项"""
        return {
            "server_ip": DEFAULT_CONFIG.get("ip", ""),
            "ssh_user": DEFAULT_CONFIG.get("user", ""),
            "ssh_pwd": DEFAULT_CONFIG.get("pwd", ""),
            "ncbi_api_key": DEFAULT_CONFIG.get("ncbi_api_key", ""),
            "remote_db": DEFAULT_CONFIG.get("remote_db", ""), # 新增项
            "blast_bin": DEFAULT_CONFIG.get("blast_bin", ""), # 新增项
            "remote_dir": DEFAULT_CONFIG.get("remote_dir", ""), # 新增
            "linux_project_path": "", # 添加 Linux 项目路径
            "conda_env_path": "", # 添加 Conda 环境路径
            "conda_env_name": "", # 添加 Conda 环境显示名称
        }

    def _load_config_merged(self) -> dict:
        merged = self._default_config_for_ui()
        merged.update({k: v for k, v in self._read_config_file().items() if v is not None})
        return merged

    def _apply_config_to_components(self, merged: dict) -> None:
        """将加载的配置分发给各卡片"""
        self.ssh_card.set_values(
            server_ip=str(merged.get("server_ip", "") or ""),
            ssh_user=str(merged.get("ssh_user", "") or ""),
            ssh_pwd=str(merged.get("ssh_pwd", "") or ""),
        )
        # 为 Linux 卡片设置初始值
        self.linux_card.set_values(
            project_path=str(merged.get("linux_project_path", "") or ""),
            conda_env=str(merged.get("conda_env_path", "") or ""),
            conda_env_name=str(merged.get("conda_env_name", "") or "")
        )
        self.blast_card.set_values(
            remote_db=str(merged.get("remote_db", "") or ""),
            blast_bin=str(merged.get("blast_bin", "") or ""),
            remote_dir=str(merged.get("remote_dir", "") or "")
        )
        self.ncbi_card.set_values(ncbi_api_key=str(merged.get("ncbi_api_key", "") or ""))

    def _collect_components_config(self) -> dict:
        """收集所有卡片的配置"""
        data = {}
        data.update(self.ssh_card.get_values())
        data.update(self.blast_card.get_values())  # 收集新卡片数据
        data.update(self.linux_card.get_values())
        data.update(self.ncbi_card.get_values())
        return data

    # -------------------------
    # Public config API
    # -------------------------
    def load_config(self):
        merged = self._load_config_merged()
        self._apply_config_to_components(merged)

    def save_config(self):
        try:
            data = self._collect_components_config()
            self._write_config_file(data)

            # 同步更新DEFAULT_CONFIG以确保其他页面能获取到最新的配置
            for key in DEFAULT_CONFIG:
                if key in data:
                    DEFAULT_CONFIG[key] = data[key]

            # 旧行为：保存成功在 SSH 卡片区域提示
            try:
                self.ssh_card.status_label.setText("设置已保存")
            except Exception:
                pass

            # 保存后锁定 NCBI（有 key 就锁定，空就保持可编辑）
            self.ncbi_card.lock_if_needed()
        except Exception as e:
            # 捕获保存过程中的任何异常，防止程序崩溃
            import logging
            logging.error(f"保存配置失败: {e}", exc_info=True)
            try:
                self.ssh_card.status_label.setText(f"保存失败: {str(e)}")
                self.ssh_card.status_label.setStyleSheet("color: #e74c3c;")
            except Exception:
                pass

    def _save_ncbi_config(self):
        data = self._read_config_file()
        data["ncbi_api_key"] = self.ncbi_card.get_values().get("ncbi_api_key", "")
        self._write_config_file(data)
        # 同步更新DEFAULT_CONFIG以确保其他页面能获取到最新的配置
        DEFAULT_CONFIG["ncbi_api_key"] = data["ncbi_api_key"]
        self.ncbi_card.lock_if_needed()

    # 在 SettingsPage 类中添加这个方法处理联动
    def _on_ssh_state_changed(self, connected: bool):
        """当 SSH 连接状态变化时，通知 Linux 卡片"""
        client = self.ssh_card.get_active_client() if connected else None
        self.linux_card.set_active_client(client)
