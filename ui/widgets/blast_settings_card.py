# ui/widgets/blast_settings_card.py
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QLabel, QHBoxLayout, QWidget, QApplication
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QObject, pyqtSlot, QTimer
)
from ui.widgets import styles
from core.ssh_service import SSHService


class ClickableHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class VerifyWorker(QObject):
    finished = pyqtSignal(bool, str)

    def __init__(self, client, db_path, blast_bin_path):
        super().__init__()
        self.client = client
        self.db_path = db_path
        self.blast_bin_path = blast_bin_path

    @pyqtSlot()
    def run(self):
        try:
            if not self.client:
                self.finished.emit(False, "SSH 未连接")
                return

            ssh_service = SSHService(lambda: self.client)
            
            # 如果提供了blast_bin路径，先验证该路径下的blast程序是否存在
            if self.blast_bin_path and self.blast_bin_path.strip():
                blast_path = self.blast_bin_path.strip()
                
                # 首先检查提供的路径是否存在
                check_path_cmd = f"test -e '{blast_path}' && echo 'exists' || echo 'not_found'"
                rc, out, err = ssh_service.run(check_path_cmd, timeout=5)
                
                if "not_found" in out:
                    # 如果路径不存在，返回错误
                    self.finished.emit(False, f"验证失败：指定路径不存在: {blast_path}")
                    return
                
                # 检查是否是目录
                check_dir_cmd = f"test -d '{blast_path}' && echo 'dir' || echo 'file'"
                rc_dir, out_dir, err_dir = ssh_service.run(check_dir_cmd, timeout=5)
                
                if "dir" in out_dir:
                    # 如果是目录，认为它是bin目录，直接使用
                    bin_dir = blast_path.rstrip('/')
                else:
                    # 如果是文件，获取其所在目录
                    import os
                    bin_dir = os.path.dirname(blast_path)
                
                # 检查bin目录下是否有blast相关程序
                check_blast_cmd = f"test -f '{bin_dir}/blastn' && echo 'found' || echo 'not_found'"
                rc_blast, out_blast, err_blast = ssh_service.run(check_blast_cmd, timeout=5)
                
                if "not_found" in out_blast:
                    self.finished.emit(False, f"验证失败：在指定目录下未找到BLAST程序: {bin_dir}")
                    return
                
                # 验证bin目录下是否有blastn程序是否可执行
                test_cmd = f"'{bin_dir}/blastn' -help | head -1"
                rc_test, out_test, err_test = ssh_service.run(test_cmd, timeout=5)
                if rc_test != 0:
                    self.finished.emit(False, f"验证失败：指定的BLAST程序不可执行或路径错误: {bin_dir}/blastn")
                    return
                
                # 使用bin目录下的 blastdbcmd 命令验证数据库
                blastdbcmd_path = f"{bin_dir}/blastdbcmd"
                
                # 检查 blastdbcmd 是否存在
                check_cmd = f"test -f '{blastdbcmd_path}' && echo 'found' || echo 'not_found'"
                rc, out, err = ssh_service.run(check_cmd, timeout=5)
                
                if "not_found" in out:
                    self.finished.emit(False, f"验证失败：在相同目录下未找到 blastdbcmd 命令: {blastdbcmd_path}")
                    return
                
                # 使用指定路径的 blastdbcmd 命令验证数据库
                cmd = f"'{blastdbcmd_path}' -db '{self.db_path}' -info"
            else:
                # 如果没有指定路径，尝试使用系统PATH中的blastdbcmd
                check_cmd = "which blastdbcmd || type blastdbcmd || echo 'not_found'"
                rc, out, err = ssh_service.run(check_cmd, timeout=5)
                
                if "not_found" in out or rc != 0:
                    # 如果which/type命令没找到blastdbcmd，尝试直接运行
                    test_cmd = "blastdbcmd -help | head -1"
                    rc_test, out_test, err_test = ssh_service.run(test_cmd, timeout=5)
                    if rc_test != 0:
                        self.finished.emit(False, "验证失败：未找到 blastdbcmd 命令，请确认BLAST+工具包已正确安装")
                        return
                
                # 使用系统PATH中的 blastdbcmd 命令验证数据库
                cmd = f"blastdbcmd -db '{self.db_path}' -info"

            rc, out, err = ssh_service.run(cmd, timeout=10)
            if rc == 0:
                self.finished.emit(True, "验证通过：数据库有效")
            else:
                # 如果直接路径验证失败，尝试仅使用数据库名
                import os
                db_name = os.path.basename(self.db_path.strip())
                if db_name:
                    if self.blast_bin_path and self.blast_bin_path.strip():
                        # 如果指定了 blast_bin，使用该路径下的 blastdbcmd
                        if self.blast_bin_path.endswith('/bin') or self.blast_bin_path.endswith('\\bin'):
                            blastdbcmd_path = f"{self.blast_bin_path.rstrip('/')}/blastdbcmd"
                        else:
                            bin_dir = os.path.dirname(self.blast_bin_path)
                            blastdbcmd_path = f"{bin_dir}/blastdbcmd"
                        cmd = f"'{blastdbcmd_path}' -db '{db_name}' -info"
                    else:
                        cmd = f"blastdbcmd -db '{db_name}' -info"
                    
                    rc2, out2, err2 = ssh_service.run(cmd, timeout=10)
                    if rc2 == 0:
                        self.finished.emit(True, "验证通过：数据库有效")
                    else:
                        self.finished.emit(False, f"验证失败：{err or err2}")
                else:
                    self.finished.emit(False, f"验证失败：{err}")
        except Exception as e:
            self.finished.emit(False, f"校验过程出错: {str(e)}")


