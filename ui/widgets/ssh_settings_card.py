from __future__ import annotations

import ipaddress
import socket
import time
from typing import Protocol, Callable, Optional

import paramiko
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import (
    CARD_FRAME,
    INPUT_LINEEDIT,
    BUTTON_PRIMARY,
    BUTTON_SECONDARY,
    BUTTON_LINK,
    BUTTON_DANGER,
    CARD_TITLE,
    COLOR_TEXT_HINT,
    COLOR_TEXT_SUB,
    COLOR_SUCCESS,
    COLOR_DANGER,
    COLOR_WARNING,
    COLOR_BG_BLANK,
    COLOR_BG_CARD,
    COLOR_BORDER_INPUT,
    RADIUS_CTRL,
    STATUS_NEUTRAL,
    STATUS_SUCCESS,
    STATUS_ERROR,
)


# ---- 错误消息分类 ----
def _classify_ssh_error(exc: Exception) -> str:
    """将 paramiko / socket 异常转为用户友好的中文消息。"""
    if isinstance(exc, paramiko.AuthenticationException):
        return "认证失败 — 用户名或密码（密钥）不正确"
    if isinstance(exc, paramiko.SSHException):
        return f"SSH 协议错误 — {exc}"
    if isinstance(exc, socket.timeout):
        return "连接超时 — 服务器地址或端口不可达"
    if isinstance(exc, ConnectionRefusedError):
        return "连接被拒绝 — 目标端口未开放"
    if isinstance(exc, socket.gaierror):
        return "无法解析主机 — 检查 IP 地址或网络连接"
    if isinstance(exc, OSError):
        msg = str(exc)
        if "No route to host" in msg:
            return "无法路由到主机 — 检查网络连接"
        if "Network is unreachable" in msg:
            return "网络不可达 — 检查本地网络连接"
        return f"系统错误 — {msg}"
    return f"未知错误 — {exc}"


# ---- Typed signal Protocols for better IDE hints ----
class _FinishedSignal(Protocol):
    def connect(self, slot: Callable[[bool, str, object], None]) -> None: ...
    def emit(self, ok: bool, msg: str, client: object) -> None: ...


class _NoArgSignal(Protocol):
    def connect(self, slot: Callable[[], None]) -> None: ...
    def emit(self) -> None: ...


class SSHWorker(QObject):
    """后台连接工作线程，分步骤汇报进度。"""
    finished: _FinishedSignal = pyqtSignal(bool, str, object)
    step_updated = pyqtSignal(int, str)   # (step_index, "running"/"ok"/"fail")
    error_detail = pyqtSignal(str)        # 详细错误消息

    def __init__(self, ip: str, port: int, user: str, pwd: str,
                 key_file: str = "", parent=None):
        super().__init__(parent)
        self.ip, self.port, self.user, self.pwd = ip, port, user, pwd
        self.key_file = key_file

    @pyqtSlot()
    def run(self):
        try:
            self._do_connect()
        except Exception as e:
            # 兜底：确保 finished 始终被发射，避免 UI 卡死
            try:
                self.error_detail.emit(f"未知错误 — {e}")
            except Exception:
                pass
            try:
                self.finished.emit(False, "连接失败", None)
            except Exception:
                pass

    def _do_connect(self):
        # --- Step 0: TCP 端口可达性 ---
        self.step_updated.emit(0, "running")
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=5)
            sock.close()
        except Exception as e:
            self.step_updated.emit(0, "fail")
            self.error_detail.emit(_classify_ssh_error(e))
            self.finished.emit(False, "连接失败", None)
            return
        self.step_updated.emit(0, "ok")

        # --- Step 1: SSH 握手 + 身份验证 ---
        self.step_updated.emit(1, "running")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            connect_kwargs: dict = {
                "hostname": self.ip,
                "port": self.port,
                "username": self.user,
                "timeout": 5,
                "allow_agent": False,
                "look_for_keys": False,
            }
            if self.key_file:
                connect_kwargs["key_filename"] = self.key_file
            else:
                connect_kwargs["password"] = self.pwd
            client.connect(**connect_kwargs)
        except paramiko.AuthenticationException as e:
            # SSH 握手成功，认证失败 → step1 ok, step2 fail
            self.step_updated.emit(1, "ok")
            self.step_updated.emit(2, "fail")
            self.error_detail.emit(_classify_ssh_error(e))
            self.finished.emit(False, "认证失败", None)
            return
        except Exception as e:
            self.step_updated.emit(1, "fail")
            self.error_detail.emit(_classify_ssh_error(e))
            self.finished.emit(False, "连接失败", None)
            return
        self.step_updated.emit(1, "ok")

        # --- Step 2: 身份验证成功 ---
        self.step_updated.emit(2, "ok")
        try:
            client.get_transport().set_keepalive(30)
        except Exception:
            pass
        self.finished.emit(True, "连接成功", client)


