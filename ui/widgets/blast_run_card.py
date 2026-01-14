# ui/widgets/blast_run_card.py
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QProgressBar
from PyQt6.QtCore import Qt
from ui.widgets import styles

class BlastRunCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BlastRunCard")
        self.setStyleSheet(styles.CARD_FRAME("BlastRunCard"))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        title = QLabel("步骤 3：任务执行与回传结果")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        # 状态提示与进度条
        status_row = QHBoxLayout()
        self.status_msg = QLabel("等待前置配置...")
        self.status_msg.setStyleSheet(styles.LABEL_HINT)
        status_row.addWidget(self.status_msg)
        status_row.addStretch()
        layout.addLayout(status_row)

        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(6)
        self.pbar.setTextVisible(False)
        self.pbar.setStyleSheet("QProgressBar { border-radius: 3px; background: #f0f0f0; border: none; } "
                                "QProgressBar::chunk { background: #1890ff; border-radius: 3px; }")
        self.pbar.hide()
        layout.addWidget(self.pbar)

        self.run_btn = QPushButton("开始 BLAST 比对并自动回传")
        self.run_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self.run_btn.setFixedHeight(42)
        self.run_btn.setEnabled(False)
        layout.addWidget(self.run_btn)

        # 本地结果预览区
        layout.addWidget(QLabel("本地回传结果预览 (Top Hits):", styleSheet=styles.FORM_LABEL))
        self.result_view = QTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setPlaceholderText("分析完成后，这里将预览保存在本地的结果文件...")
        self.result_view.setStyleSheet("background: #fdfdfd; border: 1px solid #e1eefb; border-radius: 6px; font-family: 'Consolas';")
        layout.addWidget(self.result_view)

    def set_ready(self, ready, msg=""):
        self.run_btn.setEnabled(ready)
        self.status_msg.setText(msg or ("就绪，可开始比对" if ready else "等待参数确认..."))

    def show_loading(self, show):
        self.run_btn.setEnabled(not show)
        if show:
            self.pbar.show()
            self.pbar.setRange(0, 0)
        else:
            self.pbar.hide()