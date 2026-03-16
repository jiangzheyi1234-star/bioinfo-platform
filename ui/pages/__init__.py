# 预留导出页面类
from .settings_page import SettingsPage
from .detection_page_web import DetectionPageWeb
from .home_page import HomePage
from .assembly_page import AssemblyPage
from .project_page import ProjectPage
from .log_page import LogPage

# Backward-compatible export: legacy imports expect `DetectionPage`.
DetectionPage = DetectionPageWeb

__all__ = [
    "SettingsPage",
    "DetectionPageWeb",
    "DetectionPage",
    "HomePage",
    "AssemblyPage",
    "ProjectPage",
    "LogPage",
]