# ---- 诊断对话框 ----
class SSHDiagnosticWorker(QObject):
    """独立诊断工作线程，返回详细逐步结果。"""
    log = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(self, ip: str, port: int, user: str, pwd: str,
                 key_file: str = "", parent=None):
        super().__init__(parent)
        self.ip, self.port, self.user, self.pwd = ip, port, user, pwd
        self.key_file = key_file

    @pyqtSlot()
    def run(self):
        self.log.emit("=" * 45)
        self.log.emit(f"  SSH 连接诊断 — {self.ip}:{self.port}")
        self.log.emit("=" * 45 + "\n")

        # Step 1: DNS / IP 解析
        self.log.emit("① 检查主机地址格式...")
        try:
            ipaddress.ip_address(self.ip)
            self.log.emit(f"   ✓ {self.ip} 格式正确（IPv4 地址）\n")
        except ValueError:
            try:
                resolved = socket.getaddrinfo(self.ip, self.port)
                ip = resolved[0][4][0]
                self.log.emit(f"   ✓ 域名解析成功 → {ip}\n")
            except Exception as e:
                self.log.emit(f"   ✗ 域名解析失败: {e}\n")
                self.log.emit("\n结论：无法解析主机地址，请检查输入。")
                self.done.emit()
                return

        # Step 2: TCP 连接
        self.log.emit(f"② TCP 连接到端口 {self.port}...")
        t0 = time.perf_counter()
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=5)
            elapsed = (time.perf_counter() - t0) * 1000
            sock.close()
            self.log.emit(f"   ✓ 成功 ({elapsed:.0f}ms)\n")
        except socket.timeout:
            self.log.emit(f"   ✗ 超时 (>5s) — 端口可能被防火墙屏蔽\n")
            self.log.emit("\n结论：TCP 无法到达目标端口，检查防火墙或 IP/端口设置。")
            self.done.emit()
            return
        except ConnectionRefusedError:
            self.log.emit(f"   ✗ 连接被拒绝 — 端口 {self.port} 未开放\n")
            self.log.emit("\n结论：目标端口未开放，确认 SSH 服务是否运行。")
            self.done.emit()
            return
        except Exception as e:
            self.log.emit(f"   ✗ 失败: {e}\n")
            self.log.emit("\n结论：无法建立 TCP 连接。")
            self.done.emit()
            return

        # Step 3: SSH 握手
        self.log.emit("③ SSH 协议握手...")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            transport = paramiko.Transport((self.ip, self.port))
            transport.connect()
            remote_version = transport.remote_version or "未知"
            transport.close()
            self.log.emit(f"   ✓ 成功 (服务器: {remote_version})\n")
        except Exception as e:
            self.log.emit(f"   ✗ SSH 握手失败: {e}\n")
            self.log.emit("\n结论：TCP 可达但 SSH 握手失败，端口可能不是 SSH 服务。")
            self.done.emit()
            return

        # Step 4: 身份验证
        auth_method = "密钥文件" if self.key_file else "密码"
        self.log.emit(f"④ 身份验证 (方式: {auth_method})...")
        try:
            connect_kwargs: dict = {
                "hostname": self.ip,
                "port": self.port,
                "username": self.user,
                "timeout": 5,
                "allow_agent": False,
                "look_for_keys": False,
            }
            if self.key_file:
                connect_kwargs["key_filename"] = self.key_file
            else:
                connect_kwargs["password"] = self.pwd
            client.connect(**connect_kwargs)
            client.close()
            self.log.emit(f"   ✓ 认证成功\n")
        except paramiko.AuthenticationException:
            self.log.emit(f"   ✗ 认证失败 — 用户名或{auth_method}不正确\n")
            self.log.emit(f"\n结论：服务器可达，SSH 正常，请检查用户名和{auth_method}。")
            self.done.emit()
            return
        except Exception as e:
            self.log.emit(f"   ✗ 认证过程出错: {e}\n")
            self.log.emit("\n结论：认证过程异常。")
            self.done.emit()
            return

        self.log.emit("─" * 45)
        self.log.emit("结论：所有检查通过，连接配置正常。")
        self.done.emit()


