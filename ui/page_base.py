from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

class BasePage(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.label = QLabel(title)
        self.label.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.label)
        self.setStyleSheet("background-color: #f5f7f9;")

