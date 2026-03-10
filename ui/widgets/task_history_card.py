# ui/widgets/task_history_card.py
"""
任务历史卡片组件
显示历史任务列表，支持查看状态、继续监控、查看结果
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QMessageBox
)
from ui.widgets import styles
from core.task_manager import get_task_manager, TaskRecord


class TaskHistoryCard(QWidget):
    """任务历史卡片"""
    
    # 信号：请求继续监控某个任务
    resume_task = pyqtSignal(str)  # job_id
    # 信号：请求查看结果文件
    view_result = pyqtSignal(str)  # local_output path
    # 信号：刷新任务状态
    refresh_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.refresh_list()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # 标题栏
        header_layout = QHBoxLayout()
        title = QLabel("任务历史")
        title.setStyleSheet(styles.CARD_TITLE)
        header_layout.addWidget(title)

        header_layout.addStretch()

        # 刷新按钮
        self.refresh_btn = QPushButton("刷新状态")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        self.refresh_btn.clicked.connect(self._on_refresh)
        header_layout.addWidget(self.refresh_btn)

        layout.addLayout(header_layout)
        
        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {styles.COLOR_BORDER}; max-height: 1px;")
        layout.addWidget(line)
        
        # 任务表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["任务ID", "状态", "创建时间", "输入文件", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(4, 120)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setStyleSheet(styles.TABLE_WIDGET)
        layout.addWidget(self.table)
        
        # 提示信息
        self.hint_label = QLabel("提示：程序关闭后重新打开，可以在这里看到之前的任务")
        self.hint_label.setStyleSheet(f"color: {styles.COLOR_TEXT_SUB}; font-size: 12px;")
        layout.addWidget(self.hint_label)
        
        # 整体样式 — 白底卡片，无边框，通过背景层次区分
        self.setStyleSheet(f"""
            TaskHistoryCard {{
                background-color: {styles.COLOR_BG_CARD};
                border: none;
                border-radius: {styles.RADIUS_CARD};
            }}
        """)
    
    def refresh_list(self):
        """刷新任务列表"""
        self.table.setRowCount(0)
        tasks = get_task_manager().get_recent_tasks(20)
        
        if not tasks:
            self.table.setRowCount(1)
            item = QTableWidgetItem("暂无任务记录")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, 5)
            return
        
        self.table.setRowCount(len(tasks))
        
        for row, task in enumerate(tasks):
            # 任务ID (简化显示)
            job_id_short = task.job_id[-16:] if len(task.job_id) > 16 else task.job_id
            id_item = QTableWidgetItem(job_id_short)
            id_item.setToolTip(task.job_id)
            id_item.setData(Qt.ItemDataRole.UserRole, task.job_id)  # 存储完整ID
            self.table.setItem(row, 0, id_item)
            
            # 状态
            status_item = QTableWidgetItem(task.status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if task.status == "DONE":
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            elif task.status == "FAILED":
                status_item.setForeground(Qt.GlobalColor.red)
            elif task.status == "RUNNING":
                status_item.setForeground(Qt.GlobalColor.blue)
            else:
                status_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 1, status_item)
            
            # 创建时间
            time_item = QTableWidgetItem(task.get_created_time_str())
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, time_item)
            
            # 输入文件
            import os
            filename = os.path.basename(task.local_fasta) if task.local_fasta else "-"
            file_item = QTableWidgetItem(filename)
            file_item.setToolTip(task.local_fasta)
            self.table.setItem(row, 3, file_item)
            
            # 操作按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(5, 2, 5, 2)
            btn_layout.setSpacing(5)
            
            if task.status == "RUNNING":
                resume_btn = QPushButton("继续监控")
                resume_btn.setStyleSheet(f"background-color: {styles.COLOR_PRIMARY}; color: white; border-radius: 4px; padding: 4px 8px;")
                resume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                resume_btn.clicked.connect(lambda checked, jid=task.job_id: self.resume_task.emit(jid))
                btn_layout.addWidget(resume_btn)
            elif task.status == "DONE" and task.local_output:
                view_btn = QPushButton("查看结果")
                view_btn.setStyleSheet(f"background-color: {styles.COLOR_SUCCESS}; color: white; border-radius: 4px; padding: 4px 8px;")
                view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                view_btn.clicked.connect(lambda checked, path=task.local_output: self.view_result.emit(path))
                btn_layout.addWidget(view_btn)
            else:
                placeholder = QLabel("-")
                placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                btn_layout.addWidget(placeholder)
            
            self.table.setCellWidget(row, 4, btn_widget)
    
    def _on_refresh(self):
        """刷新按钮点击"""
        self.refresh_requested.emit()
    
    def update_task_status(self, job_id: str, status: str):
        """更新指定任务的状态显示"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == job_id:
                status_item = self.table.item(row, 1)
                if status_item:
                    status_item.setText(status)
                    if status == "DONE":
                        status_item.setForeground(Qt.GlobalColor.darkGreen)
                    elif status == "FAILED":
                        status_item.setForeground(Qt.GlobalColor.red)
                break
        # 刷新整个列表以更新操作按钮
        self.refresh_list()
