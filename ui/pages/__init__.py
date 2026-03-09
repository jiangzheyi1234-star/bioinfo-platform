# 预留导出页面类
from .settings_page import SettingsPage
from .detection_page_web import DetectionPageWeb
from .home_page import HomePage
from .analysis_page import AnalysisPage
from .assembly_page import AssemblyPage

# Backward-compatible export: legacy imports expect `DetectionPage`.
DetectionPage = DetectionPageWeb

__all__ = [
    "SettingsPage",
    "DetectionPageWeb",
    "DetectionPage",
    "HomePage",
    "AnalysisPage",
    "AssemblyPage",
]