class BlastSettingsCard(QFrame):
    request_save = pyqtSignal()  # 仅在验证通过后发射

    def __init__(self, get_ssh_client_func, parent=None):
        super().__init__(parent)
        self.setObjectName("BlastCard")
        self.get_ssh_client = get_ssh_client_func

        # 状态标志
        self._in_edit_mode = True
        self._verifying = False
        self._external_lock = False

        # 定时器
        self._auto_fold_timer = QTimer(self)
        self._auto_fold_timer.setSingleShot(True)
        self._auto_fold_timer.timeout.connect(self._auto_fold)

        self.setStyleSheet(styles.CARD_FRAME("BlastCard"))
        self._build_ui()

        # 初始化状态 - 默认锁定状态，显示修改按钮
        self._lock_inputs()

    def set_external_lock(self, locked: bool) -> None:
        if self._external_lock == locked:
            return
        self._external_lock = locked
        self._refresh_interaction_state()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. 头部区域 (可点击折叠/展开)
        self.header_area = ClickableHeader()
        self.header_area.setStyleSheet("background: transparent; border: none;")
        self.header_area.clicked.connect(self._toggle_container)

        header_layout = QHBoxLayout(self.header_area)
        header_layout.setContentsMargins(20, 15, 20, 15)

        self.title_label = QLabel("BLAST 环境与路径设置")
        self.title_label.setStyleSheet(styles.CARD_TITLE)

        self.modify_btn = QPushButton("修改")
        self.modify_btn.setFixedWidth(60)
        self.modify_btn.setStyleSheet(styles.BUTTON_LINK)
        self.modify_btn.clicked.connect(self._enable_editing)
        # 修改按钮始终保持可见，不在初始化时隐藏

        self.arrow_label = QLabel("▲")
        self.arrow_label.setStyleSheet("color: #90adca; font-size: 12px;")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.modify_btn)
        header_layout.addWidget(self.arrow_label)

        main_layout.addWidget(self.header_area)

        # 2. 内容容器
        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(20, 0, 20, 20)
        c_layout.setSpacing(15)

        form = QFormLayout()
        form.setVerticalSpacing(10)

        # 输入框
        self.bin_path_input = QLineEdit()
        self.bin_path_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self.bin_path_input.setPlaceholderText(
            "例如: /home/zyserver/anaconda3/envs/ncbi_download/bin 或 /usr/local/ncbi/blast/bin")
        self.bin_path_input.setToolTip(
            "可以是完整路径（如 /path/to/blastn）或bin目录路径（如 /path/to/bin），程序会自动在该目录下查找所有BLAST工具")

        self.db_path_input = QLineEdit()
        self.db_path_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self.db_path_input.setPlaceholderText("例如: /data/blastdb/nt")

        self.remote_dir_input = QLineEdit()
        self.remote_dir_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self.remote_dir_input.setPlaceholderText("例如: /tmp/blast_work")

        # 监听输入改变，如果在非编辑模式下意外改变(通常不会)或需要重置状态
        for w in [self.bin_path_input, self.db_path_input, self.remote_dir_input]:
            w.textChanged.connect(self._on_input_changed)

        form.addRow(QLabel("BLAST 程序路径:", styleSheet=styles.FORM_LABEL), self.bin_path_input)
        form.addRow(QLabel("远程数据库路径:", styleSheet=styles.FORM_LABEL), self.db_path_input)
        form.addRow(QLabel("远程工作目录:", styleSheet=styles.FORM_LABEL), self.remote_dir_input)

        c_layout.addLayout(form)

        # 操作栏
        btn_layout = QHBoxLayout()

        self.save_btn = QPushButton("验证并保存")
        self.save_btn.setFixedWidth(120)
        self.save_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self.save_btn.clicked.connect(self._start_verification)  # 连接到验证逻辑

        self.status_label = QLabel("配置未验证")
        self.status_label.setStyleSheet(styles.STATUS_NEUTRAL)

        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.status_label)
        btn_layout.addStretch()

        c_layout.addLayout(btn_layout)
        main_layout.addWidget(self.container)

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
        
        # 根据是否有有效配置来设置初始状态
        if remote_db and remote_db.strip():
            # 如果有数据库路径，则认为已有配置，进入锁定状态
            self._lock_inputs()
        else:
            # 否则保持编辑状态让用户配置
            self._enable_editing()

    # ---------------- 逻辑控制 ----------------

    def _toggle_container(self):
        """折叠/展开"""
        if self._verifying or self._external_lock:
            return
        visible = self.container.isVisible()
        self.container.setVisible(not visible)
        self.arrow_label.setText("▲" if not visible else "▼")

        # 如果是展开操作且处于锁定状态，显示修改按钮（通常修改按钮一直显示在 header，只要是 locked）
        if not visible:
            self._auto_fold_timer.stop()

    def _auto_fold(self):
        """自动折叠，仅在锁定且可见时触发"""
        if not self._in_edit_mode and self.container.isVisible():
            self.container.hide()
            self.arrow_label.setText("▼")

    def _enable_editing(self):
        """进入编辑模式：解锁输入框，修改按钮保持可见，显示保存按钮"""
        if self._external_lock:
            return
        self.container.show()
        self.arrow_label.setText("▲")

        self.db_path_input.setEnabled(True)
        self.bin_path_input.setEnabled(True)
        self.remote_dir_input.setEnabled(True)

        self.save_btn.show()
        self.save_btn.setEnabled(True)
        self.modify_btn.show()  # 修改按钮保持可见，不隐藏

        self.status_label.setText("请修改配置并验证")
        self.status_label.setStyleSheet(styles.STATUS_NEUTRAL)
        self._in_edit_mode = True
        self._auto_fold_timer.stop()

    def _lock_inputs(self):
        """锁定模式：禁用输入框，修改按钮保持可见"""
        self.db_path_input.setEnabled(False)
        self.bin_path_input.setEnabled(False)
        self.remote_dir_input.setEnabled(False)

        self.save_btn.hide()  # 锁定后隐藏保存按钮
        self.modify_btn.show()  # 修改按钮始终保持可见
        self.status_label.setText("配置已保存")
        self._in_edit_mode = False

    def _on_input_changed(self):
        # 如果正在验证中，禁止改变按钮状态
        if self._verifying or self._external_lock:
            return

        if self._in_edit_mode:
            self.save_btn.setEnabled(True)
            self.status_label.setText("配置已修改，请重新验证")
            self.status_label.setStyleSheet(styles.STATUS_NEUTRAL)

    def _start_verification(self):
        # 防止重复启动：如果正在验证，直接返回
        if self._verifying or self._external_lock:
            return

        client = self.get_ssh_client()
        if not client:
            self.status_label.setText("SSH 未连接，无法验证")
            self.status_label.setStyleSheet(styles.STATUS_ERROR)
            return

        db_path = self.db_path_input.text().strip()
        blast_bin = self.bin_path_input.text().strip()

        if not db_path:
            self.status_label.setText("数据库路径不能为空")
            self.status_label.setStyleSheet(styles.STATUS_ERROR)
            return

        # 设置标志位 & 彻底锁定 UI
        self._verifying = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("正在验证...")
        self.setCursor(Qt.CursorShape.WaitCursor)
        self.status_label.setText("正在连接服务器校验路径...")

        # 关键：验证期间禁用所有输入框，防止用户修改导致按钮重新启用
        self.db_path_input.setEnabled(False)
        self.bin_path_input.setEnabled(False)
        self.remote_dir_input.setEnabled(False)

        # 启动线程
        self._thread = QThread()
        self._worker = VerifyWorker(client, db_path, blast_bin)
        self._worker.moveToThread(self._thread)

        # 连接信号
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_verify_finished)

        # 确保清理资源 - 简化版本
        def cleanup():
            if hasattr(self, '_thread') and self._thread:
                self._thread.quit()
                self._thread.wait()
                self._thread = None
            if hasattr(self, '_worker') and self._worker:
                self._worker.deleteLater()
                self._worker = None

        # 连接清理函数
        self._worker.finished.connect(cleanup)

        self._thread.start()

    def _on_verify_finished(self, success, message):
        # 恢复UI状态
        self._verifying = False
        self.unsetCursor()

        # 恢复输入框状态
        self.db_path_input.setEnabled(True)
        self.bin_path_input.setEnabled(True)
        self.remote_dir_input.setEnabled(True)

        if success:
            # 验证成功：锁定界面，发射保存信号
            self._lock_inputs()
            self.status_label.setText("验证通过，设置已保存")
            self.status_label.setStyleSheet(styles.STATUS_SUCCESS)
            self.save_btn.setText("验证并保存")
            self.request_save.emit()
            self._auto_fold_timer.start(1500)
        else:
            # 验证失败：保持编辑状态
            self.save_btn.setEnabled(True)
            self.save_btn.setText("验证并保存")
            self.status_label.setText(message)
            self.status_label.setStyleSheet(styles.STATUS_ERROR)
        self._refresh_interaction_state()

    def _refresh_interaction_state(self):
        if self._external_lock:
            for w in [
                self.db_path_input,
                self.bin_path_input,
                self.remote_dir_input,
                self.modify_btn,
                self.save_btn,
            ]:
                w.setEnabled(False)
            return

        if self._verifying:
            return

        if self._in_edit_mode:
            self.db_path_input.setEnabled(True)
            self.bin_path_input.setEnabled(True)
            self.remote_dir_input.setEnabled(True)
            self.save_btn.setEnabled(True)
            self.modify_btn.setEnabled(True)
        else:
            self.db_path_input.setEnabled(False)
            self.bin_path_input.setEnabled(False)
            self.remote_dir_input.setEnabled(False)
            self.modify_btn.setEnabled(True)
