# 预留导出页面类
from .settings_page import SettingsPage
from .database_page import DatabasePage
from .detection_page_web import DetectionPageWeb
from .home_page import HomePage
from .project_page import ProjectPage
from .log_page import LogPage

# Backward-compatible export: legacy imports expect `DetectionPage`.
DetectionPage = DetectionPageWeb

__all__ = [
    "SettingsPage",
    "DatabasePage",
    "DetectionPageWeb",
    "DetectionPage",
    "HomePage",
    "ProjectPage",
    "LogPage",
]
