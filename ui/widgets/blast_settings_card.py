# ui/widgets/blast_settings_card.py
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QLabel, QHBoxLayout
from PyQt6.QtCore import pyqtSignal
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
    request_save = pyqtSignal()  # 新增信号，当用户点击保存按钮时发射
    def __init__(self, get_ssh_client_func, parent=None):
        super().__init__(parent)
        self.setObjectName("BlastCard")
        self.get_ssh_client = get_ssh_client_func
        self.setStyleSheet(styles.CARD_FRAME("BlastCard"))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)

        title = QLabel("BLAST 环境与路径设置")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        form = QFormLayout()
        
        # 1. BLAST 执行程序路径
        self.bin_path_input = QLineEdit()
        self.bin_path_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self.bin_path_input.setPlaceholderText("例如: /usr/bin/blastn")
        form.addRow(QLabel("BLAST 执行程序路径:", styleSheet=styles.FORM_LABEL), self.bin_path_input)

        # 2. 远程数据库路径
        self.db_path_input = QLineEdit()
        self.db_path_input.setStyleSheet(styles.INPUT_LINEEDIT)
        form.addRow(QLabel("远程数据库路径:", styleSheet=styles.FORM_LABEL), self.db_path_input)

        # 3. 新增：远程工作目录 (remote_dir)
        self.remote_dir_input = QLineEdit()
        self.remote_dir_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self.remote_dir_input.setPlaceholderText("服务器存放临时文件的目录")
        form.addRow(QLabel("远程工作目录:", styleSheet=styles.FORM_LABEL), self.remote_dir_input)
        
        layout.addLayout(form)

        # 保存按钮
        button_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("保存 BLAST 设置")
        self.save_btn.setStyleSheet(styles.BUTTON_SUCCESS)
        self.save_btn.clicked.connect(self._on_save_clicked)
        button_layout.addWidget(self.save_btn)
        button_layout.addStretch()  # 添加弹性空间
        layout.addLayout(button_layout)
        
        # 底部状态
        self.status_label = QLabel("请在修改后点击上方的保存按钮")
        self.status_label.setStyleSheet(styles.LABEL_HINT)
        layout.addWidget(self.status_label)

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
        self.db_path_input.setEnabled(not locked)
        self.bin_path_input.setEnabled(not locked)
        self.remote_dir_input.setEnabled(not locked)
        if locked:
            self.setCursor(Qt.CursorShape.WaitCursor) # 鼠标变为忙碌状态
        else:
            self.unsetCursor() # 恢复默认光标

    def get_values(self):
        return {
            "remote_db": self.db_path_input.text().strip(),
            "blast_bin": self.bin_path_input.text().strip(),
            "remote_dir": self.remote_dir_input.text().strip()
        }

    def set_values(self, remote_db: str, blast_bin: str = "", remote_dir: str = ""):
        self.db_path_input.setText(remote_db or "")
        self.bin_path_input.setText(blast_bin or "")
        self.remote_dir_input.setText(remote_dir or "")

    def _on_save_clicked(self):
        # 发射信号通知父级页面保存配置
        self.request_save.emit()
        self.status_label.setText("BLAST 设置已保存")
        self.status_label.setStyleSheet(styles.STATUS_SUCCESS)