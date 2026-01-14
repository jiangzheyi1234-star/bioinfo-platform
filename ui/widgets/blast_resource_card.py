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
            # 校验逻辑保持不变：检查分卷索引文件
            cmd = f"ls {self.db_path}*.nsq > /dev/null 2>&1 && echo 'OK'"
            service = SSHService(self.client_provider)
            rc, out, _ = service.run(cmd, timeout=5)
            if rc == 0 and "OK" in out:
                self.finished.emit(True, "配置已保存")
            else:
                self.finished.emit(False, "路径无效")
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