import json
import os
import paramiko
import ipaddress
from PyQt6.QtWidgets import (QFormLayout, QLineEdit, QPushButton, QHBoxLayout,
                             QLabel, QVBoxLayout, QFrame, QWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from ui.page_base import BasePage  #


# --- SSH 验证线程 ---
class SSHWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, ip, user, pwd, timeout: float = 2.0):
        super().__init__()
        self.ip, self.user, self.pwd = ip, user, pwd
        self.timeout = timeout

    def run(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.ip,
                port=22,
                username=self.user,
                password=self.pwd,
                timeout=self.timeout,
            )
            # 这里只做连通性检查，成功后立即关闭
            try:
                tr = client.get_transport()
                if tr is not None:
                    tr.set_keepalive(30)
            except Exception:
                # keepalive 失败不影响整体结果
                pass
            client.close()
            self.finished.emit(True, "连接成功")
        except Exception as e:
            # 带上部分错误信息便于排查
            msg = f"连接失败: {str(e)}"
            if len(msg) > 80:
                msg = msg[:80]
            self.finished.emit(False, msg)


# --- 优化后的头部组件：增加手型光标指示 ---
class ClickableHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # --- 核心改进：设置手型光标，提示可展开 ---
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SettingsPage(BasePage):
    def __init__(self):
        super().__init__("⚙ 设置")
        if hasattr(self, "label"):
            self.label.hide()

        # 持久 SSH 连接（由主线程维护）
        self.active_client: paramiko.SSHClient | None = None

        # 记录启动时从配置文件读出的原始值，用于避免自动连接与用户编辑冲突
        self._loaded_ip = ""
        self._loaded_user = ""
        self._loaded_pwd = ""

        # 精准定位 Roaming 路径
        appdata = os.getenv("APPDATA") or os.getcwd()
        self.config_dir = os.path.join(appdata, "H2OMeta")
        self.config_path = os.path.join(self.config_dir, "config.json")
        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir, exist_ok=True)
            except Exception:
                # 如果创建失败，退回当前工作目录
                self.config_dir = os.getcwd()
                self.config_path = os.path.join(self.config_dir, "config.json")

        self.setStyleSheet("background-color: #f4f9ff;")
        self.init_ui()
        self.load_config()

        # 延迟启动自动测试，避开初始渲染峰值
        QTimer.singleShot(1000, self._auto_check_on_start)

    def init_ui(self):
        self.layout.setContentsMargins(40, 30, 40, 30)
        self.layout.setSpacing(20)

        # 1. SSH 配置卡片
        self.ssh_card = QFrame()
        self.ssh_card.setObjectName("SSHCard")
        self.ssh_card.setStyleSheet(
            "QFrame#SSHCard { background: white; border: 1px solid #e1eefb; border-radius: 12px; }"
        )
        ssh_main_layout = QVBoxLayout(self.ssh_card)
        ssh_main_layout.setContentsMargins(0, 0, 0, 0)

        # --- 可点击的头部：整行手型 + 点击响应 ---
        self.header_area = ClickableHeader()
        self.header_area.setStyleSheet("background: transparent; border: none;")
        self.header_area.clicked.connect(self._toggle_ssh_container)

        header_layout = QHBoxLayout(self.header_area)
        header_layout.setContentsMargins(20, 15, 20, 15)

        self.ssh_title = QLabel("Linux服务器SSH连接")
        self.ssh_title.setStyleSheet("font-weight: 600; color: #4a6a8a; font-size: 14px;")

        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet("color: #90adca; font-size: 12px;")

        self.modify_link = QPushButton("修改")
        self.modify_link.setFixedWidth(40)
        self.modify_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.modify_link.setStyleSheet(
            "color: #1890ff; border: none; background: transparent; font-size: 11px; text-decoration: underline;"
        )
        self.modify_link.clicked.connect(self._enable_editing)
        self.modify_link.hide()

        header_layout.addWidget(self.ssh_title)
        header_layout.addStretch()
        header_layout.addWidget(self.modify_link)
        header_layout.addWidget(self.arrow_label)
        ssh_main_layout.addWidget(self.header_area)

        # --- 折叠内容区 ---
        self.ssh_container = QWidget()
        c_layout = QVBoxLayout(self.ssh_container)
        c_layout.setContentsMargins(20, 0, 20, 20)

        form = QFormLayout()
        input_style = "padding: 10px; border: 1px solid #dcebfa; border-radius: 6px; background: #fafcfe;"
        self.server_ip = QLineEdit()
        self.ssh_user = QLineEdit()
        self.ssh_pwd = QLineEdit()
        self.ssh_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        for w in [self.server_ip, self.ssh_user, self.ssh_pwd]:
            w.setStyleSheet(input_style)
            w.textChanged.connect(self._validate_inputs)

        form.addRow("服务器 IP", self.server_ip)
        form.addRow("用户名", self.ssh_user)
        form.addRow("SSH 密码", self.ssh_pwd)
        c_layout.addLayout(form)

        op_row = QHBoxLayout()
        self.connect_btn = QPushButton("连接并锁定")
        self.connect_btn.setFixedWidth(110)
        self.connect_btn.setEnabled(False)
        self.connect_btn.setStyleSheet(
            "QPushButton { background: #1890ff; color: white; border-radius: 6px; padding: 8px; font-weight: bold; } "
            "QPushButton:disabled { background: #bae7ff; }"
        )
        self.connect_btn.clicked.connect(self._on_connect_ssh)

        # 连接状态与保存状态分开，避免信息混淆
        self.status_label = QLabel("等待验证")
        self.status_label.setStyleSheet("color: #a0aec0; margin-left: 10px;")

        self.save_status_label = QLabel("")
        self.save_status_label.setStyleSheet("color: #a0aec0; margin-left: 10px; font-size: 11px;")

        op_row.addWidget(self.connect_btn)
        op_row.addWidget(self.status_label)
        op_row.addStretch()
        c_layout.addLayout(op_row)
        c_layout.addWidget(self.save_status_label)
        ssh_main_layout.addWidget(self.ssh_container)

        self.layout.addWidget(self.ssh_card)

        # 底部保存
        self.save_btn = QPushButton("保存全部设置")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(
            "background: #52c41a; color: white; border-radius: 6px; padding: 10px; font-weight: bold;"
        )
        self.save_btn.clicked.connect(self.save_config)
        self.layout.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.layout.addStretch()

    def _validate_inputs(self):
        ip = self.server_ip.text().strip()
        user = self.ssh_user.text().strip()
        pwd = self.ssh_pwd.text().strip()
        is_valid = False
        try:
            if ip:
                ipaddress.ip_address(ip)
                is_valid = True
        except Exception:
            is_valid = False
        self.connect_btn.setEnabled(bool(ip and user and pwd and is_valid))

    def _on_connect_ssh(self):
        # 避免重复发起连接
        if hasattr(self, "_connecting") and self._connecting:
            return
        self._connecting = True

        self.connect_btn.setEnabled(False)
        self.status_label.setText("正在验证...")
        self.status_label.setStyleSheet("color: #1890ff; margin-left: 10px;")

        # 启动线程做一次连通性检查
        self.worker = SSHWorker(self.server_ip.text().strip(), self.ssh_user.text().strip(), self.ssh_pwd.text().strip())
        self.worker.finished.connect(self._on_connect_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _ensure_persistent_connection(self) -> bool:
        """确保 active_client 处于已连接状态，必要时在主线程中重新建立长连接。"""
        ip = self.server_ip.text().strip()
        user = self.ssh_user.text().strip()
        pwd = self.ssh_pwd.text().strip()
        if not (ip and user and pwd):
            return False

        # 如果已有连接，简单做一次心跳测试
        if self.active_client is not None:
            try:
                stdin, stdout, stderr = self.active_client.exec_command("echo ping", timeout=5)
                stdout.channel.recv_exit_status()
                return True
            except Exception:
                try:
                    self.active_client.close()
                except Exception:
                    pass
                self.active_client = None

        # 重新建立一个长期连接
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(ip, port=22, username=user, password=pwd, timeout=5)
            tr = client.get_transport()
            if tr is not None:
                tr.set_keepalive(30)
            self.active_client = client
            return True
        except Exception:
            try:
                client.close()
            except Exception:
                pass
            self.active_client = None
            return False

    def _on_connect_finished(self, success: bool, msg: str):
        # 线程已结束
        self._connecting = False

        self.status_label.setText(msg)
        if success:
            # 确保建立一条持久连接
            ok = self._ensure_persistent_connection()
            if ok:
                self.status_label.setText("连接成功，已保持长连接")
                self.status_label.setStyleSheet("color: #52c41a; margin-left: 10px;")
                for w in [self.server_ip, self.ssh_user, self.ssh_pwd, self.connect_btn]:
                    w.setEnabled(False)
                QTimer.singleShot(1500, self._auto_fold)
            else:
                self.status_label.setText("连接测试成功，但建立长连接失败")
                self.status_label.setStyleSheet("color: #ff4d4f; margin-left: 10px;")
                # 允许用户重新尝试
                self._validate_inputs()
        else:
            self.status_label.setStyleSheet("color: #ff4d4f; margin-left: 10px;")
            self._validate_inputs()

    def _auto_fold(self):
        if not self.server_ip.isEnabled():
            self.ssh_container.hide()
            self.arrow_label.setText("▼")
            self.modify_link.show()

    def _toggle_ssh_container(self):
        # 增加状态保护，防止在自动连接时干扰 UI 渲染
        if getattr(self, "_connecting", False) and self.status_label.text().startswith("正在验证"):
            return
        visible = self.ssh_container.isVisible()
        self.ssh_container.setVisible(not visible)
        self.arrow_label.setText("▲" if not visible else "▼")

    def _enable_editing(self):
        self.ssh_container.show()
        self.arrow_label.setText("▲")
        for w in [self.server_ip, self.ssh_user, self.ssh_pwd, self.connect_btn]:
            w.setEnabled(True)
        self.modify_link.hide()
        self.status_label.setText("等待验证")
        self.status_label.setStyleSheet("color: #a0aec0; margin-left: 10px;")
        self._validate_inputs()

    def save_config(self):
        data = {
            "server_ip": self.server_ip.text().strip(),
            "ssh_user": self.ssh_user.text().strip(),
            "ssh_pwd": self.ssh_pwd.text().strip(),
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            self.save_status_label.setText("本地已保存配置")
            self.save_status_label.setStyleSheet("color: #52c41a; margin-left: 10px; font-size: 11px;")
        except Exception as e:
            self.save_status_label.setText(f"保存失败: {e}")
            self.save_status_label.setStyleSheet("color: #ff4d4f; margin-left: 10px; font-size: 11px;")

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._loaded_ip = data.get("server_ip", "")
                self._loaded_user = data.get("ssh_user", "")
                self._loaded_pwd = data.get("ssh_pwd", "")

                self.server_ip.setText(self._loaded_ip)
                self.ssh_user.setText(self._loaded_user)
                self.ssh_pwd.setText(self._loaded_pwd)
                self._validate_inputs()
            except Exception:
                # 配置损坏时保持为空，让用户重新填
                self._loaded_ip = self._loaded_user = self._loaded_pwd = ""

    def _values_equal_loaded(self) -> bool:
        """当前输入是否仍然等于启动时从配置文件读取的值。"""
        return (
            self.server_ip.text().strip() == self._loaded_ip
            and self.ssh_user.text().strip() == self._loaded_user
            and self.ssh_pwd.text().strip() == self._loaded_pwd
        )

    def _auto_check_on_start(self):
        # 仅当：按钮可用 + 当前值和加载时完全一致 时才自动连接，避免与用户编辑冲突
        if self.connect_btn.isEnabled() and self._values_equal_loaded():
            self._on_connect_ssh()

    def closeEvent(self, event):
        # 确保页面关闭时断开持久连接
        try:
            if self.active_client is not None:
                self.active_client.close()
        except Exception:
            pass
        self.active_client = None
        super().closeEvent(event)

