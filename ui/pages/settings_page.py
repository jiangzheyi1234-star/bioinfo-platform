import json
import os
import paramiko
import ipaddress
from typing import Protocol, Callable
from PyQt6.QtWidgets import (QFormLayout, QLineEdit, QPushButton, QHBoxLayout,
                             QLabel, QVBoxLayout, QFrame, QWidget, QApplication)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject, pyqtSlot
from ui.page_base import BasePage  #
from config import DEFAULT_CONFIG


# ---- Typed signal Protocols for better IDE hints ----
class _FinishedSignal(Protocol):
    def connect(self, slot: Callable[[bool, str, object], None]) -> None: ...
    def emit(self, ok: bool, msg: str, client: object) -> None: ...

class _NoArgSignal(Protocol):
    def connect(self, slot: Callable[[], None]) -> None: ...
    def emit(self) -> None: ...


# --- SSH 后台保持线程（Worker 模式） ---
class SSHWorker(QObject):
    finished: _FinishedSignal = pyqtSignal(bool, str, object)

    def __init__(self, ip, user, pwd, parent=None):
        super().__init__(parent)
        self.ip, self.user, self.pwd = ip, user, pwd

    @pyqtSlot()
    def run(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(self.ip, port=22, username=self.user, password=self.pwd, timeout=2)
            # 保持心跳包，确保连接不中断
            client.get_transport().set_keepalive(30)
            self.finished.emit(True, "连接成功", client)
        except Exception:
            self.finished.emit(False, "连接失败", None)


# --- 整行可点击的头部组件 ---
class ClickableHeader(QFrame):
    clicked: _NoArgSignal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # 设置手型光标，增强点击暗示
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SettingsPage(BasePage):
    def __init__(self):
        super().__init__("\u2699 \u8bbe\u7f6e")
        if hasattr(self, "label"):
            self.label.hide()

        self.active_client = None
        self.last_stable_config = None
        self.connected = False
        # 10秒离开卡片自动折叠
        self._auto_fold_timer = QTimer(self)
        self._auto_fold_timer.setSingleShot(True)
        getattr(self._auto_fold_timer, "timeout").connect(self._auto_fold_after_idle)
        # 新增：修改模式下20秒无操作自动重连定时器
        self._edit_idle_timer = QTimer(self)
        self._edit_idle_timer.setSingleShot(True)
        getattr(self._edit_idle_timer, "timeout").connect(self._auto_connect_after_edit_idle)
        # 是否处于“修改配置”模式
        self._in_edit_mode = False
        # NCBI 是否处于编辑模式
        self._ncbi_in_edit_mode = False

        # 线程句柄占位
        self._ssh_thread = None
        self._ssh_worker = None

        self.config_dir = os.path.join(os.getenv('APPDATA'), "H2OMeta")
        self.config_path = os.path.join(self.config_dir, "config.json")
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)

        # 页面整体背景：浅天蓝（蓝天感）
        self.setStyleSheet("background-color: #f4f9ff;")
        self.init_ui()
        self.load_config()

        # 启动即自动执行一次连接测试
        QTimer.singleShot(1000, self._auto_check_on_start)

        # 新增：SSH 健康检查定时器，尽量保持在线并自动重连
        self._ssh_health_timer = QTimer(self)
        self._ssh_health_timer.setInterval(15_000)
        getattr(self._ssh_health_timer, "timeout").connect(self._check_ssh_health)
        self._ssh_health_timer.start()

    def init_ui(self):
        """仅负责编排：标题 + 各卡片 + 保存区。"""
        self.layout.setContentsMargins(40, 30, 40, 30)
        self.layout.setSpacing(25)

        # 1. 页面大标题
        header_title = QLabel("系统设置")
        header_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a3a5a; background: transparent;")
        self.layout.addWidget(header_title)

        # 2. 卡片区
        self._init_ssh_card()
        self._init_ncbi_card()
        self._init_save_area()

        self.layout.addStretch()

    def _init_ssh_card(self):
        """封装原有 SSH 连接卡片 UI（保留自动折叠/健康检查相关控件与信号）。"""
        # 2. SSH 配置卡片 (外层纯白一体化设计)
        self.ssh_card = QFrame()
        self.ssh_card.setObjectName("SSHCard")
        self.ssh_card.setStyleSheet("""
            QFrame#SSHCard {
                background-color: #ffffff;
                border: 1px solid #e1eefb;
                border-radius: 12px;
            }
        """)
        ssh_main_layout = QVBoxLayout(self.ssh_card)
        ssh_main_layout.setContentsMargins(0, 0, 0, 0)

        # --- 卡片头部：全行可点击区域 ---
        self.header_area = ClickableHeader()
        self.header_area.setStyleSheet("background: transparent; border: none;")
        getattr(self.header_area, "clicked").connect(self._toggle_ssh_container)

        header_layout = QHBoxLayout(self.header_area)
        header_layout.setContentsMargins(20, 15, 20, 15)

        self.ssh_title = QLabel("Linux服务器SSH连接")
        self.ssh_title.setStyleSheet(
            "font-weight: 600; color: #4a6a8a; font-size: 14px; border: none; background: transparent;")

        # 状态指示箭头 (▲/▼)
        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet("color: #90adca; font-size: 12px; border: none; background: transparent;")

        # “修改”小链接：仅在连接成功锁定后显示；默认可输入时隐藏
        self.modify_link = QPushButton("修改")
        self.modify_link.setFixedWidth(40)
        self.modify_link.setStyleSheet(
            "color: #1890ff; border: none; background: transparent; font-size: 11px; text-decoration: underline;")
        getattr(self.modify_link, "clicked").connect(lambda checked=False: self._enable_ssh_editing())
        self.modify_link.hide()

        header_layout.addWidget(self.ssh_title)
        header_layout.addStretch()
        header_layout.addWidget(self.modify_link)
        header_layout.addWidget(self.arrow_label)
        ssh_main_layout.addWidget(self.header_area)

        # --- 配置输入区域 (背景透明，确保跟随卡片的白色) ---
        self.ssh_container = QWidget()
        self.ssh_container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(self.ssh_container)
        c_layout.setContentsMargins(20, 0, 20, 20)

        form = QFormLayout()
        form.setVerticalSpacing(15)

        # 输入框样式：浅蓝底 + 蓝色边框，Focus变亮
        self._input_style = """
            QLineEdit {
                padding: 10px; border: 1px solid #dcebfa; border-radius: 6px; 
                background-color: #fafcfe; color: #333;
            }
            QLineEdit:focus { border: 1px solid #1890ff; background-color: #ffffff; }
            QLineEdit:disabled { background-color: #f5f5f5; color: #bfbfbf; border: 1px solid #e8e8e8; }
        """

        self.server_ip = QLineEdit()
        self.ssh_user = QLineEdit()
        self.ssh_pwd = QLineEdit()
        self.ssh_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        for w in [self.server_ip, self.ssh_user, self.ssh_pwd]:
            w.setStyleSheet(self._input_style)
            getattr(w, "textChanged").connect(lambda _text, _=w: self._on_edit_changed())

        form.addRow("服务器 IP", self.server_ip)
        form.addRow("用户名", self.ssh_user)
        form.addRow("SSH 密码", self.ssh_pwd)
        c_layout.addLayout(form)

        # 操作行
        op_row = QHBoxLayout()
        self.connect_btn = QPushButton("连接并锁定")
        self.connect_btn.setFixedWidth(110)
        self.connect_btn.setEnabled(False)
        self.connect_btn.setStyleSheet("""
            QPushButton { background: #1890ff; color: white; border-radius: 6px; padding: 8px; font-weight: bold; border: none; }
            QPushButton:disabled { background: #bae7ff; color: #ffffff; }
        """)
        getattr(self.connect_btn, "clicked").connect(lambda checked=False: self._on_connect_ssh())

        self.status_label = QLabel("等待验证")
        self.status_label.setStyleSheet("color: #a0aec0; margin-left: 10px; background: transparent;")

        # 恢复成功配置按钮
        self.revert_btn = QPushButton("恢复上次成功")
        self.revert_btn.setStyleSheet(
            "color: #ff7875; border: none; background: transparent; font-size: 11px; text-decoration: underline;")
        getattr(self.revert_btn, "clicked").connect(lambda checked=False: self._revert_to_last_stable())
        self.revert_btn.hide()

        op_row.addWidget(self.connect_btn)
        op_row.addWidget(self.status_label)
        op_row.addWidget(self.revert_btn)
        op_row.addStretch()
        c_layout.addLayout(op_row)

        ssh_main_layout.addWidget(self.ssh_container)
        self.layout.addWidget(self.ssh_card)

        # 注册全局焦点变化监听（带保护，避免 IDE “未解析” 警告）
        app = QApplication.instance()
        if app is not None and hasattr(app, "focusChanged"):
            getattr(app, "focusChanged").connect(self._on_focus_changed)

    def _init_ncbi_card(self):
        """新增：NCBI API Key 卡片（在 SSH 卡片下方）。"""
        self.ncbi_card = QFrame()
        self.ncbi_card.setObjectName("NCBICard")
        self.ncbi_card.setStyleSheet("""
            QFrame#NCBICard {
                background-color: #ffffff;
                border: 1px solid #e1eefb;
                border-radius: 12px;
            }
        """)

        main_layout = QVBoxLayout(self.ncbi_card)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 头部：标题 + 修改/保存
        header = QFrame()
        header.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 15, 20, 10)

        title = QLabel("NCBI 服务配置")
        title.setStyleSheet("font-weight: 600; color: #4a6a8a; font-size: 14px; background: transparent;")

        self.ncbi_modify_btn = QPushButton("修改")
        self.ncbi_modify_btn.setFixedWidth(40)
        self.ncbi_modify_btn.setStyleSheet(
            "color: #1890ff; border: none; background: transparent; font-size: 11px; text-decoration: underline;")
        getattr(self.ncbi_modify_btn, "clicked").connect(lambda checked=False: self._enable_ncbi_editing())

        self.ncbi_save_btn = QPushButton("保存")
        self.ncbi_save_btn.setFixedWidth(40)
        self.ncbi_save_btn.setStyleSheet(
            "color: #52c41a; border: none; background: transparent; font-size: 11px; text-decoration: underline;")
        getattr(self.ncbi_save_btn, "clicked").connect(lambda checked=False: self._save_ncbi_config())
        self.ncbi_save_btn.hide()

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.ncbi_modify_btn)
        header_layout.addWidget(self.ncbi_save_btn)
        main_layout.addWidget(header)

        # 内容区
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(20, 0, 20, 20)
        content_layout.setSpacing(12)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        self.ncbi_api_key = QLineEdit()
        self.ncbi_api_key.setStyleSheet(getattr(self, "_input_style", ""))
        self.ncbi_api_key.setPlaceholderText("可选：填写 NCBI API Key")

        label = QLabel("NCBI API Key")
        label.setStyleSheet("color: #4a6a8a; font-size: 12px; background: transparent;")
        form.addRow(label, self.ncbi_api_key)
        content_layout.addLayout(form)


        # 状态提示
        self.ncbi_status_label = QLabel("")
        self.ncbi_status_label.setStyleSheet("color: #a0aec0; font-size: 11px; background: transparent;")
        content_layout.addWidget(self.ncbi_status_label)

        main_layout.addWidget(content)
        self.layout.addWidget(self.ncbi_card)

        # 默认锁定
        self._lock_ncbi_inputs()

    def _lock_ncbi_inputs(self):
        """锁定 NCBI 卡片输入（已有 key 时使用）。"""
        if hasattr(self, "ncbi_api_key"):
            self.ncbi_api_key.setEnabled(False)
        self._ncbi_in_edit_mode = False
        if hasattr(self, "ncbi_modify_btn"):
            self.ncbi_modify_btn.show()
        if hasattr(self, "ncbi_save_btn"):
            self.ncbi_save_btn.hide()

    def _unlock_ncbi_inputs(self):
        """解锁 NCBI 卡片输入（key 为空/缺失时默认使用）。"""
        if hasattr(self, "ncbi_api_key"):
            self.ncbi_api_key.setEnabled(True)
        self._ncbi_in_edit_mode = True
        if hasattr(self, "ncbi_modify_btn"):
            self.ncbi_modify_btn.hide()
        if hasattr(self, "ncbi_save_btn"):
            self.ncbi_save_btn.show()
        if hasattr(self, "ncbi_status_label"):
            self.ncbi_status_label.setText("")

    def _enable_ncbi_editing(self):
        """进入 NCBI 编辑模式。"""
        self._unlock_ncbi_inputs()

    def _save_ncbi_config(self):
        """仅保存 NCBI 配置到 config.json，并按内容决定锁定/解锁。"""
        data = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    old = json.load(f)
                if isinstance(old, dict):
                    data.update(old)
            except Exception:
                data = {}

        key = self.ncbi_api_key.text().strip()
        data["ncbi_api_key"] = key

        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 用户说不需要提示：这里不再设置“已保存”文字
        if hasattr(self, "ncbi_status_label"):
            self.ncbi_status_label.setText("")

        # 保存后：有值就锁定；空值保持可编辑
        if key:
            self._lock_ncbi_inputs()
        else:
            self._unlock_ncbi_inputs()

    def save_config(self):
        data = {
            "server_ip": self.server_ip.text(),
            "ssh_user": self.ssh_user.text(),
            "ssh_pwd": self.ssh_pwd.text(),
            "ncbi_api_key": self.ncbi_api_key.text().strip(),
        }
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.status_label.setText("设置已保存")
        # 保存全部后：同样按 ncbi key 是否为空决定锁定/解锁
        key = self.ncbi_api_key.text().strip()
        if key:
            self._lock_ncbi_inputs()
        else:
            self._unlock_ncbi_inputs()

    def load_config(self):
        # 兜底：先用全局默认配置（兼容旧 config.json 缺少字段）
        merged = {
            "server_ip": DEFAULT_CONFIG.get("ip", ""),
            "ssh_user": DEFAULT_CONFIG.get("user", ""),
            "ssh_pwd": DEFAULT_CONFIG.get("pwd", ""),
            "ncbi_api_key": DEFAULT_CONFIG.get("ncbi_api_key", ""),
        }

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    merged.update({k: v for k, v in data.items() if v is not None})
            except Exception:
                pass

        self.server_ip.setText(str(merged.get("server_ip", "") or ""))
        self.ssh_user.setText(str(merged.get("ssh_user", "") or ""))
        self.ssh_pwd.setText(str(merged.get("ssh_pwd", "") or ""))
        self.ncbi_api_key.setText(str(merged.get("ncbi_api_key", "") or ""))

        # 加载完：SSH 默认保持可输入（不锁定）；NCBI 根据 key 是否为空决定锁定/解锁
        self._validate_inputs()
        self._in_edit_mode = True
        self.modify_link.hide()

        ncbi_key = (merged.get("ncbi_api_key") or "").strip() if isinstance(merged.get("ncbi_api_key"), str) or merged.get("ncbi_api_key") is None else str(merged.get("ncbi_api_key")).strip()
        if ncbi_key:
            self._lock_ncbi_inputs()
        else:
            self._unlock_ncbi_inputs()

        # 加载完毕后：自动尝试连接（若有有效 IP 和密码）
        if merged.get("server_ip") and merged.get("ssh_pwd"):
            self.last_stable_config = {
                'ip': merged.get('server_ip', ''),
                'user': merged.get('ssh_user', ''),
                'pwd': merged.get('ssh_pwd', ''),
            }
            # 直接连接（不弹窗）
            QTimer.singleShot(1000, self._try_auto_connect)

    def _try_auto_connect(self):
        """尝试自动连接至上次成功的 SSH 目标（无弹窗提示）。"""
        if not self.connect_btn.isEnabled():
            return
        self._on_connect_ssh()

    def _auto_check_on_start(self):
        if self.connect_btn.isEnabled():
            self._on_connect_ssh()

    # 新增：SSH 健康检查逻辑
    def _check_ssh_health(self):
        """每 15s 检查一次当前 SSH 连接状态，断开则更新 UI 并尝试重连。"""
        client = self.active_client
        if not client:
            return
        ok = False
        try:
            t = client.get_transport()
            ok = (t is not None) and t.is_active()
        except Exception:
            ok = False

        if ok:
            return

        # 标记断开并清理旧 client
        try:
            client.close()
        except Exception:
            pass
        self.active_client = None

        # 仅在此前处于连接状态时更新 UI 并尝试重连
        if self.connected:
            self.connected = False
            # UI 提示断开与重连中
            self.status_label.setStyleSheet("color: #ff4d4f; background: transparent;")
            self.status_label.setText("连接已断开，正在重连…")
            # 允许重新连接
            for w in [self.server_ip, self.ssh_user, self.ssh_pwd, self.connect_btn]:
                w.setEnabled(True)
            self._validate_inputs()
            # 避免与正在验证的流程重叠
            if self.connect_btn.isEnabled() and self.status_label.text() != "正在验证...":
                self._on_connect_ssh()

    def get_active_client(self):
        """提供当前活跃的 SSHClient（可能为 None）。"""
        return self.active_client

    def _init_save_area(self):
        """封装底部保存区域。"""
        self.save_btn = QPushButton("保存全部设置")
        self.save_btn.setStyleSheet(
            "background: #52c41a; color: white; border-radius: 6px; padding: 10px 20px; font-weight: bold; border: none;")
        getattr(self.save_btn, "clicked").connect(self.save_config)
        self.layout.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignRight)

    # ------------ SSH 卡片：只影响 SSH QFrame 的锁定/修改 ------------
    def _lock_ssh_inputs(self):
        """仅在 SSH 连接成功后锁定输入。"""
        for w in [self.server_ip, self.ssh_user, self.ssh_pwd, self.connect_btn]:
            w.setEnabled(False)
        self._in_edit_mode = False
        self.modify_link.show()

    def _enable_ssh_editing(self):
        """点击 SSH 卡片的“修改”，重新解锁 SSH 输入（只影响 SSH 卡片）。"""
        self.ssh_container.show()
        self.arrow_label.setText("▲")
        for w in [self.server_ip, self.ssh_user, self.ssh_pwd]:
            w.setEnabled(True)
        # 解锁后按钮是否可用由校验决定
        self._in_edit_mode = True
        self.modify_link.hide()
        self._validate_inputs()
        # 解锁后启动 20s 自动连接（若输入合法）
        self._on_edit_changed()

    def _validate_inputs(self):
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

    def _on_edit_changed(self):
        self._validate_inputs()
        if self._in_edit_mode:
            if self._edit_idle_timer.isActive():
                self._edit_idle_timer.stop()
            if self.connect_btn.isEnabled():
                self._edit_idle_timer.start(20_000)

    def _toggle_ssh_container(self):
        # 连接中禁止折叠
        if not self.connect_btn.isEnabled() and self.status_label.text() == "正在验证...":
            return
        v = self.ssh_container.isVisible()
        self.ssh_container.setVisible(not v)
        self.arrow_label.setText("▲" if not v else "▼")
        if self._auto_fold_timer.isActive():
            self._auto_fold_timer.stop()

    def _auto_fold(self):
        if not self.server_ip.isEnabled():
            self.ssh_container.hide()
            self.arrow_label.setText("▼")
            self.modify_link.show()

    def _auto_fold_after_idle(self):
        if self.connected and not self.server_ip.isEnabled() and self.ssh_container.isVisible():
            self._auto_fold()

    def _auto_connect_after_edit_idle(self):
        if not self._in_edit_mode or not self.connect_btn.isEnabled():
            return
        self._on_connect_ssh()

    def _on_focus_changed(self, old, new):
        from PyQt6.QtWidgets import QApplication
        w = QApplication.focusWidget()

        ssh_widgets = {
            self.server_ip,
            self.ssh_user,
            self.ssh_pwd,
            self.connect_btn,
            self.revert_btn,
            self.header_area,
            self.ssh_container,
        }

        if w in ssh_widgets:
            if self._auto_fold_timer.isActive():
                self._auto_fold_timer.stop()
            return

        if self.connected and not self.server_ip.isEnabled() and self.ssh_container.isVisible():
            self._auto_fold_timer.start(10_000)

    def _on_connect_ssh(self):
        self.connect_btn.setEnabled(False)
        self.status_label.setStyleSheet("color: #a0aec0; margin-left: 10px; background: transparent;")
        self.status_label.setText("正在验证...")
        self.connected = False

        if self._edit_idle_timer.isActive():
            self._edit_idle_timer.stop()

        self._ssh_thread = QThread(self)
        self._ssh_worker = SSHWorker(self.server_ip.text(), self.ssh_user.text(), self.ssh_pwd.text())
        self._ssh_worker.moveToThread(self._ssh_thread)
        getattr(self._ssh_thread, "started").connect(self._ssh_worker.run)
        self._ssh_worker.finished.connect(self._on_connect_finished)
        self._ssh_worker.finished.connect(lambda ok, msg, client: self._ssh_thread.quit())
        self._ssh_worker.finished.connect(lambda ok, msg, client: self._ssh_worker.deleteLater())
        getattr(self._ssh_thread, "finished").connect(self._ssh_thread.deleteLater)
        self._ssh_thread.start()

    def _on_connect_finished(self, success, msg, client):
        self.status_label.setText(msg)
        if success:
            self.active_client = client
            self.status_label.setStyleSheet("color: #52c41a; background: transparent;")
            self.last_stable_config = {
                'ip': self.server_ip.text(),
                'user': self.ssh_user.text(),
                'pwd': self.ssh_pwd.text(),
            }
            self.connected = True
            # 只锁定 SSH 卡片
            self._lock_ssh_inputs()
            QTimer.singleShot(1500, self._auto_fold)
        else:
            self.status_label.setStyleSheet("color: #ff4d4f; background: transparent;")
            self.connected = False
            self._validate_inputs()
            if self.last_stable_config:
                self.revert_btn.show()

    def _revert_to_last_stable(self):
        if self.last_stable_config:
            self.server_ip.setText(self.last_stable_config['ip'])
            self.ssh_user.setText(self.last_stable_config['user'])
            self.ssh_pwd.setText(self.last_stable_config['pwd'])
            self.revert_btn.hide()
