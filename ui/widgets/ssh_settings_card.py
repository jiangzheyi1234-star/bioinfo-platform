from __future__ import annotations

import os
import socket
import sys
import time
from typing import Protocol, Callable, Optional

import paramiko
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject, pyqtSlot
from PyQt6.QtWidgets import QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from core.remote.ssh_connector import classify_ssh_error, ssh_connect, diagnose_to_text
from ui.widgets.ssh_settings_components import ClickableHeader, SSHDiagnosticDialog, StepIndicator
from ui.widgets.styles import (
    CARD_FRAME,
    INPUT_LINEEDIT,
    BUTTON_PRIMARY,
    BUTTON_SECONDARY,
    BUTTON_LINK,
    BUTTON_DANGER,
    CARD_TITLE,
    COLOR_DANGER,
    COLOR_TEXT_HINT,
    COLOR_TEXT_SUB,
    COLOR_SUCCESS,
    COLOR_BG_BLANK,
    COLOR_BG_CARD,
    COLOR_BORDER_INPUT,
    RADIUS_CTRL,
    STATUS_NEUTRAL,
    STATUS_SUCCESS,
    STATUS_ERROR,
)

def _is_test_mode() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules)


class _FinishedSignal(Protocol):
    def connect(self, slot: Callable[[bool, str, object], None]) -> None: ...
    def emit(self, ok: bool, msg: str, client: object) -> None: ...


class _NoArgSignal(Protocol):
    def connect(self, slot: Callable[[], None]) -> None: ...
    def emit(self) -> None: ...


class SSHWorker(QObject):
    """后台连接工作线程，分步骤汇报进度。

    薄壳层：仅负责信号转发，后端逻辑委托给 ssh_connector.ssh_connect()。
    """

    finished: _FinishedSignal = pyqtSignal(bool, str, object)
    step_updated = pyqtSignal(int, str)
    error_detail = pyqtSignal(str)

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
            try:
                self.error_detail.emit(f"未知错误 — {e}")
            except Exception:
                pass
            try:
                self.finished.emit(False, "连接失败", None)
            except Exception:
                pass

    def _do_connect(self):
        self.step_updated.emit(0, "running")
        try:
            import socket as _socket
            sock = _socket.create_connection((self.ip, self.port), timeout=5)
            sock.close()
        except Exception as e:
            self.step_updated.emit(0, "fail")
            self.error_detail.emit(classify_ssh_error(e))
            self.finished.emit(False, "连接失败", None)
            return
        self.step_updated.emit(0, "ok")

        self.step_updated.emit(1, "running")
        result = ssh_connect(
            ip=self.ip,
            port=self.port,
            user=self.user,
            password="" if self.key_file else self.pwd,
            key_file=self.key_file,
        )

        if not result.ok:
            if "认证失败" in result.message:
                self.step_updated.emit(1, "ok")
                self.step_updated.emit(2, "fail")
            else:
                self.step_updated.emit(1, "fail")
            self.error_detail.emit(result.message)
            self.finished.emit(False, result.message, None)
            return

        self.step_updated.emit(1, "ok")
        self.step_updated.emit(2, "ok")
        self.finished.emit(True, "连接成功", result.client)


