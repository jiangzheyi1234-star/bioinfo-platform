"""UI 冒烟测试 — 确保应用程序可以正常启动并显示主窗口。

验证:
  - 所有页面模块可正确导入
  - MainWindow 在无项目、无 SSH 的条件下能正常构造
  - 各页面组件正常初始化（不崩溃）
  - ServiceLocator 信号链路正常连接
"""

import sys

import pytest


@pytest.fixture(scope="module")
def qapp():
    """创建一次 QApplication 供所有测试共用"""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture(scope="module")
def main_window(qapp):
    """创建一次 MainWindow 供所有测试共用，避免反复创建/销毁导致 Qt 崩溃"""
    from ui.main_window import MainWindow
    window = MainWindow()
    yield window
    window.close()


# ── 导入测试 ──────────────────────────────────────────────


class TestUIImports:
    """确保所有 UI 模块可正常导入"""

    def test_import_main_window(self):
        from ui.main_window import MainWindow
        assert MainWindow is not None

    def test_import_all_pages(self):
        from ui.pages import AnalysisPage, DetectionPage, SettingsPage, HomePage
        assert all([AnalysisPage, DetectionPage, SettingsPage, HomePage])

    def test_import_all_widgets(self):
        from ui.widgets import (
            ExecutionHistoryCard, StageStatusWidget,
            BlastResourceCard, BlastSampleCard, BlastRunCard,
        )
        assert ExecutionHistoryCard is not None
        assert StageStatusWidget is not None

    def test_import_core_modules(self):
        from core.service_locator import ServiceLocator
        from core.pipeline_runner import PipelineRunner, PipelineStage
        from core.tool_engine import ToolEngine
        from config import get_config, save_config
        assert all([ServiceLocator, PipelineRunner, PipelineStage, ToolEngine])
        assert callable(get_config)
        assert callable(save_config)


# ── MainWindow 启动测试 ────────────────────────────────────


class TestMainWindowStartup:
    """确保 MainWindow 在各种初始状态下都不崩溃"""

    def test_create_main_window(self, main_window):
        """MainWindow 应正常构造"""
        assert main_window is not None
        assert main_window.windowTitle() == "H2OMeta 宏基因组平台"

    def test_main_window_has_service_locator(self, main_window):
        """MainWindow 应自动创建 ServiceLocator"""
        assert main_window.service_locator is not None

    def test_main_window_has_all_pages(self, main_window):
        """MainWindow 应包含所有页面"""
        assert hasattr(main_window, 'project_page')
        assert hasattr(main_window, 'home_page')
        assert hasattr(main_window, 'detection_page')
        assert hasattr(main_window, 'settings_page')
        assert hasattr(main_window, 'analysis_page')

    def test_main_window_sidebar_count(self, main_window):
        """侧边栏应有 6 个导航项（含组装分析）"""
        assert main_window.sidebar.count() == 6

    def test_main_window_show_and_close(self, qapp):
        """show() + close() 不崩溃"""
        from ui.main_window import MainWindow
        window = MainWindow()
        window.show()
        window.close()


# ── DetectionPage 测试 ─────────────────────────────────────


class TestDetectionPageStartup:
    """确保 DetectionPage 在无 ServiceLocator 时不崩溃"""

    def test_create_without_main_window(self, qapp):
        """无 main_window 参数时应正常创建"""
        from ui.pages.detection_page import DetectionPage
        page = DetectionPage(main_window=None)
        assert page is not None

    def test_create_with_main_window(self, main_window):
        """有 main_window 时，执行历史和信号应正常连接"""
        page = main_window.detection_page
        assert hasattr(page, 'execution_history')
        assert hasattr(page, '_current_execution_id')

    def test_history_tab_shows_execution_history(self, main_window):
        """历史标签页应使用 ExecutionHistoryCard"""
        from ui.widgets.execution_history_card import ExecutionHistoryCard
        page = main_window.detection_page
        assert isinstance(page.execution_history, ExecutionHistoryCard)


# ── AnalysisPage 测试 ──────────────────────────────────────


class TestAnalysisPageStartup:
    """确保 AnalysisPage 在无 ServiceLocator 时不崩溃"""

    def test_create_without_main_window(self, qapp):
        from ui.pages.analysis_page import AnalysisPage
        page = AnalysisPage(main_window=None)
        assert page is not None

    def test_has_execution_history_card(self, main_window):
        assert hasattr(main_window.analysis_page, '_execution_history')

    def test_has_stage_widgets(self, main_window):
        assert len(main_window.analysis_page._stage_widgets) == 3

    def test_run_button_disabled_by_default(self, main_window):
        assert not main_window.analysis_page._btn_run.isEnabled()


# ── ServiceLocator 启动测试 ────────────────────────────────


class TestServiceLocatorStartup:
    """确保 ServiceLocator 在无 SSH 条件下正常初始化"""

    def test_initialize_without_ssh(self):
        from core.service_locator import ServiceLocator
        locator = ServiceLocator(ssh_service=None)
        count = locator.initialize()
        assert count >= 4  # fastp, kraken2, hostile, blastn
        locator.shutdown()

    def test_tool_engine_none_without_project(self):
        from core.service_locator import ServiceLocator
        locator = ServiceLocator(ssh_service=None)
        locator.initialize()
        assert locator.tool_engine is None
        locator.shutdown()