class SSHDiagnosticDialog(QDialog):
    """SSH 诊断弹窗。"""

    def __init__(self, ip: str, port: int, user: str, pwd: str,
                 key_file: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH 连接诊断")
        self.setMinimumSize(520, 400)
        self.resize(560, 440)
        self.setStyleSheet("""
            QDialog {
                background-color: #F0F7FF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(f"""
            QTextEdit {{
                font-family: 'Consolas', 'Microsoft YaHei UI', monospace;
                font-size: 13px;
                background-color: #F5F5F5;
                color: #333333;
                border: none;
                border-radius: 6px;
                padding: 12px;
            }}
        """)
        layout.addWidget(self.output)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.close_btn = QPushButton("关闭")
        self.close_btn.setStyleSheet(BUTTON_SECONDARY)
        self.close_btn.setMinimumWidth(80)
        self.close_btn.clicked.connect(self.accept)
        self.close_btn.setEnabled(False)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        # 启动诊断线程
        self._thread = QThread(self)
        self._worker = SSHDiagnosticWorker(ip, port, user, pwd, key_file)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append_log)
        self._worker.done.connect(self._on_done)
        self._worker.done.connect(self._thread.quit)
        self._worker.done.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _append_log(self, text: str) -> None:
        # 将特殊字符着色
        html = text
        if "✓" in html:
            html = html.replace("✓", '<span style="color: #A6E3A1;">✓</span>')
        if "✗" in html:
            html = html.replace("✗", '<span style="color: #F38BA8;">✗</span>')
        if html.startswith("结论"):
            html = f'<span style="color: #F9E2AF; font-weight: bold;">{html}</span>'
        self.output.append(html)

    def _on_done(self) -> None:
        self.close_btn.setEnabled(True)


class ClickableHeader(QFrame):
    clicked: _NoArgSignal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# ---- 分步状态指示器 ----
class StepIndicator(QWidget):
    """三步骤连接进度指示器：TCP连接 → SSH握手 → 身份验证"""

    STEP_LABELS = ["TCP 连接", "SSH 握手", "身份验证"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(0)

        self._icons: list[QLabel] = []
        self._labels: list[QLabel] = []

        for i, label_text in enumerate(self.STEP_LABELS):
            if i > 0:
                arrow = QLabel("  →  ")
                arrow.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px; background: transparent;")
                layout.addWidget(arrow)

            icon = QLabel("○")
            icon.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 13px; background: transparent;")
            icon.setFixedWidth(16)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._icons.append(icon)

            label = QLabel(label_text)
            label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px; background: transparent;")
            self._labels.append(label)

            layout.addWidget(icon)
            layout.addWidget(label)

        layout.addStretch()

    def reset(self) -> None:
        for icon, label in zip(self._icons, self._labels):
            icon.setText("○")
            icon.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 13px; background: transparent;")
            label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px; background: transparent;")

    def set_step(self, index: int, status: str) -> None:
        if index < 0 or index >= len(self._icons):
            return
        icon = self._icons[index]
        label = self._labels[index]

        if status == "running":
            icon.setText("●")
            icon.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 13px; background: transparent;")
            label.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 12px; font-weight: 600; background: transparent;")
        elif status == "ok":
            icon.setText("✓")
            icon.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 13px; background: transparent;")
            label.setStyleSheet(f"color: {COLOR_SUCCESS}; font-size: 12px; font-weight: 600; background: transparent;")
        elif status == "fail":
            icon.setText("✗")
            icon.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 13px; background: transparent;")
            label.setStyleSheet(f"color: {COLOR_DANGER}; font-size: 12px; font-weight: 600; background: transparent;")


class SshSettingsCard(QFrame):
    """SSH 设置卡片组件。

    Contract:
      - set_values()/get_values()：与 SettingsPage 做配置同步。
      - get_active_client()：对外提供可复用的 SSHClient（可能为 None）。
      - request_save：当卡片内发生"需要保存"的动作时发出（当前用于状态联动，可选）。
    """

    request_save = pyqtSignal()
    connection_state_changed = pyqtSignal(bool)  # connected

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SSHCard")

        self.active_client = None
        self.last_stable_config = None
        self.connected = False
        self._connecting = False
        self._in_edit_mode = False
        self._external_lock = False
        self._status_cache: Optional[tuple[str, str]] = None

        # timers
        self._auto_fold_timer = QTimer(self)
        self._auto_fold_timer.setSingleShot(True)
        self._auto_fold_timer.timeout.connect(self._auto_fold_after_idle)

        self._edit_idle_timer = QTimer(self)
        self._edit_idle_timer.setSingleShot(True)
        self._edit_idle_timer.timeout.connect(self._auto_connect_after_edit_idle)

        self._ssh_health_timer = QTimer(self)
        self._ssh_health_timer.setInterval(15_000)
        self._ssh_health_timer.timeout.connect(self._check_ssh_health)
        self._ssh_health_timer.start()

        self._ssh_thread: Optional[QThread] = None
        self._ssh_worker: Optional[SSHWorker] = None

        self._build_ui()
        self._bind_global_focus_listener()

    # -------------------------
    # Public API: config sync
    # -------------------------
    def set_values(self, server_ip: str = "", ssh_port: int = 22,
                   ssh_user: str = "", ssh_pwd: str = "",
                   use_key: bool = False, key_file: str = "") -> None:
        self.server_ip.setText(str(server_ip or ""))
        self.ssh_port.setText(str(ssh_port or 22))
        self.ssh_user.setText(str(ssh_user or ""))
        self.ssh_pwd.setText(str(ssh_pwd or ""))
        self.use_key_cb.setChecked(use_key)
        self.key_file_input.setText(str(key_file or ""))
        self._toggle_auth_mode(use_key)

        self._validate_inputs()
        self._in_edit_mode = True

        if server_ip and (ssh_pwd or key_file):
            self.last_stable_config = {
                'ip': server_ip, 'port': ssh_port or 22,
                'user': ssh_user, 'pwd': ssh_pwd,
                'use_key': use_key, 'key_file': key_file,
            }
            self._lock_inputs()
            QTimer.singleShot(1000, self.try_auto_connect)
        else:
            self._enable_editing()

    def get_values(self) -> dict:
        return {
            "server_ip": self.server_ip.text(),
            "ssh_port": int(self.ssh_port.text() or 22),
            "ssh_user": self.ssh_user.text(),
            "ssh_pwd": self.ssh_pwd.text(),
            "use_key": self.use_key_cb.isChecked(),
            "key_file": self.key_file_input.text(),
        }

    def try_auto_connect(self) -> None:
        if self._connecting:
            return
        self._validate_inputs()
        if not self.connect_btn.isEnabled():
            return
        self._on_connect_ssh()

    def auto_check_on_start(self) -> None:
        if self._connecting:
            return
        self._validate_inputs()
        if self.connect_btn.isEnabled():
            self._on_connect_ssh()

    def get_active_client(self):
        return self.active_client

    def set_external_lock(self, locked: bool, reason: str = "SSH 正在使用中，设置已锁定") -> None:
        if self._external_lock == locked:
            return
        self._external_lock = locked
        if locked:
            self._status_cache = (self.status_label.text(), self.status_label.styleSheet())
            self.status_label.setText(reason)
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
        else:
            if self._status_cache:
                text, style = self._status_cache
                self.status_label.setText(text)
                self.status_label.setStyleSheet(style)
                self._status_cache = None
        self._refresh_interaction_state()

    # -------------------------
    # Internal UI
    # -------------------------
    def _build_ui(self) -> None:
        self.setStyleSheet(CARD_FRAME("SSHCard"))

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)

        self.header_area = ClickableHeader()
        self.header_area.setStyleSheet("background: transparent; border: none;")
        self.header_area.clicked.connect(self._toggle_container)

        header_layout = QHBoxLayout(self.header_area)
        header_layout.setContentsMargins(20, 15, 20, 15)

        self.ssh_title = QLabel("Linux服务器SSH连接")
        self.ssh_title.setStyleSheet(CARD_TITLE)

        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px; border: none; background: transparent;")

        self.modify_link = QPushButton("修改")
        self.modify_link.setMinimumWidth(60)
        self.modify_link.setStyleSheet(BUTTON_LINK)
        self.modify_link.clicked.connect(self._enable_editing)

        header_layout.addWidget(self.ssh_title)
        header_layout.addStretch()
        header_layout.addWidget(self.modify_link)
        header_layout.addWidget(self.arrow_label)
        main.addWidget(self.header_area)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(20, 0, 20, 20)

        form = QFormLayout()
        form.setVerticalSpacing(15)

        self.server_ip = QLineEdit()
        self.server_ip.setStyleSheet(INPUT_LINEEDIT)
        self.server_ip.setPlaceholderText("例如 192.168.0.152")
        self.ssh_port = QLineEdit()
        self.ssh_port.setStyleSheet(INPUT_LINEEDIT)
        self.ssh_port.setText("22")
        self.ssh_port.setMaximumWidth(80)
        self.ssh_user = QLineEdit()
        self.ssh_user.setStyleSheet(INPUT_LINEEDIT)
        self.ssh_user.setPlaceholderText("例如 root")
        self.ssh_pwd = QLineEdit()
        self.ssh_pwd.setStyleSheet(INPUT_LINEEDIT)
        self.ssh_pwd.setEchoMode(QLineEdit.EchoMode.Password)

        for w in [self.server_ip, self.ssh_port, self.ssh_user, self.ssh_pwd]:
            w.textChanged.connect(lambda _text, _=w: self._on_edit_changed())

        form.addRow("服务器 IP", self.server_ip)
        form.addRow("SSH 端口", self.ssh_port)
        form.addRow("用户名", self.ssh_user)

        # 密钥认证切换
        self.use_key_cb = QCheckBox("使用密钥文件认证")
        self.use_key_cb.setStyleSheet(f"color: {COLOR_TEXT_SUB}; font-size: 12px; background: transparent;")
        self.use_key_cb.toggled.connect(self._toggle_auth_mode)

        # 密码行
        self.pwd_label = QLabel("SSH 密码")
        form.addRow(self.pwd_label, self.ssh_pwd)

        # 密钥文件行
        self.key_file_row = QWidget()
        self.key_file_row.setStyleSheet("background: transparent;")
        key_layout = QHBoxLayout(self.key_file_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(8)
        self.key_file_input = QLineEdit()
        self.key_file_input.setStyleSheet(INPUT_LINEEDIT)
        self.key_file_input.setPlaceholderText("选择 .pem / .rsa / id_rsa 文件")
        self.key_file_input.textChanged.connect(lambda _: self._on_edit_changed())
        self.browse_key_btn = QPushButton("浏览…")
        self.browse_key_btn.setStyleSheet(BUTTON_SECONDARY)
        self.browse_key_btn.setFixedWidth(70)
        self.browse_key_btn.clicked.connect(self._browse_key_file)
        key_layout.addWidget(self.key_file_input)
        key_layout.addWidget(self.browse_key_btn)

        self.key_file_label = QLabel("密钥文件")
        form.addRow(self.key_file_label, self.key_file_row)
        form.addRow("", self.use_key_cb)

        # 默认隐藏密钥行
        self.key_file_label.hide()
        self.key_file_row.hide()

        c_layout.addLayout(form)

        # 分步状态指示器
        self.step_indicator = StepIndicator()
        self.step_indicator.hide()
        c_layout.addWidget(self.step_indicator)

        # 错误详情标签
        self.error_detail_label = QLabel()
        self.error_detail_label.setStyleSheet(
            f"color: {COLOR_DANGER}; font-size: 12px; background: transparent; padding: 4px 0;"
        )
        self.error_detail_label.setWordWrap(True)
        self.error_detail_label.hide()
        c_layout.addWidget(self.error_detail_label)

        # 按钮行
        row = QHBoxLayout()
        self.connect_btn = QPushButton("连接并锁定")
        self.connect_btn.setMinimumWidth(110)
        self.connect_btn.setEnabled(False)
        self.connect_btn.setStyleSheet(BUTTON_PRIMARY)
        self.connect_btn.clicked.connect(lambda checked=False: self._on_connect_ssh())

        self.diagnose_btn = QPushButton("诊断")
        self.diagnose_btn.setMinimumWidth(70)
        self.diagnose_btn.setStyleSheet(BUTTON_SECONDARY)
        self.diagnose_btn.clicked.connect(self._on_diagnose)

        self.status_label = QLabel("等待验证")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)

        self.revert_btn = QPushButton("恢复上次成功")
        self.revert_btn.setStyleSheet(BUTTON_DANGER)
        self.revert_btn.clicked.connect(lambda checked=False: self._revert_to_last_stable())
        self.revert_btn.hide()

        row.addWidget(self.connect_btn)
        row.addWidget(self.diagnose_btn)
        row.addWidget(self.status_label)
        row.addWidget(self.revert_btn)
        row.addStretch()
        c_layout.addLayout(row)

        main.addWidget(self.container)

    def _bind_global_focus_listener(self) -> None:
        app = QApplication.instance()
        if app is not None and hasattr(app, "focusChanged"):
            app.focusChanged.connect(self._on_focus_changed)

    # -------------------------
    # Auth mode toggle
    # -------------------------
    def _toggle_auth_mode(self, use_key: bool) -> None:
        self.ssh_pwd.setVisible(not use_key)
        self.pwd_label.setVisible(not use_key)
        self.key_file_label.setVisible(use_key)
        self.key_file_row.setVisible(use_key)
        self._validate_inputs()

    def _browse_key_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 SSH 密钥文件", "",
            "SSH 密钥文件 (*.pem *.rsa *.key id_rsa id_ed25519);;所有文件 (*)"
        )
        if path:
            self.key_file_input.setText(path)

    # -------------------------
    # Behavior
    # -------------------------
    def _validate_inputs(self) -> None:
        ip = self.server_ip.text().strip()
        port_str = self.ssh_port.text().strip()
        user = self.ssh_user.text().strip()
        pwd = self.ssh_pwd.text().strip()
        use_key = self.use_key_cb.isChecked()
        key_file = self.key_file_input.text().strip()

        valid_ip = False
        try:
            if ip:
                ipaddress.ip_address(ip)
                valid_ip = True
        except Exception:
            valid_ip = False

        valid_port = False
        try:
            port = int(port_str)
            valid_port = 1 <= port <= 65535
        except Exception:
            valid_port = False

        has_auth = bool(key_file) if use_key else bool(pwd)
        self.connect_btn.setEnabled(bool(ip and user and valid_ip and valid_port and has_auth))

    def _on_edit_changed(self) -> None:
        self._validate_inputs()
        if self._in_edit_mode:
            if self._edit_idle_timer.isActive():
                self._edit_idle_timer.stop()
            if self.connect_btn.isEnabled():
                self._edit_idle_timer.start(20_000)

    def _toggle_container(self) -> None:
        if self._connecting:
            return
        visible = self.container.isVisible()
        self.container.setVisible(not visible)
        self.arrow_label.setText("▲" if not visible else "▼")
        if self._auto_fold_timer.isActive():
            self._auto_fold_timer.stop()

    def _auto_fold(self) -> None:
        if not self.server_ip.isEnabled():
            self.container.hide()
            self.arrow_label.setText("▼")

    def _auto_fold_after_idle(self) -> None:
        if self.connected and (not self.server_ip.isEnabled()) and self.container.isVisible():
            self._auto_fold()

    def _auto_connect_after_edit_idle(self) -> None:
        if (not self._in_edit_mode) or (not self.connect_btn.isEnabled()):
            return
        self._on_connect_ssh()

    def _on_focus_changed(self, old, new) -> None:
        _ = old
        w = new
        watched = {
            self.server_ip,
            self.ssh_port,
            self.ssh_user,
            self.ssh_pwd,
            self.connect_btn,
            self.revert_btn,
            self.header_area,
            self.container,
            self.key_file_input,
            self.browse_key_btn,
            self.diagnose_btn,
        }

        inside_card = False
        if w is not None:
            if w in watched:
                inside_card = True
            elif isinstance(w, QWidget) and (w is self or self.isAncestorOf(w)):
                inside_card = True

        if inside_card:
            if self._auto_fold_timer.isActive():
                self._auto_fold_timer.stop()
            return

        if self.connected and (not self.server_ip.isEnabled()) and self.container.isVisible():
            self._auto_fold_timer.start(10_000)

    def _lock_inputs(self) -> None:
        for w in [self.server_ip, self.ssh_port, self.ssh_user, self.ssh_pwd,
                   self.connect_btn, self.key_file_input, self.browse_key_btn, self.use_key_cb]:
            w.setEnabled(False)
        self._in_edit_mode = False
        self.modify_link.show()
        self.revert_btn.hide()
        self._refresh_interaction_state()

    def _enable_editing(self) -> None:
        if self._external_lock:
            return
        self.container.show()
        self.arrow_label.setText("▲")
        for w in [self.server_ip, self.ssh_port, self.ssh_user, self.ssh_pwd,
                   self.key_file_input, self.browse_key_btn, self.use_key_cb]:
            w.setEnabled(True)
        self._in_edit_mode = True
        self.modify_link.show()
        self.revert_btn.hide()
        self._validate_inputs()
        self._on_edit_changed()

    def _on_connect_ssh(self) -> None:
        if self._connecting or self._external_lock:
            return

        if self.active_client is not None:
            try:
                self.active_client.close()
            except Exception:
                pass
            self.active_client = None

        self._connecting = True
        self.connect_btn.setEnabled(False)
        self.status_label.setStyleSheet(STATUS_NEUTRAL)
        self.status_label.setText("正在连接...")
        self.error_detail_label.hide()
        self.step_indicator.reset()
        self.step_indicator.show()
        self.connected = False
        self.connection_state_changed.emit(False)

        if self._edit_idle_timer.isActive():
            self._edit_idle_timer.stop()

        # 创建新的线程和工作对象
        ssh_thread = QThread(self)
        port = int(self.ssh_port.text() or 22)
        use_key = self.use_key_cb.isChecked()
        key_file = self.key_file_input.text().strip() if use_key else ""
        pwd = "" if use_key else self.ssh_pwd.text()
        ssh_worker = SSHWorker(
            self.server_ip.text(), port, self.ssh_user.text(), pwd,
            key_file=key_file,
        )
        ssh_worker.moveToThread(ssh_thread)

        # 连接信号
        ssh_thread.started.connect(ssh_worker.run)
        ssh_worker.finished.connect(self._on_connect_finished)
        ssh_worker.step_updated.connect(self._on_step_updated)
        ssh_worker.error_detail.connect(self._on_error_detail)

        # 清理：finished → 先停线程 → 线程结束后再删 worker 和 thread
        ssh_worker.finished.connect(ssh_thread.quit)
        ssh_thread.finished.connect(ssh_worker.deleteLater)
        ssh_thread.finished.connect(ssh_thread.deleteLater)
        ssh_thread.start()

        self._temp_thread = ssh_thread
        self._temp_worker = ssh_worker

    def _on_step_updated(self, index: int, status: str) -> None:
        self.step_indicator.set_step(index, status)

    def _on_error_detail(self, detail: str) -> None:
        self.error_detail_label.setText(detail)
        self.error_detail_label.show()

    def _on_connect_finished(self, success: bool, msg: str, client: object) -> None:
        self._connecting = False
        self.status_label.setText(msg)

        if hasattr(self, '_temp_thread'):
            delattr(self, '_temp_thread')
        if hasattr(self, '_temp_worker'):
            delattr(self, '_temp_worker')

        if success:
            self.active_client = client
            self.status_label.setStyleSheet(STATUS_SUCCESS)
            self.error_detail_label.hide()
            self.last_stable_config = {
                'ip': self.server_ip.text(),
                'port': int(self.ssh_port.text() or 22),
                'user': self.ssh_user.text(),
                'pwd': self.ssh_pwd.text(),
                'use_key': self.use_key_cb.isChecked(),
                'key_file': self.key_file_input.text(),
            }
            self.connected = True
            self.connection_state_changed.emit(True)
            self._lock_inputs()
            self.revert_btn.hide()
            QTimer.singleShot(1500, self._auto_fold)
        else:
            self.status_label.setStyleSheet(STATUS_ERROR)
            self.connected = False
            self.connection_state_changed.emit(False)
            self._validate_inputs()
            if self.last_stable_config:
                self.revert_btn.show()
        self._refresh_interaction_state()

    def _revert_to_last_stable(self) -> None:
        if not self.last_stable_config:
            return
        self.server_ip.setText(self.last_stable_config.get('ip', ''))
        self.ssh_port.setText(str(self.last_stable_config.get('port', 22)))
        self.ssh_user.setText(self.last_stable_config.get('user', ''))
        self.ssh_pwd.setText(self.last_stable_config.get('pwd', ''))
        self.use_key_cb.setChecked(self.last_stable_config.get('use_key', False))
        self.key_file_input.setText(self.last_stable_config.get('key_file', ''))
        self.revert_btn.hide()

    def _on_diagnose(self) -> None:
        """打开诊断对话框。"""
        ip = self.server_ip.text().strip()
        port_str = self.ssh_port.text().strip()
        user = self.ssh_user.text().strip()
        pwd = self.ssh_pwd.text().strip()
        use_key = self.use_key_cb.isChecked()
        key_file = self.key_file_input.text().strip() if use_key else ""

        try:
            port = int(port_str)
        except (ValueError, TypeError):
            port = 22

        dlg = SSHDiagnosticDialog(
            ip or "0.0.0.0", port, user or "unknown", pwd,
            key_file=key_file, parent=self
        )
        dlg.exec()

    def _check_ssh_health(self) -> None:
        if self._connecting:
            return

        client = self.active_client
        if not client:
            return

        try:
            t = client.get_transport()
            ok = (t is not None) and t.is_active()
        except Exception:
            ok = False

        if ok:
            return

        try:
            client.close()
        except Exception:
            pass
        self.active_client = None

        if self.connected:
            self.connected = False
            self.connection_state_changed.emit(False)

            self.status_label.setStyleSheet(STATUS_ERROR)
            self.status_label.setText("连接已断开，正在重连…")

            # 使用 last_stable_config 直接重连，不依赖表单和按钮状态
            if self.last_stable_config:
                self._reconnect_from_stable_config()
            else:
                # 没有保存的配置，回退到编辑模式让用户手动处理
                self._in_edit_mode = True
                self._refresh_interaction_state()

    def _reconnect_from_stable_config(self) -> None:
        """使用 last_stable_config 保存的参数直接发起重连。"""
        if self._connecting or not self.last_stable_config:
            return

        cfg = self.last_stable_config
        self._connecting = True
        self.connect_btn.setEnabled(False)
        self.error_detail_label.hide()
        self.step_indicator.reset()
        self.step_indicator.show()

        if self._edit_idle_timer.isActive():
            self._edit_idle_timer.stop()

        ssh_thread = QThread(self)
        use_key = cfg.get('use_key', False)
        key_file = cfg.get('key_file', '') if use_key else ''
        pwd = '' if use_key else cfg.get('pwd', '')
        ssh_worker = SSHWorker(
            cfg.get('ip', ''), cfg.get('port', 22),
            cfg.get('user', ''), pwd, key_file=key_file,
        )
        ssh_worker.moveToThread(ssh_thread)

        ssh_thread.started.connect(ssh_worker.run)
        ssh_worker.finished.connect(self._on_connect_finished)
        ssh_worker.step_updated.connect(self._on_step_updated)
        ssh_worker.error_detail.connect(self._on_error_detail)
        ssh_worker.finished.connect(ssh_thread.quit)
        ssh_thread.finished.connect(ssh_worker.deleteLater)
        ssh_thread.finished.connect(ssh_thread.deleteLater)
        ssh_thread.start()

        self._temp_thread = ssh_thread
        self._temp_worker = ssh_worker

    def _refresh_interaction_state(self) -> None:
        if self._external_lock:
            for w in [self.server_ip, self.ssh_port, self.ssh_user, self.ssh_pwd,
                       self.connect_btn, self.modify_link, self.revert_btn,
                       self.key_file_input, self.browse_key_btn, self.use_key_cb]:
                w.setEnabled(False)
            return

        self.modify_link.setEnabled(True)
        self.diagnose_btn.setEnabled(True)
        if self._in_edit_mode:
            for w in [self.server_ip, self.ssh_port, self.ssh_user, self.ssh_pwd,
                       self.key_file_input, self.browse_key_btn, self.use_key_cb]:
                w.setEnabled(True)
            self._validate_inputs()
        else:
            for w in [self.server_ip, self.ssh_port, self.ssh_user, self.ssh_pwd,
                       self.connect_btn, self.key_file_input, self.browse_key_btn, self.use_key_cb]:
                w.setEnabled(False)

        if self._connecting:
            self.connect_btn.setEnabled(False)
        if self.revert_btn.isVisible():
            self.revert_btn.setEnabled(True)
