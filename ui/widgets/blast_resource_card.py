import os
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QLineEdit, QWidget
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from ui.widgets import styles
from config import DEFAULT_CONFIG
from core.ssh_service import SSHService

class ResourceVerifyWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, client_provider, db_path):
        super().__init__()
        self.client_provider = client_provider
        self.db_path = db_path

    def run(self):
        try:
            service = SSHService(self.client_provider)
            
            # 尝试从配置中获取 blast_bin 路径
            from config import DEFAULT_CONFIG
            blast_bin = DEFAULT_CONFIG.get('blast_bin', '')
            
            if blast_bin and blast_bin.strip():
                # 如果指定了 blast_bin 路径，检查它是否是目录还是完整路径
                blast_path = blast_bin.strip()
                
                # 检查提供的路径是否存在
                check_path_cmd = f"test -e '{blast_path}' && echo 'exists' || echo 'not_found'"
                rc, out, err = service.run(check_path_cmd, timeout=5)
                
                if "not_found" in out:
                    self.finished.emit(False, "BLAST 路径配置错误")
                    return
                
                # 检查是否是目录
                check_dir_cmd = f"test -d '{blast_path}' && echo 'dir' || echo 'file'"
                rc_dir, out_dir, err_dir = service.run(check_dir_cmd, timeout=5)
                
                if "dir" in out_dir:
                    # 如果是目录，使用该目录下的 blastdbcmd
                    blastdbcmd_path = f"{blast_path.rstrip('/')}/blastdbcmd"
                else:
                    # 如果是文件路径，获取其所在目录
                    import os
                    bin_dir = os.path.dirname(blast_path)
                    blastdbcmd_path = f"{bin_dir}/blastdbcmd"
                
                # 检查 blastdbcmd 是否存在
                check_cmd = f"test -f '{blastdbcmd_path}' && echo 'found' || echo 'not_found'"
                rc, out, err = service.run(check_cmd, timeout=5)
                
                if "not_found" in out:
                    self.finished.emit(False, "BLAST 工具配置错误")
                    return
                
                # 使用指定路径的 blastdbcmd 验证数据库
                cmd = f"'{blastdbcmd_path}' -db '{self.db_path}' -info"
            else:
                # 如果没有指定路径，尝试使用系统PATH中的 blastdbcmd
                check_cmd = "which blastdbcmd || type blastdbcmd || echo 'not_found'"
                rc, out, err = service.run(check_cmd, timeout=5)
                
                if "not_found" in out or rc != 0:
                    # 如果找不到 blastdbcmd，尝试直接运行
                    test_cmd = "blastdbcmd -help | head -1"
                    rc_test, out_test, err_test = service.run(test_cmd, timeout=5)
                    if rc_test != 0:
                        self.finished.emit(False, "未找到 blastdbcmd 命令")
                        return
                
                # 使用系统PATH中的 blastdbcmd 验证数据库
                cmd = f"blastdbcmd -db '{self.db_path}' -info"

            # 执行验证命令
            rc, out, err = service.run(cmd, timeout=10)
            if rc == 0:
                self.finished.emit(True, "配置已保存")
            else:
                # 如果直接路径验证失败，尝试仅使用数据库名
                import os
                db_name = os.path.basename(self.db_path.strip())
                if db_name:
                    if blast_bin and blast_bin.strip():
                        # 如果指定了 blast_bin，使用该路径下的 blastdbcmd
                        if blast_bin.endswith('/bin') or blast_bin.endswith('\\bin'):
                            blastdbcmd_path = f"{blast_bin.rstrip('/')}/blastdbcmd"
                        else:
                            import os
                            bin_dir = os.path.dirname(blast_bin)
                            blastdbcmd_path = f"{bin_dir}/blastdbcmd"
                        cmd = f"'{blastdbcmd_path}' -db '{db_name}' -info"
                    else:
                        cmd = f"blastdbcmd -db '{db_name}' -info"
                    
                    rc2, out2, err2 = service.run(cmd, timeout=10)
                    if rc2 == 0:
                        self.finished.emit(True, "配置已保存")
                    else:
                        self.finished.emit(False, "数据库路径无效")
                else:
                    self.finished.emit(False, "数据库路径无效")
        except Exception as e:
            self.finished.emit(False, f"校验出错: {str(e)}")

