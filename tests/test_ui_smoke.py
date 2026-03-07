"""UI 冒烟测试：确保关键页面和主窗口可初始化。"""

import sys

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture(scope="module")
def main_window(qapp):
    from ui.main_window import MainWindow

    window = MainWindow()
    yield window
    window.close()


class TestUIImports:
    def test_import_main_window(self):
        from ui.main_window import MainWindow

        assert MainWindow is not None

    def test_import_pages(self):
        from ui.pages import AnalysisPage, DetectionPage, HomePage, SettingsPage

        assert all([AnalysisPage, DetectionPage, HomePage, SettingsPage])

    def test_import_widgets(self):
        from ui.widgets import BlastResourceCard, BlastRunCard, BlastSampleCard, ExecutionHistoryCard, StageStatusWidget

        assert all([BlastResourceCard, BlastRunCard, BlastSampleCard, ExecutionHistoryCard, StageStatusWidget])


class TestMainWindowStartup:
    def test_create_main_window(self, main_window):
        assert main_window is not None
        assert main_window.windowTitle() == "H2OMeta 宏基因组分析平台"

    def test_has_service_locator(self, main_window):
        assert main_window.service_locator is not None

    def test_has_expected_pages(self, main_window):
        assert hasattr(main_window, "project_page")
        assert hasattr(main_window, "home_page")
        assert hasattr(main_window, "detection_page")
        assert hasattr(main_window, "settings_page")
        assert hasattr(main_window, "analysis_page")
        assert hasattr(main_window, "assembly_page")

    def test_sidebar_count(self, main_window):
        assert main_window.sidebar.count() == 6


class TestPageStartup:
    def test_detection_page_starts(self, qapp):
        from ui.pages.detection_page import DetectionPage

        page = DetectionPage(main_window=None)
        assert page is not None
        assert hasattr(page, "execution_history")

    def test_analysis_page_starts(self, qapp):
        from ui.pages.analysis_page import AnalysisPage

        page = AnalysisPage(main_window=None)
        assert page is not None
        assert hasattr(page, "_stage_widgets")
        assert len(page._stage_widgets) >= 1


class TestServiceLocatorStartup:
    def test_initialize_without_ssh(self):
        from core.service_locator import ServiceLocator

        locator = ServiceLocator(ssh_service=None)
        count = locator.initialize()
        assert count >= 4
        assert locator.tool_engine is None
        locator.shutdown()