class SshSettingsCard(QFrame):
    """SSH 设置卡片组件。

    Contract:
      - set_values()/get_values()：与 SettingsPage 做配置同步。
      - get_active_client()：对外提供可复用的 SSHClient（可能为 None）。
      - request_save：当卡片内发生"需要保存"的动作时发出。
    """

    request_save = pyqtSignal()
    connection_state_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SSHCard")

        self.active_client = None
        self.last_stable_config = None
        self.connected = False
        self._connecting = False
        self._diagnose_active = False
        self._in_edit_mode = False
        self._external_lock = False
        self._status_cache: Optional[tuple[str, str]] = None
        self._auto_connect_armed = False
        self._last_connect_started_at = 0.0

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

        can_auto_connect_from_saved = bool(server_ip and (ssh_pwd or key_file))

        if can_auto_connect_from_saved:
            self.last_stable_config = {
                'ip': server_ip, 'port': ssh_port or 22,
                'user': ssh_user, 'pwd': ssh_pwd,
                'use_key': use_key, 'key_file': key_file,
            }
            self._lock_inputs()
            self._auto_connect_armed = not _is_test_mode()
            if self._auto_connect_armed:
                QTimer.singleShot(1000, self._consume_auto_connect)
        else:
            self._auto_connect_armed = False
            self._enable_editing()

    def _consume_auto_connect(self) -> None:
        """Consume a single startup auto-connect trigger.

        Both SettingsPage and this card may schedule startup checks; this gate
        guarantees only one connect attempt is started.
        """
        if not self._auto_connect_armed:
            return
        if _is_test_mode():
            self._auto_connect_armed = False
            return
        self._auto_connect_armed = False
        self.try_auto_connect()

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
        if _is_test_mode():
            self._auto_connect_armed = False
            return
        if self._auto_connect_armed:
            self._consume_auto_connect()
            return
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
        self.ssh_title.setCursor(Qt.CursorShape.PointingHandCursor)

        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 12px; border: none; background: transparent;")
        self.arrow_label.setCursor(Qt.CursorShape.PointingHandCursor)

        self.modify_link = QPushButton("修改")
        self.modify_link.setMinimumWidth(60)
        self.modify_link.setStyleSheet(BUTTON_LINK)
        self.modify_link.setCursor(Qt.CursorShape.PointingHandCursor)
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

        self.use_key_cb = QCheckBox("使用密钥文件认证")
        self.use_key_cb.setStyleSheet(f"color: {COLOR_TEXT_SUB}; font-size: 12px; background: transparent;")
        self.use_key_cb.toggled.connect(self._toggle_auth_mode)

        self.pwd_label = QLabel("SSH 密码")
        form.addRow(self.pwd_label, self.ssh_pwd)

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

        self.key_file_label.hide()
        self.key_file_row.hide()

        c_layout.addLayout(form)

        self.step_indicator = StepIndicator()
        self.step_indicator.hide()
        c_layout.addWidget(self.step_indicator)

        self.error_detail_label = QLabel()
        self.error_detail_label.setStyleSheet(
            f"color: {COLOR_DANGER}; font-size: 12px; background: transparent; padding: 4px 0;"
        )
        self.error_detail_label.setWordWrap(True)
        self.error_detail_label.hide()
        c_layout.addWidget(self.error_detail_label)

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

    def _disconnect_global_focus_listener(self) -> None:
        app = QApplication.instance()
        if app is not None and hasattr(app, "focusChanged"):
            try:
                app.focusChanged.disconnect(self._on_focus_changed)
            except (TypeError, RuntimeError):
                pass

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

    def _validate_inputs(self) -> None:
        import ipaddress

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
        now = time.monotonic()
        if now - self._last_connect_started_at < 1.0:
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
            self.status_label.setText("检测到重复连接触发，已忽略")
            return
        if self._ssh_thread is not None and self._ssh_thread.isRunning():
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
            self.status_label.setText("连接仍在进行，请稍候...")
            return

        if self.active_client is not None:
            try:
                self.active_client.close()
            except Exception:
                pass
            self.active_client = None

        self._connecting = True
        self._last_connect_started_at = now
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

        port = int(self.ssh_port.text() or 22)
        use_key = self.use_key_cb.isChecked()
        key_file = self.key_file_input.text().strip() if use_key else ""
        pwd = "" if use_key else self.ssh_pwd.text()
        ssh_worker = SSHWorker(
            self.server_ip.text(), port, self.ssh_user.text(), pwd,
            key_file=key_file,
        )
        self._start_ssh_worker(ssh_worker)

    def _start_ssh_worker(self, ssh_worker: SSHWorker) -> None:
        self._cleanup_ssh_worker(wait_ms=0)
        ssh_thread = QThread(self)
        self._ssh_thread = ssh_thread
        self._ssh_worker = ssh_worker
        ssh_worker.moveToThread(ssh_thread)
        ssh_thread.started.connect(ssh_worker.run)
        ssh_worker.finished.connect(self._on_connect_finished)
        ssh_worker.step_updated.connect(self._on_step_updated)
        ssh_worker.error_detail.connect(self._on_error_detail)
        ssh_worker.finished.connect(ssh_thread.quit)
        ssh_thread.finished.connect(ssh_worker.deleteLater)
        ssh_thread.finished.connect(self._on_ssh_thread_finished)
        ssh_thread.finished.connect(ssh_thread.deleteLater)
        ssh_thread.start()

    def _on_ssh_thread_finished(self) -> None:
        self._ssh_worker = None
        self._ssh_thread = None

    def _cleanup_ssh_worker(self, wait_ms: int = 1000) -> None:
        thread = self._ssh_thread
        if thread is not None and thread.isRunning():
            try:
                thread.quit()
                thread.wait(wait_ms)
            except Exception:
                pass
        # If thread already finished, release references immediately.
        if thread is None or not thread.isRunning():
            self._ssh_worker = None
            self._ssh_thread = None

    def _on_step_updated(self, index: int, status: str) -> None:
        self.step_indicator.set_step(index, status)

    def _on_error_detail(self, detail: str) -> None:
        self.error_detail_label.setText(detail)
        self.error_detail_label.show()

    def _on_connect_finished(self, success: bool, msg: str, client: object) -> None:
        self._connecting = False
        self.status_label.setText(msg)

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
            self.request_save.emit()
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
        if self._connecting or self._diagnose_active:
            self.status_label.setStyleSheet(STATUS_NEUTRAL)
            self.status_label.setText("诊断进行中或连接处理中，请稍后")
            return

        self._diagnose_active = True
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

        try:
            dlg = SSHDiagnosticDialog(
                ip or "0.0.0.0", port, user or "unknown", pwd,
                key_file=key_file, existing_client=self.active_client, parent=self
            )
            dlg.exec()
        finally:
            self._diagnose_active = False

    def _check_ssh_health(self) -> None:
        if self._connecting or self._diagnose_active:
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

            if self.last_stable_config:
                self._reconnect_from_stable_config()
            else:
                self._in_edit_mode = True
                self._refresh_interaction_state()

    def _reconnect_from_stable_config(self) -> None:
        if self._connecting or self._diagnose_active or not self.last_stable_config:
            return
        if self._ssh_thread is not None and self._ssh_thread.isRunning():
            return

        cfg = self.last_stable_config
        self._connecting = True
        self.connect_btn.setEnabled(False)
        self.error_detail_label.hide()
        self.step_indicator.reset()
        self.step_indicator.show()

        if self._edit_idle_timer.isActive():
            self._edit_idle_timer.stop()

        use_key = cfg.get('use_key', False)
        key_file = cfg.get('key_file', '') if use_key else ''
        pwd = '' if use_key else cfg.get('pwd', '')
        ssh_worker = SSHWorker(
            cfg.get('ip', ''), cfg.get('port', 22),
            cfg.get('user', ''), pwd, key_file=key_file,
        )
        self._start_ssh_worker(ssh_worker)

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

    def closeEvent(self, event) -> None:
        for timer in (self._auto_fold_timer, self._edit_idle_timer, self._ssh_health_timer):
            if timer.isActive():
                timer.stop()

        self._disconnect_global_focus_listener()
        self._cleanup_ssh_worker(wait_ms=3000)

        client = self.active_client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            self.active_client = None

        super().closeEvent(event)
