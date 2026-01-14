# ui/widgets/blast_run_card.py
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QWidget, QLineEdit, QFileDialog
)
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
        layout.setSpacing(10)

        title = QLabel("步骤 3：分析结果与数据解读")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        # 状态与进度
        self.status_msg = QLabel("等待参数确认...")
        self.status_msg.setStyleSheet(styles.LABEL_HINT)
        layout.addWidget(self.status_msg)

        # --- 新增：本地保存路径选择 ---
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("保存目录:", styleSheet=styles.FORM_LABEL))
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.path_input.setStyleSheet(styles.INPUT_LINEEDIT)
        self.browse_btn = QPushButton("更改目录")
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.setStyleSheet(styles.BUTTON_LINK_PRIMARY)
        path_row.addWidget(self.path_input)
        path_row.addWidget(self.browse_btn)
        layout.addLayout(path_row)

        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(6)
        self.pbar.setTextVisible(False)
        self.pbar.setStyleSheet("QProgressBar { border-radius: 3px; background: #eee; } QProgressBar::chunk { background: #1890ff; }")
        self.pbar.hide()
        layout.addWidget(self.pbar)

        # --- 新增：本地保存路径显示区 ---
        self.path_display = QLabel("")
        self.path_display.setStyleSheet(
            "background-color: #f0f7ff; border: 1px dashed #1890ff; padding: 6px; "
            "border-radius: 4px; color: #003a8c; font-size: 11px; font-family: 'Consolas';"
        )
        self.path_display.setWordWrap(True)
        self.path_display.hide() 
        layout.addWidget(self.path_display)

        # 1. 智能解读区
        self.interpret_box = QFrame()
        self.interpret_box.setStyleSheet("background: #f0f7ff; border-radius: 6px; border: 1px solid #dcebfa;")
        self.interpret_box.hide()
        it_layout = QVBoxLayout(self.interpret_box)
        self.interpret_label = QLabel("")
        self.interpret_label.setStyleSheet("color: #003a8c; font-size: 13px;")
        it_layout.addWidget(self.interpret_label)
        layout.addWidget(self.interpret_box)

        # 2. 专业结果表格 (带悬停解释)
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(12)
        headers = ["Query", "Subject", "Ident%", "Len", "Mism", "Gap", "QS", "QE", "SS", "SE", "E-val", "Score"]
        tips = ["查询序列 ID", "参考序列 ID", "一致性(%)", "比对长度", "错配数", "空位数", "查询起始", "查询结束", "参考起始", "参考结束", "期望值", "比对得分"]
        self.result_table.setHorizontalHeaderLabels(headers)
        for i, tip in enumerate(tips):
            item = self.result_table.horizontalHeaderItem(i)
            if item: item.setToolTip(tip) # 悬停解释

        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.result_table.setStyleSheet("QTableWidget { border: 1px solid #e1eefb; background: white; gridline-color: #f0f0f0; }")
        layout.addWidget(self.result_table)

        # 3. 分页控制条
        self.page_nav = QWidget()
        nav_layout = QHBoxLayout(self.page_nav)
        self.prev_btn = QPushButton("上一页")
        self.next_btn = QPushButton("下一页")
        self.page_label = QLabel("第 1 / 1 页")
        self.prev_btn.setFixedWidth(70)
        self.next_btn.setFixedWidth(70)
        nav_layout.addStretch(); nav_layout.addWidget(self.prev_btn); nav_layout.addWidget(self.page_label); nav_layout.addWidget(self.next_btn); nav_layout.addStretch()
        layout.addWidget(self.page_nav)
        self.page_nav.hide()

        # 运行按钮
        self.run_btn = QPushButton("开始 BLAST 分析")
        self.run_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self.run_btn.setFixedHeight(40)
        self.run_btn.setEnabled(False)
        layout.addWidget(self.run_btn)

    def show_loading(self, show):
        self.run_btn.setEnabled(not show)
        if show:
            self.pbar.show(); self.pbar.setRange(0, 0)
            self.interpret_box.hide(); self.result_table.setRowCount(0); self.page_nav.hide()
        else:
            self.pbar.hide()
