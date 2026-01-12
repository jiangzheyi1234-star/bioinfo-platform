# ui/page.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt

class BasePage(QFrame):
    """基础页面类，设置统一背景"""
    def __init__(self, title):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.label = QLabel(title)
        self.label.setStyleSheet("font-size: 24px; font-weight: bold; color: #333;")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.label)
        self.setStyleSheet("background-color: #f5f7f9; border-radius: 5px;")

class HomePage(BasePage):
    def __init__(self):
        super().__init__("📊 系统概览 / 首页")

class DetectionPage(BasePage):
    def __init__(self):
        super().__init__("🔍 病原体监测分析")

class SettingsPage(BasePage):
    def __init__(self):
        super().__init__("⚙ 设置")
