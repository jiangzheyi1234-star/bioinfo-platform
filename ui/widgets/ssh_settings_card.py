from __future__ import annotations

import ipaddress
from typing import Protocol, Callable, Optional

import paramiko
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import (
    CARD_FRAME,
    INPUT_LINEEDIT,
    BUTTON_PRIMARY,
    BUTTON_LINK,
    BUTTON_DANGER,
    CARD_TITLE,
    STATUS_NEUTRAL,
    STATUS_SUCCESS,
    STATUS_ERROR,
)


# ---- Typed signal Protocols for better IDE hints ----
class _FinishedSignal(Protocol):
    def connect(self, slot: Callable[[bool, str, object], None]) -> None: ...
    def emit(self, ok: bool, msg: str, client: object) -> None: ...


class _NoArgSignal(Protocol):
    def connect(self, slot: Callable[[], None]) -> None: ...
    def emit(self) -> None: ...


class SSHWorker(QObject):
    finished: _FinishedSignal = pyqtSignal(bool, str, object)

    def __init__(self, ip: str, user: str, pwd: str, parent=None):
        super().__init__(parent)
        self.ip, self.user, self.pwd = ip, user, pwd

    @pyqtSlot()
    def run(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(self.ip, port=22, username=self.user, password=self.pwd, timeout=2)
            client.get_transport().set_keepalive(30)
            self.finished.emit(True, "连接成功", client)
        except Exception:
            self.finished.emit(False, "连接失败", None)


class ClickableHeader(QFrame):
    clicked: _NoArgSignal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SshSettingsCard(QFrame):
    """SSH 设置卡片组件。

    Contract:
      - set_values()/get_values()：与 SettingsPage 做配置同步。
      - get_active_client()：对外提供可复用的 SSHClient（可能为 None）。
      - request_save：当卡片内发生“需要保存”的动作时发出（当前用于状态联动，可选）。
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
    def set_values(self, server_ip: str = "", ssh_user: str = "", ssh_pwd: str = "") -> None:
        self.server_ip.setText(str(server_ip or ""))
        self.ssh_user.setText(str(ssh_user or ""))
        self.ssh_pwd.setText(str(ssh_pwd or ""))

        self._validate_inputs()
        self._in_edit_mode = True
        
        if server_ip and ssh_pwd:
            self.last_stable_config = {'ip': server_ip, 'user': ssh_user, 'pwd': ssh_pwd}
            # 如果有有效的配置，进入锁定状态并显示修改按钮
            self._lock_inputs()
            QTimer.singleShot(1000, self.try_auto_connect)
        else:
            # 如果没有配置，保持编辑状态并显示修改按钮
            self._enable_editing()

    def get_values(self) -> dict:
        return {
            "server_ip": self.server_ip.text(),
            "ssh_user": self.ssh_user.text(),
            "ssh_pwd": self.ssh_pwd.text(),
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
        self.header_area.setStyleSheet(f"background: transparent; border: none;")
        self.header_area.clicked.connect(self._toggle_container)

        header_layout = QHBoxLayout(self.header_area)
        header_layout.setContentsMargins(20, 15, 20, 15)

        self.ssh_title = QLabel("Linux服务器SSH连接")
        self.ssh_title.setStyleSheet(CARD_TITLE)

        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet("color: #90adca; font-size: 12px; border: none; background: transparent;")

        self.modify_link = QPushButton("修改")
        self.modify_link.setFixedWidth(60)
        self.modify_link.setStyleSheet(BUTTON_LINK)
        self.modify_link.clicked.connect(self._enable_editing)
        # 修改按钮始终保持可见，不在初始化时隐藏

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

        self.server_ip = QLineEdit(); self.server_ip.setStyleSheet(INPUT_LINEEDIT)
        self.ssh_user = QLineEdit(); self.ssh_user.setStyleSheet(INPUT_LINEEDIT)
        self.ssh_pwd = QLineEdit(); self.ssh_pwd.setStyleSheet(INPUT_LINEEDIT)
        self.ssh_pwd.setEchoMode(QLineEdit.EchoMode.Password)

        for w in [self.server_ip, self.ssh_user, self.ssh_pwd]:
            w.textChanged.connect(lambda _text, _=w: self._on_edit_changed())

        form.addRow("服务器 IP", self.server_ip)
        form.addRow("用户名", self.ssh_user)
        form.addRow("SSH 密码", self.ssh_pwd)
        c_layout.addLayout(form)

        row = QHBoxLayout()
        self.connect_btn = QPushButton("连接并锁定")
        self.connect_btn.setFixedWidth(110)
        self.connect_btn.setEnabled(False)
        self.connect_btn.setStyleSheet(BUTTON_PRIMARY)
        self.connect_btn.clicked.connect(lambda checked=False: self._on_connect_ssh())

        self.status_label = QLabel("等待验证")
        self.status_label.setStyleSheet(STATUS_NEUTRAL)

        self.revert_btn = QPushButton("恢复上次成功")
        self.revert_btn.setStyleSheet(BUTTON_DANGER)
        self.revert_btn.clicked.connect(lambda checked=False: self._revert_to_last_stable())
        self.revert_btn.hide()

        row.addWidget(self.connect_btn)
        row.addWidget(self.status_label)
        row.addWidget(self.revert_btn)
        row.addRemember = row.addStretch  # keep compatibility with old style naming if referenced
        row.addStretch()
        c_layout.addLayout(row)

        main.addWidget(self.container)

    def _bind_global_focus_listener(self) -> None:
        app = QApplication.instance()
        if app is not None and hasattr(app, "focusChanged"):
            app.focusChanged.connect(self._on_focus_changed)

    # -------------------------
    # Behavior
    # -------------------------
    def _validate_inputs(self) -> None:
        ip = self.server_ip.text().strip()
        user = self.ssh_user.text().strip()
        pwd = self.ssh_pwd.text().strip()

        valid_ip = False
        try:
            if ip:
                ipaddress.ip_address(ip)
                valid_ip = True
        except Exception:
            valid_ip = False

        self.connect_btn.setEnabled(bool(ip and user and pwd and valid_ip))

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
            # 修改按钮始终保持可见，不需要在此处显式显示

    def _auto_fold_after_idle(self) -> None:
        if self.connected and (not self.server_ip.isEnabled()) and self.container.isVisible():
            self._auto_fold()

    def _auto_connect_after_edit_idle(self) -> None:
        if (not self._in_edit_mode) or (not self.connect_btn.isEnabled()):
            return
        self._on_connect_ssh()

    def _on_focus_changed(self, old, new) -> None:
        from PyQt6.QtWidgets import QApplication

        w = QApplication.focusWidget()
        watched = {
            self.server_ip,
            self.ssh_user,
            self.ssh_pwd,
            self.connect_btn,
            self.revert_btn,
            self.header_area,
            self.container,
        }

        if w in watched:
            if self._auto_fold_timer.isActive():
                self._auto_fold_timer.stop()
            return

        if self.connected and (not self.server_ip.isEnabled()) and self.container.isVisible():
            self._auto_fold_timer.start(10_000)

    def _lock_inputs(self) -> None:
        for w in [self.server_ip, self.ssh_user, self.ssh_pwd, self.connect_btn]:
            w.setEnabled(False)
        self._in_edit_mode = False
        self.modify_link.show()  # 修改按钮始终保持可见
        self.revert_btn.hide()  # 锁定时隐藏恢复按钮
        self._refresh_interaction_state()

    def _enable_editing(self) -> None:
        if self._external_lock:
            return
        self.container.show()
        self.arrow_label.setText("▲")
        for w in [self.server_ip, self.ssh_user, self.ssh_pwd]:
            w.setEnabled(True)
        self._in_edit_mode = True
        self.modify_link.show()  # 修改按钮始终保持可见，不隐藏
        self.revert_btn.hide()  # 编辑时隐藏恢复按钮
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
        self.status_label.setText("正在验证...")
        self.connected = False
        self.connection_state_changed.emit(False)

        if self._edit_idle_timer.isActive():
            self._edit_idle_timer.stop()

        # 创建新的线程和工作对象
        ssh_thread = QThread(self)
        ssh_worker = SSHWorker(self.server_ip.text(), self.ssh_user.text(), self.ssh_pwd.text())
        ssh_worker.moveToThread(ssh_thread)

        # 连接信号
        ssh_thread.started.connect(ssh_worker.run)
        ssh_worker.finished.connect(self._on_connect_finished)
        
        # 独立的清理函数
        def cleanup_resources():
            ssh_worker.deleteLater()
            ssh_thread.quit()
            ssh_thread.wait()
            ssh_thread.deleteLater()
        
        # 连接清理函数到finished信号
        ssh_worker.finished.connect(cleanup_resources)

        # 启动线程
        ssh_thread.start()
        
        # 临时存储引用以备不时之需
        self._temp_thread = ssh_thread
        self._temp_worker = ssh_worker

    def _on_connect_finished(self, success: bool, msg: str, client: object) -> None:
        self._connecting = False
        self.status_label.setText(msg)

        # 清理临时引用
        if hasattr(self, '_temp_thread'):
            delattr(self, '_temp_thread')
        if hasattr(self, '_temp_worker'):
            delattr(self, '_temp_worker')

        if success:
            self.active_client = client
            self.status_label.setStyleSheet(STATUS_SUCCESS)
            self.last_stable_config = {
                'ip': self.server_ip.text(),
                'user': self.ssh_user.text(),
                'pwd': self.ssh_pwd.text(),
            }
            self.connected = True
            self.connection_state_changed.emit(True)
            self._lock_inputs()
            self.revert_btn.hide()  # 连接成功后隐藏恢复按钮
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
        self.ssh_user.setText(self.last_stable_config.get('user', ''))
        self.ssh_pwd.setText(self.last_stable_config.get('pwd', ''))
        self.revert_btn.hide()

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

            self._in_edit_mode = True
            self._refresh_interaction_state()

            if self.connect_btn.isEnabled():
                self._on_connect_ssh()
            # 显示恢复按钮以便用户可以选择恢复到最后的稳定配置
            if self.last_stable_config:
                self.revert_btn.show()

    def _refresh_interaction_state(self) -> None:
        if self._external_lock:
            for w in [self.server_ip, self.ssh_user, self.ssh_pwd, self.connect_btn, self.modify_link, self.revert_btn]:
                w.setEnabled(False)
            return

        self.modify_link.setEnabled(True)
        if self._in_edit_mode:
            for w in [self.server_ip, self.ssh_user, self.ssh_pwd]:
                w.setEnabled(True)
            self._validate_inputs()
        else:
            for w in [self.server_ip, self.ssh_user, self.ssh_pwd, self.connect_btn]:
                w.setEnabled(False)

        if self._connecting:
            self.connect_btn.setEnabled(False)
        if self.revert_btn.isVisible():
            self.revert_btn.setEnabled(True)
