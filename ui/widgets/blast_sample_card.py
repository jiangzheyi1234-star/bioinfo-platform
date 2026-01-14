from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog
from PyQt6.QtCore import Qt, pyqtSignal
from ui.widgets import styles

class BlastSampleCard(QFrame):
    """步骤 2：样本导入卡片"""
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BlastSampleCard")
        self.setStyleSheet(styles.CARD_FRAME("BlastSampleCard")) # 使用固定卡片样式
        self._selected_path = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(12)

        # 标题
        title = QLabel("步骤 2：样本导入")
        title.setStyleSheet(styles.CARD_TITLE)
        layout.addWidget(title)

        # 文件选择行
        file_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("请选择本地 FASTA 文件...")
        self.path_input.setReadOnly(True) # 只读，防止手动误改
        self.path_input.setStyleSheet(styles.INPUT_LINEEDIT) # 固定白色样式
        
        self.browse_btn = QPushButton("浏览")
        self.browse_btn.setStyleSheet(styles.BUTTON_PRIMARY) # 包含悬停效果
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_btn.clicked.connect(self._on_browse)

        file_row.addWidget(self.path_input)
        file_row.addWidget(self.browse_btn)
        layout.addLayout(file_row)

        # 提示信息
        self.hint_label = QLabel("支持格式: .fasta, .fa, .fna, .txt")
        self.hint_label.setStyleSheet(styles.LABEL_HINT)
        layout.addWidget(self.hint_label)

        # 状态展示
        self.status_label = QLabel("未选择文件")
        self.status_label.setStyleSheet(styles.STATUS_NEUTRAL)
        layout.addWidget(self.status_label)
        
        layout.addStretch()

    def _on_browse(self):
        """核心：通过限制后缀名引导用户"""
        file_filter = "FASTA Files (*.fasta *.fa *.fna);;Text Files (*.txt);;All Files (*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择序列文件", "", file_filter
        )
        
        if file_path:
            self._selected_path = file_path
            self.path_input.setText(file_path)
            self.status_label.setText(" 已就绪")
            self.status_label.setStyleSheet(styles.STATUS_SUCCESS)
            self.file_selected.emit(file_path)

    def get_file_path(self):
        return self._selected_path