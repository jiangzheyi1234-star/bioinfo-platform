# ui/widgets/blast_settings_card.py
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QLabel, QHBoxLayout
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot
from ui.widgets import styles
from config import DEFAULT_CONFIG
from core.ssh_service import SSHService


class VerifyWorker(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, client, path):
        super().__init__()
        self.client = client
        self.path = path

    @pyqtSlot()
    def run(self):
        try:
            # 兼容分卷数据库校验
            cmd = f"ls {self.path}*.nsq > /dev/null 2>&1 && echo 'OK'"
            ssh_service = SSHService(lambda: self.client)
            rc, out, _ = ssh_service.run(cmd, timeout=5)
            if rc == 0 and "OK" in out:
                self.finished.emit(True, "验证通过：数据库有效")
            else:
                self.finished.emit(False, "验证失败：未找到有效索引文件")
        except Exception as e:
            self.finished.emit(False, f"校验过程出错: {str(e)}")


class BlastSettingsCard(QFrame):
    def __init__(self, get_ssh_client_func, parent=None):
        super().__init__(parent)
        self.setObjectName("BlastCard")
        self.get_ssh_client = get_ssh_client_func
        self.setStyleSheet(styles.CARD_FRAME("BlastCard"))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)

        title = QLabel("BLAST 数据库设置")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        form = QFormLayout()
        self.db_path_input = QLineEdit()
        self.db_path_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self.db_path_input.setText(DEFAULT_CONFIG.get('remote_db', ''))
        form.addRow(QLabel("远程数据库路径:", styleSheet=styles.FORM_LABEL), self.db_path_input)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.verify_btn = QPushButton("验证路径")
        self.verify_btn.setStyleSheet(styles.BUTTON_PRIMARY) # 已包含 hover 逻辑
        self.verify_btn.setFixedWidth(100)
        self.verify_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.verify_btn.clicked.connect(self._start_verification)

        self.status_label = QLabel("等待验证")
        self.status_label.setStyleSheet(styles.STATUS_NEUTRAL)

        row.addWidget(self.verify_btn)
        row.addWidget(self.status_label)
        row.addStretch()
        layout.addLayout(row)

    def _start_verification(self):
        client = self.get_ssh_client()
        if not client:
            self.status_label.setText("请先在上方连接 SSH")
            self.status_label.setStyleSheet(styles.STATUS_ERROR)
            return

        # 锁定交互并显示 WaitCursor
        self._set_ui_locked(True)
        self.status_label.setText("正在连接服务器校验...")
        
        self._thread = QThread()
        self._worker = VerifyWorker(client, self.db_path_input.text().strip())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_verify_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_verify_finished(self, success, message):
        self._set_ui_locked(False)
        self.status_label.setText(message)
        self.status_label.setStyleSheet(styles.STATUS_SUCCESS if success else styles.STATUS_ERROR)

    def _set_ui_locked(self, locked: bool):
        """标准化锁定反馈"""
        self.verify_btn.setEnabled(not locked)
        self.db_path_input.setEnabled(not locked)
        if locked:
            self.verify_btn.setText("验证中...")
            self.setCursor(Qt.CursorShape.WaitCursor) # 鼠标变为忙碌状态
        else:
            self.verify_btn.setText("验证路径")
            self.unsetCursor() # 恢复默认光标

    def get_values(self):
        """提供给 SettingsPage 收集配置"""
        return {"remote_db": self.db_path_input.text()}

    def set_values(self, remote_db: str):
        """由 SettingsPage 加载配置"""
        self.db_path_input.setText(remote_db or "")