class BlastResourceCard(QFrame):
    def __init__(self, get_client_func, parent=None):
        super().__init__(parent)
        self.setObjectName("BlastResourceCard")
        self.get_client = get_client_func
        self.setStyleSheet(styles.CARD_FRAME("BlastResourceCard"))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(10)

        # 标题
        title = QLabel("步骤 1：资源确认")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        # 类别选择：公共 vs 自定义
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("数据库:", styleSheet=styles.FORM_LABEL))
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(["公共库 (core_nt)", "自定义"])
        self.cat_combo.setFixedWidth(120)
        self.cat_combo.currentIndexChanged.connect(self._on_category_changed)
        cat_row.addWidget(self.cat_combo)
        cat_row.addStretch()
        layout.addLayout(cat_row)

        # 输入框：白色背景，限制宽度
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText("输入远程绝对路径...")
        # 使用全局样式并限制最大宽度
        self.custom_input.setStyleSheet(styles.INPUT_LINEEDIT + "QLineEdit { max-width: 250px; }")
        self.custom_input.hide()
        layout.addWidget(self.custom_input)

        # 路径展示
        self.path_display = QLabel()
        self.path_display.setStyleSheet(styles.LABEL_HINT)
        layout.addWidget(self.path_display)

        # 算法选择
        algo_row = QHBoxLayout()
        algo_row.addWidget(QLabel("比对算法:", styleSheet=styles.FORM_LABEL))
        self.algo_combo = QComboBox()
        self.algo_combo.addItem("Highly similar (megablast)", "megablast")
        self.algo_combo.addItem("Somewhat similar (blastn)", "blastn")
        self.algo_combo.addItem("Short sequences (blastn-short)", "blastn-short")
        self.algo_combo.setFixedWidth(200)
        algo_row.addWidget(self.algo_combo)
        algo_row.addStretch()
        layout.addLayout(algo_row)

        # 操作区
        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("保存配置")
        # 使用全局样式，不再重复定义 hover 和 pressed 效果
        self.save_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self.save_btn.setFixedWidth(90)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save)

        self.status_label = QLabel("未保存")
        self.status_label.setStyleSheet(styles.STATUS_NEUTRAL)

        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.status_label)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._on_category_changed(0)

    def _on_category_changed(self, index):
        is_custom = (index == 1)
        self.custom_input.setVisible(is_custom)
        path = DEFAULT_CONFIG.get("remote_db", "") if not is_custom else self.custom_input.text()
        self.path_display.setText(f"当前路径: {path if not is_custom else '等待输入'}")
        self.status_label.setText("待校验")

    def _on_save(self):
        client = self.get_client()
        if not client:
            self.status_label.setText("请连接服务器")
            self.status_label.setStyleSheet(styles.STATUS_ERROR)
            return

        db_path = DEFAULT_CONFIG.get("remote_db", "") if self.cat_combo.currentIndex() == 0 else self.custom_input.text().strip()
        if not db_path: return

        self._set_locked(True)
        self.status_label.setText("正在保存...")

        self._worker = ResourceVerifyWorker(self.get_client, db_path)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self, success, msg):
        self._set_locked(False)
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(styles.STATUS_SUCCESS if success else styles.STATUS_ERROR)

    def _set_locked(self, locked):
        self.save_btn.setEnabled(not locked)
        self.cat_combo.setEnabled(not locked)
        self.custom_input.setEnabled(not locked)
        if locked:
            self.save_btn.setText("保存中...")
            self.setCursor(Qt.CursorShape.WaitCursor)
        else:
            self.save_btn.setText("保存配置")
            self.unsetCursor()

    def get_db_path(self):
        return DEFAULT_CONFIG.get("remote_db", "") if self.cat_combo.currentIndex() == 0 else self.custom_input.text().strip()

    def get_task(self):
        """返回选中的算法名称"""
        return self.algo_combo.currentData()