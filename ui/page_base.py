from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout
from ui.widgets import styles

class BasePage(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.label = QLabel(title)
        self.label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {styles.COLOR_TEXT_DEFAULT};")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.label)
        self.setStyleSheet(f"background-color: {styles.COLOR_BG_PAGE};")

