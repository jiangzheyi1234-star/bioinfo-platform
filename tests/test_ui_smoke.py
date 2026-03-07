"""UI 冒烟测试：确保关键页面和主窗口可初始化。"""

import json
import sys
from pathlib import Path

import pytest

from core.project_manager import ProjectManager


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


@pytest.fixture()
def temp_main_window(qapp, tmp_path: Path):
    from ui.main_window import MainWindow

    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
    )
    project_id = pm.create_project("测试项目", "用于 UI 验证")
    pm.open_project(project_id)

    window = MainWindow(project_manager=pm)
    qapp.processEvents()
    yield window
    window.close()
    pm.close()


def _flush_events(qapp) -> None:
    qapp.processEvents()
    qapp.processEvents()


def _insert_sample(pm: ProjectManager, sample_id: str, name: str, r1: str, r2: str = "") -> None:
    metadata = json.dumps({"r1": r1, "r2": r2}, ensure_ascii=False)
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        (sample_id, name, "测试来源", metadata),
    )
    pm.db.commit()


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


class TestHomePageFlows:
    def test_add_sample_updates_home_page_state(self, qapp, temp_main_window):
        home_page = temp_main_window.home_page
        pm = temp_main_window._pm

        home_page._on_sample_added(
            pm,
            name="sample_A",
            r1_path="C:/data/sample_A_R1.fastq.gz",
            r2_path="",
            source="污水样本",
        )
        _flush_events(qapp)

        count = pm.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        assert count == 1
        assert len(home_page._card_widgets) == 1
        assert home_page._stat_samples.text() == "📁 1 个样本"
        assert home_page._add_btn.isEnabled() is True

    def test_continue_analysis_prefills_existing_sample_context(self, qapp, temp_main_window):
        home_page = temp_main_window.home_page
        pm = temp_main_window._pm

        home_page._on_sample_added(
            pm,
            name="sample_B",
            r1_path="C:/reads/sample_B_R1.fastq.gz",
            r2_path="C:/reads/sample_B_R2.fastq.gz",
            source="河道样本",
        )
        sample_id = pm.db.execute(
            "SELECT sample_id FROM samples WHERE name = ?",
            ("sample_B",),
        ).fetchone()[0]

        home_page._on_continue_analysis(sample_id)
        _flush_events(qapp)

        analysis_page = temp_main_window.analysis_page
        assert temp_main_window.sidebar.currentRow() == 4
        assert analysis_page._selected_sample_id == sample_id
        assert analysis_page._sample_name_input.text() == "sample_B"
        assert analysis_page._r1_path == "C:/reads/sample_B_R1.fastq.gz"
        assert analysis_page._r2_path == "C:/reads/sample_B_R2.fastq.gz"
        assert analysis_page._r1_path_label.text() == "sample_B_R1.fastq.gz"
        assert analysis_page._r2_path_label.text() == "sample_B_R2.fastq.gz"
        assert pm.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1

    def test_project_switch_refreshes_home_and_clears_analysis_context(self, qapp, tmp_path: Path):
        from ui.main_window import MainWindow

        pm = ProjectManager(
            projects_root=tmp_path / "projects",
            index_path=tmp_path / "projects.json",
        )
        project_one = pm.create_project("项目一", "第一个项目")
        pm.open_project(project_one)
        _insert_sample(pm, "smp_alpha", "alpha", "C:/reads/alpha_R1.fastq.gz")

        project_two = pm.create_project("项目二", "第二个项目")
        pm.open_project(project_one)

        window = MainWindow(project_manager=pm)
        _flush_events(qapp)

        assert window.home_page._proj_name_label.text() == "项目一"
        assert len(window.home_page._card_widgets) == 1

        window.home_page._on_continue_analysis("smp_alpha")
        _flush_events(qapp)
        assert window.analysis_page._selected_sample_id == "smp_alpha"

        pm.open_project(project_two)
        window._on_project_switched(project_two)
        _flush_events(qapp)

        assert window.home_page._proj_name_label.text() == "项目二"
        assert len(window.home_page._card_widgets) == 0
        assert window.home_page._stat_samples.text() == "📁 0 个样本"
        assert window.analysis_page._selected_sample_id is None
        assert window.analysis_page._sample_name_input.text() == ""
        assert window.analysis_page._r1_path_label.text() == "未选择"

        window.close()
        pm.close()


class TestServiceLocatorStartup:
    def test_initialize_without_ssh(self):
        from core.service_locator import ServiceLocator

        locator = ServiceLocator(ssh_service=None)
        count = locator.initialize()
        assert count >= 4
        assert locator.tool_engine is None
        locator.shutdown()

def test_settings_save_updates_runtime_config(qapp, temp_main_window):
    import config

    settings_page = temp_main_window.settings_page
    settings_page.linux_card.spin_concurrent.setValue(5)
    settings_page.linux_card.spin_poll.setValue(11)
    settings_page.db_card.set_values({"blast_nt": "/remote/blast_nt"})
    settings_page.ncbi_card.set_values(email="user@example.com")
    settings_page.save_config()
    _flush_events(qapp)

    assert temp_main_window.service_locator.job_queue.max_concurrent == 5
    assert config.DEFAULT_CONFIG["max_concurrent"] == 5
    assert config.DEFAULT_CONFIG["poll_interval"] == 11
    assert config.DEFAULT_CONFIG["remote_db"] == "/remote/blast_nt"
    assert config.DEFAULT_CONFIG["ncbi_email"] == "user@example.com"
