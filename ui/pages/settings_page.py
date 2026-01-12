from PyQt6.QtWidgets import QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from ui.page_base import BasePage
import ipaddress
import subprocess

class SettingsPage(BasePage):
    def __init__(self):
        super().__init__("⚙ 设置")
        # 隐藏基础页的标题行，去掉“系统设置”字样
        if hasattr(self, "label"):
            self.label.hide()
        self.init_ui()

    def init_ui(self):
        # 顶部测试连接区域
        ip_title = QLabel("测试连接")
        ip_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #333;")
        ip_row = QHBoxLayout()
        self.server_ip = QLineEdit()
        self.server_ip.setPlaceholderText("例如: 192.168.1.10")
        self.test_btn = QPushButton("测试连接")
        self.status_label = QLabel("未测试")
        self.status_label.setStyleSheet("color: #8c8c8c;")
        self.test_btn.clicked.connect(self._on_test_ip)
        ip_row.addWidget(self.server_ip)
        ip_row.addWidget(self.test_btn)
        ip_row.addWidget(self.status_label)

        # 其他表单项
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.db_path = QLineEdit()
        form.addRow("数据库路径:", self.db_path)

        # 底部按钮
        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        btn_row.addStretch(1)
        btn_row.addWidget(self.save_btn)

        # 组装布局
        self.layout.addWidget(ip_title)
        self.layout.addLayout(ip_row)
        self.layout.addLayout(form)
        self.layout.addLayout(btn_row)

    def _on_test_ip(self):
        ip = self.server_ip.text().strip()
        # 基本格式校验
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            self._set_status("IP 格式不正确", "#fa541c")
            return

        # 使用 Windows 的 ping 测试一次
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "1000", ip],  # -n 1: 次数；-w 1000: 超时毫秒
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as e:
            self._set_status(f"测试失败: {e}", "#fa541c")
            return

        if result.returncode == 0:
            self._set_status("连接正常", "#52c41a")
        else:
            self._set_status("连接失败", "#fa541c")

    def _set_status(self, text: str, color: str):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")
