"""UI smoke tests for key pages and main window startup."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.project_manager import ProjectManager

pytestmark = pytest.mark.ui


def _make_fake_detection_page():
    """Return a lightweight QWidget stub so QWebEngineView is never loaded."""
    from PyQt6.QtWidgets import QWidget

    class _FakeDetectionPage(QWidget):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.execution_history = None

        def refresh_data(self, *a, **kw):
            pass

        def clear_context(self, *a, **kw):
            pass

    return _FakeDetectionPage


@pytest.fixture(scope="module")
def qapp(_ensure_qapp):
    yield _ensure_qapp


@pytest.fixture(scope="module")
def main_window(qapp):
    from ui.main_window import MainWindow

    with patch("ui.main_window.DetectionPage", _make_fake_detection_page()):
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
    project_id = pm.create_project("test project", "used for UI verification")
    pm.open_project(project_id)

    with patch("ui.main_window.DetectionPage", _make_fake_detection_page()):
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
        (sample_id, name, "test source", metadata),
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
        assert main_window.windowTitle() != ""

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
        from ui.pages.detection_page_web import DetectionPageWeb

        page = DetectionPageWeb(main_window=None, enable_webengine=False)
        assert page is not None
        assert hasattr(page, "execution_history")
        assert page.web_view is None

    def test_analysis_page_starts(self, qapp):
        from ui.pages.analysis_page import AnalysisPage

        page = AnalysisPage(main_window=None)
        assert page is not None
        assert hasattr(page, "_stage_widgets")
        assert len(page._stage_widgets) >= 1


class TestDetectionIntegratedWorkbench:
    def test_tool_bridge_parses_primer_result_text(self):
        from ui.pages.detection_page_web import ToolBridge

        rows = ToolBridge._parse_primer_result_text(
            "Virus_A\tregion_1\tAAA\tTTT\t10-120\tATGC\n"
            "Virus_B\tregion_2\tCCC\tGGG\t30-150\tCGTA\n"
        )

        assert len(rows) == 2
        assert rows[0]["pathogen"] == "Virus_A"
        assert rows[1]["reverse_primer"] == "GGG"

    def test_tool_bridge_merges_live_primer_results(self, monkeypatch):
        from ui.pages.detection_page_web import ToolBridge

        bridge = ToolBridge(plugin_registry=None)
        monkeypatch.setattr(
            bridge,
            "_get_live_primer_design_view",
            lambda: {
                "title": "实时引物结果",
                "description": "来自最近一次完成任务",
                "status": {"state": "completed", "label": "已加载", "detail": "测试数据"},
                "parameters": [{"label": "样本", "value": "demo"}],
                "summary": [{"label": "最终推荐", "value": "2", "tone": "accent"}],
                "columns": [{"key": "pathogen", "label": "病原体"}],
                "rows": [{"pathogen": "Virus_A"}],
                "artifacts": ["/remote/primer_result_final_2.txt"],
            },
        )

        payload = json.loads(bridge.get_integrated_workbench_config())

        assert payload["views"]["primer_design"]["title"] == "实时引物结果"
        assert payload["views"]["primer_design"]["rows"][0]["pathogen"] == "Virus_A"

    def test_tool_bridge_falls_back_to_default_remote_result_dir(self, monkeypatch):
        from ui.pages.detection_page_web import ToolBridge

        bridge = ToolBridge(plugin_registry=None)
        monkeypatch.setattr(bridge, "_get_live_primer_design_view", lambda: None)
        monkeypatch.setattr(
            bridge,
            "_get_default_primer_result_dir",
            lambda: "/remote/default/primer_design/my_result",
        )
        monkeypatch.setattr(
            bridge,
            "_build_primer_view_from_result_dir",
            lambda remote_dir: {
                "title": "默认远程结果",
                "description": f"来自 {remote_dir}",
                "status": {"state": "completed", "label": "已加载远程结果", "detail": "默认目录"},
                "parameters": [{"label": "结果目录", "value": remote_dir}],
                "summary": [{"label": "目标病原体", "value": "1", "tone": "primary"}],
                "columns": [{"key": "pathogen", "label": "病原体"}],
                "rows": [{"pathogen": "Virus_Default"}],
                "artifacts": [f"{remote_dir}/primer_result_final_2.txt"],
                "remote_result_dir": remote_dir,
            },
        )

        payload = json.loads(bridge.get_integrated_workbench_config())

        assert payload["views"]["primer_design"]["rows"][0]["pathogen"] == "Virus_Default"
        assert payload["views"]["primer_design"]["remote_result_dir"] == "/remote/default/primer_design/my_result"

    def test_tool_bridge_returns_remote_primer_results_payload(self, monkeypatch):
        from ui.pages.detection_page_web import ToolBridge

        bridge = ToolBridge(plugin_registry=None)
        monkeypatch.setattr(
            bridge,
            "_build_primer_view_from_result_dir",
            lambda remote_dir: {
                "title": "远程结果",
                "description": f"来自 {remote_dir}",
                "status": {"state": "completed", "label": "已加载远程结果", "detail": "测试"},
                "parameters": [{"label": "结果目录", "value": remote_dir}],
                "summary": [{"label": "目标病原体", "value": "1", "tone": "primary"}],
                "columns": [{"key": "pathogen", "label": "病原体"}],
                "rows": [{"pathogen": "Virus_A"}],
                "artifacts": [f"{remote_dir}/primer_result_final_2.txt"],
                "remote_result_dir": remote_dir,
            },
        )

        payload = json.loads(bridge.get_remote_primer_results("/remote/primer_job/my_result"))

        assert payload["status"] == "ok"
        assert payload["view"]["remote_result_dir"] == "/remote/primer_job/my_result"

    def test_detection_asset_contains_integrated_console_markup(self):
        html = Path("ui/pages/detection_page_assets/index_galaxy.html").read_text(encoding="utf-8")

        assert 'id="tab-integrated"' in html
        assert 'id="integrated-feature-list"' in html
        assert 'id="integrated-run-card"' in html
        assert 'id="integrated-run-btn"' in html
        assert 'id="integrated-input-list"' in html
        assert 'id="integrated-table-body"' in html
        assert 'id="remote-primer-dir"' in html


class TestHomePageFlows:
    def test_add_sample_updates_home_page_state(self, qapp, temp_main_window):
        home_page = temp_main_window.home_page
        pm = temp_main_window._pm

        home_page._on_sample_added(
            pm,
            name="sample_A",
            r1_path="C:/data/sample_A_R1.fastq.gz",
            r2_path="",
            source="wastewater",
        )
        _flush_events(qapp)

        count = pm.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        assert count == 1
        assert len(home_page._card_widgets) == 1
        assert home_page._stat_samples.text().endswith("1")
        assert home_page._add_btn.isEnabled() is True

    def test_continue_analysis_prefills_existing_sample_context(self, qapp, temp_main_window):
        home_page = temp_main_window.home_page
        pm = temp_main_window._pm

        home_page._on_sample_added(
            pm,
            name="sample_B",
            r1_path="C:/reads/sample_B_R1.fastq.gz",
            r2_path="C:/reads/sample_B_R2.fastq.gz",
            source="river",
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
        project_one = pm.create_project("project one", "first project")
        pm.open_project(project_one)
        _insert_sample(pm, "smp_alpha", "alpha", "C:/reads/alpha_R1.fastq.gz")

        project_two = pm.create_project("project two", "second project")
        pm.open_project(project_one)

        with patch("ui.main_window.DetectionPage", _make_fake_detection_page()):
            window = MainWindow(project_manager=pm)
        _flush_events(qapp)

        assert window.home_page._proj_name_label.text() == "project one"
        assert len(window.home_page._card_widgets) == 1

        window.home_page._on_continue_analysis("smp_alpha")
        _flush_events(qapp)
        assert window.analysis_page._selected_sample_id == "smp_alpha"

        pm.open_project(project_two)
        window._on_project_switched(project_two)
        _flush_events(qapp)

        assert window.home_page._proj_name_label.text() == "project two"
        assert len(window.home_page._card_widgets) == 0
        assert window.home_page._stat_samples.text().endswith("0")
        assert window.analysis_page._selected_sample_id is None
        assert window.analysis_page._sample_name_input.text() == ""
        assert window.analysis_page._r1_path_label.text() != "alpha_R1.fastq.gz"

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


def test_settings_save_without_execution_section(qapp, tmp_path: Path, monkeypatch):
    import config
    from ui.main_window import MainWindow

    tmp_config = tmp_path / "config.json"
    monkeypatch.setattr(config, "_CONFIG_PATH", tmp_config)

    schema = config.default_settings_schema()
    config.save_config(schema)

    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
    )
    project_id = pm.create_project("test_project", "ui verification")
    pm.open_project(project_id)

    with patch("ui.main_window.DetectionPage", _make_fake_detection_page()):
        window = MainWindow(project_manager=pm)
    _flush_events(qapp)

    assert "execution" not in config.get_config()

    settings_page = window.settings_page
    settings_page.db_card.set_values({"blast_nt": "/remote/blast_nt"})
    settings_page.ncbi_card.set_values(email="user@example.com")
    settings_page.save_config()
    _flush_events(qapp)

    saved = config.get_config()
    assert "execution" not in saved
    assert config.get_database_path("blast_nt") == "/remote/blast_nt"
    assert config.get_ncbi_setting("email") == "user@example.com"

    window.close()
    pm.close()


def test_linux_settings_web_install_is_deferred(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)

    card = LinuxSettingsCard()
    card.active_client = object()
    card._tools = [{"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"}]

    scheduled = []
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.QTimer.singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )

    launched = []
    monkeypatch.setattr(card, "_do_install_tool", lambda tool: launched.append(tool))

    card._on_install_from_web("fastp")

    assert launched == []
    assert len(scheduled) == 1
    assert scheduled[0][0] == 0

    scheduled[0][1]()
    assert launched == [{"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"}]

    card.close()


def test_linux_settings_install_dialog_failure_is_handled(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)

    card = LinuxSettingsCard()
    card.active_client = MagicMock()
    monkeypatch.setattr(card, "_make_ssh_run_fn", lambda: MagicMock())

    def raise_dialog_error(*args, **kwargs):
        raise RuntimeError("dialog boom")

    critical_calls = []
    monkeypatch.setattr("ui.widgets.linux_settings_card.EnvInstallDialog", raise_dialog_error)
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.QMessageBox.critical",
        lambda *args: critical_calls.append(args),
    )

    card._do_install_tool({"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"})

    assert card.status_label.text() == "打开安装窗口失败: fastp"
    assert len(critical_calls) == 1

    card.close()
