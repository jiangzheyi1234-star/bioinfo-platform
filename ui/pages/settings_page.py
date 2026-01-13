import json
import os
import paramiko
import ipaddress
from PyQt6.QtWidgets import (QFormLayout, QLineEdit, QPushButton, QHBoxLayout,
                             QLabel, QVBoxLayout, QFrame, QWidget, QApplication)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from ui.page_base import BasePage  #


# --- SSH 后台保持线程 ---
class SSHWorker(QThread):
    finished = pyqtSignal(bool, str, object)

    def __init__(self, ip, user, pwd):
        super().__init__()
        self.ip, self.user, self.pwd = ip, user, pwd

    def run(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(self.ip, port=22, username=self.user, password=self.pwd, timeout=2)
            # 保持心跳包，确保连接不中断
            client.get_transport().set_keepalive(30)
            self.finished.emit(True, "连接成功", client)
        except:
            self.finished.emit(False, "连接失败", None)


# --- 整行可点击的头部组件 ---
class ClickableHeader(QFrame):
    clicked = pyqtSignal()

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
        super().__init__("⚙ 设置")
        if hasattr(self, "label"): self.label.hide()

        self.active_client = None
        self.last_stable_config = None
        self.connected = False
        # 10秒离开卡片自动折叠
        self._auto_fold_timer = QTimer(self)
        self._auto_fold_timer.setSingleShot(True)
        self._auto_fold_timer.timeout.connect(self._auto_fold_after_idle)
        # 新增：修改模式下20秒无操作自动重连定时器
        self._edit_idle_timer = QTimer(self)
        self._edit_idle_timer.setSingleShot(True)
        self._edit_idle_timer.timeout.connect(self._auto_connect_after_edit_idle)
        # 是否处于“修改配置”模式
        self._in_edit_mode = False

        self.config_dir = os.path.join(os.getenv('APPDATA'), "H2OMeta")
        self.config_path = os.path.join(self.config_dir, "config.json")
        if not os.path.exists(self.config_dir): os.makedirs(self.config_dir)

        # 页面整体背景：浅天蓝（蓝天感）
        self.setStyleSheet("background-color: #f4f9ff;")
        self.init_ui()
        self.load_config()

        # 启动即自动执行一次连接测试
        QTimer.singleShot(1000, self._auto_check_on_start)

    def init_ui(self):
        self.layout.setContentsMargins(40, 30, 40, 30)
        self.layout.setSpacing(25)

        # 1. 页面大标题
        header_title = QLabel("系统设置")
        header_title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a3a5a; background: transparent;")
        self.layout.addWidget(header_title)

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
        ssh_main_layout.setContentsMargins(0, 0, 0, 0)  # 间距设为0，确保头部点击区域覆盖整行

        # --- 卡片头部：全行可点击区域 ---
        self.header_area = ClickableHeader()
        self.header_area.setStyleSheet("background: transparent; border: none;")
        self.header_area.clicked.connect(self._toggle_ssh_container)

        header_layout = QHBoxLayout(self.header_area)
        header_layout.setContentsMargins(20, 15, 20, 15)

        self.ssh_title = QLabel("Linux服务器SSH连接")
        self.ssh_title.setStyleSheet(
            "font-weight: 600; color: #4a6a8a; font-size: 14px; border: none; background: transparent;")

        # 状态指示箭头 (▲/▼)
        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet("color: #90adca; font-size: 12px; border: none; background: transparent;")

        # “修改”小链接
        self.modify_link = QPushButton("修改")
        self.modify_link.setFixedWidth(40)
        self.modify_link.setStyleSheet(
            "color: #1890ff; border: none; background: transparent; font-size: 11px; text-decoration: underline;")
        self.modify_link.clicked.connect(self._enable_editing)
        self.modify_link.hide()

        header_layout.addWidget(self.ssh_title);
        header_layout.addStretch()
        header_layout.addWidget(self.modify_link);
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
        input_style = """
            QLineEdit {
                padding: 10px; border: 1px solid #dcebfa; border-radius: 6px; 
                background-color: #fafcfe; color: #333;
            }
            QLineEdit:focus { border: 1px solid #1890ff; background-color: #ffffff; }
            QLineEdit:disabled { background-color: #f5f5f5; color: #bfbfbf; border: 1px solid #e8e8e8; }
        """
        self.server_ip = QLineEdit();
        self.ssh_user = QLineEdit();
        self.ssh_pwd = QLineEdit()
        self.ssh_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        for w in [self.server_ip, self.ssh_user, self.ssh_pwd]:
            w.setStyleSheet(input_style);
            w.textChanged.connect(self._on_edit_changed)
            # 简化：不再覆盖 focusInEvent / focusOutEvent，由全局焦点变化统一处理

        form.addRow("服务器 IP", self.server_ip)
        form.addRow("用户名", self.ssh_user)
        form.addRow("SSH 密码", self.ssh_pwd)
        c_layout.addLayout(form)

        # 操作行
        op_row = QHBoxLayout()
        self.connect_btn = QPushButton("连接并锁定")
        self.connect_btn.setFixedWidth(110);
        self.connect_btn.setEnabled(False)
        self.connect_btn.setStyleSheet("""
            QPushButton { background: #1890ff; color: white; border-radius: 6px; padding: 8px; font-weight: bold; border: none; }
            QPushButton:disabled { background: #bae7ff; color: #ffffff; }
        """)
        self.connect_btn.clicked.connect(self._on_connect_ssh)

        self.status_label = QLabel("等待验证")
        self.status_label.setStyleSheet("color: #a0aec0; margin-left: 10px; background: transparent;")

        # 恢复成功配置按钮
        self.revert_btn = QPushButton("恢复上次成功")
        self.revert_btn.setStyleSheet(
            "color: #ff7875; border: none; background: transparent; font-size: 11px; text-decoration: underline;")
        self.revert_btn.clicked.connect(self._revert_to_last_stable);
        self.revert_btn.hide()

        op_row.addWidget(self.connect_btn);
        op_row.addWidget(self.status_label);
        op_row.addWidget(self.revert_btn);
        op_row.addStretch()
        c_layout.addLayout(op_row)

        ssh_main_layout.addWidget(self.ssh_container)
        self.layout.addWidget(self.ssh_card)

        # 注册全局焦点变化监听
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

        # 底部保存
        self.save_btn = QPushButton("保存全部设置")
        self.save_btn.setStyleSheet(
            "background: #52c41a; color: white; border-radius: 6px; padding: 10px 20px; font-weight: bold; border: none;")
        self.save_btn.clicked.connect(self.save_config)
        self.layout.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.layout.addStretch()

    # --- 逻辑实现 ---
    def _validate_inputs(self):
        ip, user, pwd = self.server_ip.text().strip(), self.ssh_user.text().strip(), self.ssh_pwd.text().strip()
        valid = False
        try:
            if ip: ipaddress.ip_address(ip); valid = True
        except:
            pass
        self.connect_btn.setEnabled(all([ip, user, pwd]) and valid)

    def _on_edit_changed(self):
        """任何编辑变更时：重新做输入校验，同时重置20秒自动连接计时。"""
        self._validate_inputs()
        # 只在编辑模式下才考虑自动连接
        if self._in_edit_mode:
            # 每次有输入，就重置20秒计时
            if self._edit_idle_timer.isActive():
                self._edit_idle_timer.stop()
            # 只有当按钮当前是可用（输入都合法）时，才启动自动连接等待
            if self.connect_btn.isEnabled():
                self._edit_idle_timer.start(20_000)

    def _on_connect_ssh(self):
        self.connect_btn.setEnabled(False);
        self.status_label.setText("正在验证...")
        # 连接过程中视为未稳定连接
        self.connected = False
        # 手动点击连接时，停止编辑自动连接计时
        if self._edit_idle_timer.isActive():
            self._edit_idle_timer.stop()
        self.worker = SSHWorker(self.server_ip.text(), self.ssh_user.text(), self.ssh_pwd.text())
        self.worker.finished.connect(self._on_connect_finished);
        self.worker.start()

    def _on_connect_finished(self, success, msg, client):
        self.status_label.setText(msg)
        if success:
            self.active_client = client;
            self.status_label.setStyleSheet("color: #52c41a; background: transparent;")
            self.last_stable_config = {'ip': self.server_ip.text(), 'user': self.ssh_user.text(),
                                       'pwd': self.ssh_pwd.text()}
            # 标记为已连接
            self.connected = True
            for w in [self.server_ip, self.ssh_user, self.ssh_pwd, self.connect_btn]: w.setEnabled(False)
            # 退出编辑模式
            self._in_edit_mode = False
            if self._edit_idle_timer.isActive():
                self._edit_idle_timer.stop()
            # 成功后延迟折叠
            QTimer.singleShot(1500, self._auto_fold)
        else:
            self.status_label.setStyleSheet("color: #ff4d4f; background: transparent;");
            # 失败视为未连接
            self.connected = False
            self._validate_inputs()
            if self.last_stable_config: self.revert_btn.show()

    def _auto_fold(self):
        if not self.server_ip.isEnabled():
            self.ssh_container.hide()
            self.arrow_label.setText("▼")
            self.modify_link.show()

    def _auto_fold_after_idle(self):
        """输入框等控件失焦后空闲 10 秒的自动折叠逻辑。"""
        if self.connected and not self.server_ip.isEnabled() and self.ssh_container.isVisible():
            self._auto_fold()

    def _toggle_ssh_container(self):
        # 保护逻辑：连接中禁止折叠
        if not self.connect_btn.isEnabled() and self.status_label.text() == "正在验证...":
            return
        v = self.ssh_container.isVisible()
        self.ssh_container.setVisible(not v)
        self.arrow_label.setText("▲" if not v else "▼")
        # 手动展开或折叠时，交给全局焦点监听决定是否计时，这里只需停止已有计时
        if self._auto_fold_timer.isActive():
            self._auto_fold_timer.stop()

    def _enable_editing(self):
        """点击“修改”进入编辑模式：解锁输入，并开始监听编辑20秒自动连接。"""
        self.ssh_container.show();
        self.arrow_label.setText("▲")
        for w in [self.server_ip, self.ssh_user, self.ssh_pwd, self.connect_btn]: w.setEnabled(True)
        self.modify_link.hide()
        # 进入编辑模式
        self._in_edit_mode = True
        # 当前输入若已合法，则开启20秒自动连接计时
        self._on_edit_changed()

    def _auto_connect_after_edit_idle(self):
        """处于修改模式下，20秒没有任何输入变更：如果当前输入合法，则自动尝试连接并锁定折叠。"""
        # 若已经离开编辑模式或按钮不可用，则放弃
        if not self._in_edit_mode or not self.connect_btn.isEnabled():
            return
        # 直接复用现有的连接逻辑
        self._on_connect_ssh()

    def _on_focus_changed(self, old, new):
        """全局焦点变化：当焦点离开 SSH 卡片内所有控件且当前已连接时，启动 10 秒折叠计时。"""
        from PyQt6.QtWidgets import QApplication  # 局部导入避免循环

        # 当前焦点控件
        w = QApplication.focusWidget()

        # SSH 卡片内控件集合：输入框、按钮等
        ssh_widgets = {
            self.server_ip,
            self.ssh_user,
            self.ssh_pwd,
            self.connect_btn,
            self.revert_btn,
            self.header_area,
            self.ssh_container,
        }

        # 如果当前焦点仍在 SSH 卡片内，则取消计时
        if w in ssh_widgets:
            if self._auto_fold_timer.isActive():
                self._auto_fold_timer.stop()
            return

        # 焦点离开 SSH 卡片：如果已连接且锁定且展开，则启动 10 秒计时
        if self.connected and not self.server_ip.isEnabled() and self.ssh_container.isVisible():
            self._auto_fold_timer.start(10_000)

    def _revert_to_last_stable(self):
        if self.last_stable_config:
            self.server_ip.setText(self.last_stable_config['ip']);
            self.ssh_user.setText(self.last_stable_config['user'])
            self.ssh_pwd.setText(self.last_stable_config['pwd']);
            self.revert_btn.hide()

    def save_config(self):
        data = {"server_ip": self.server_ip.text(), "ssh_user": self.ssh_user.text(), "ssh_pwd": self.ssh_pwd.text()}
        with open(self.config_path, 'w', encoding='utf-8') as f: json.dump(data, f)
        self.status_label.setText("设置已保存")

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.server_ip.setText(data.get("server_ip", ""));
                    self.ssh_user.setText(data.get("ssh_user", ""))
                    self.ssh_pwd.setText(data.get("ssh_pwd", ""));
                    self._validate_inputs()
                    if data.get("server_ip") and data.get("ssh_pwd"):
                        self.last_stable_config = {'ip': data['server_ip'], 'user': data['ssh_user'],
                                                   'pwd': data['ssh_pwd']}
            except:
                pass

    def _auto_check_on_start(self):
        if self.connect_btn.isEnabled(): self._on_connect_ssh()