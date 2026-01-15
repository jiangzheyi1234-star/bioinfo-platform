import json
import os
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QScrollArea, QFrame, QVBoxLayout, QWidget

from config import DEFAULT_CONFIG
from ui.page_base import BasePage
from ui.widgets import SshSettingsCard, NcbiSettingsCard, BlastSettingsCard
from ui.widgets.styles import PAGE_HEADER_TITLE, BUTTON_SUCCESS, COLOR_BG_APP

class SettingsPage(BasePage):
    def __init__(self):
        super().__init__("\u2698 \u8bbe\u7f6e")
        if hasattr(self, "label"):
            self.label.hide()

        self.config_dir = os.path.join(os.getenv('APPDATA'), "H2OMeta")
        self.config_path = os.path.join(self.config_dir, "config.json")
        os.makedirs(self.config_dir, exist_ok=True)

        self.setStyleSheet(f"background-color: {COLOR_BG_APP};")

        self.init_ui()
        self.load_config()

        # 启动即自动执行一次连接测试
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1000, self.ssh_card.auto_check_on_start)

    # -------------------------
    # UI 构建：调度员
    # -------------------------
    def init_ui(self):
        """调度员：只负责页面整体参数与模块调用顺序，不写任何卡片细节。"""
        # 清空原始布局，创建滚动区域
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)  # 关键：让内部控件自适应宽度
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)  # 去掉滚动区域的边框
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # 通常不需要横向滚动

        # 创建“内容容器” (所有的卡片都放在这里面)
        content_widget = QWidget()
        content_widget.setObjectName("ScrollContent")
        # 给内容容器设置透明背景或特定背景
        content_widget.setStyleSheet(f"background-color: {COLOR_BG_APP};") 
        
        # 内容容器的布局
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(40, 30, 40, 30)  # 控制卡片离边缘的距离
        content_layout.setSpacing(25)  # 控制卡片之间的间距

        self._init_header(content_layout)
        self._init_cards(content_layout)
        self._init_save_area(content_layout)

        content_layout.addStretch()

        # 组装层级
        scroll_area.setWidget(content_widget)  # 把内容塞进滚动区
        self.layout.addWidget(scroll_area)    # 把滚动区塞进主界面

    def _init_header(self, layout):
        header_title = QLabel("系统设置")
        header_title.setStyleSheet(PAGE_HEADER_TITLE)
        layout.addWidget(header_title)

    def _init_cards(self, layout):
        # SSH 卡片
        self.ssh_card = SshSettingsCard()
        layout.addWidget(self.ssh_card)

        # BLAST 数据库设置卡片 (新增)
        # 传入 ssh_card 的 get_active_client 方法，以便它可以调用 SSH 进行验证
        self.blast_card = BlastSettingsCard(self.ssh_card.get_active_client)
        self.blast_card.request_save.connect(self.save_config)  # 连接保存信号
        layout.addWidget(self.blast_card)

        # NCBI 卡片
        self.ncbi_card = NcbiSettingsCard()
        self.ncbi_card.request_save.connect(self._save_ncbi_config)
        layout.addWidget(self.ncbi_card)

    def _init_save_area(self, layout):
        # 移除单独的保存按钮，因为现在保存功能集成在BLAST设置卡片中
        pass

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
        """补充默认配置项"""
        return {
            "server_ip": DEFAULT_CONFIG.get("ip", ""),
            "ssh_user": DEFAULT_CONFIG.get("user", ""),
            "ssh_pwd": DEFAULT_CONFIG.get("pwd", ""),
            "ncbi_api_key": DEFAULT_CONFIG.get("ncbi_api_key", ""),
            "remote_db": DEFAULT_CONFIG.get("remote_db", ""), # 新增项
            "blast_bin": DEFAULT_CONFIG.get("blast_bin", ""), # 新增项
            "remote_dir": DEFAULT_CONFIG.get("remote_dir", ""), # 新增
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
        # 传入三个参数到 blast_card
        self.blast_card.set_values(
            remote_db=str(merged.get("remote_db", "") or ""),
            blast_bin=str(merged.get("blast_bin", "") or ""),
            remote_dir=str(merged.get("remote_dir", "") or "") # 新增
        )
        self.ncbi_card.set_values(ncbi_api_key=str(merged.get("ncbi_api_key", "") or ""))

    def _collect_components_config(self) -> dict:
        """收集所有卡片的配置"""
        data = {}
        data.update(self.ssh_card.get_values())
        data.update(self.blast_card.get_values()) # 收集新卡片数据
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