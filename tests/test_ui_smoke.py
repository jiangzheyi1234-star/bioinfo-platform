"""UI smoke tests for key pages and main window startup."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.data.project_manager import ProjectManager

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
def main_window(qapp, tmp_path_factory):
    from ui.main_window import MainWindow

    tmp_path = tmp_path_factory.mktemp("ui_smoke_main_window")
    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
        last_project_path=tmp_path / "last_project.txt",
    )
    project_id = pm.create_project("test project", "used for UI verification")
    pm.open_project(project_id)

    with patch("ui.main_window.DetectionPage", _make_fake_detection_page()):
        window = MainWindow(project_manager=pm)
        yield window
        window.close()
        window.deleteLater()
        qapp.processEvents()
        qapp.processEvents()
    pm.close()


@pytest.fixture()
def temp_main_window(qapp, tmp_path: Path):
    from ui.main_window import MainWindow

    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
        last_project_path=tmp_path / "last_project.txt",
    )
    project_id = pm.create_project("test project", "used for UI verification")
    pm.open_project(project_id)

    with patch("ui.main_window.DetectionPage", _make_fake_detection_page()):
        window = MainWindow(project_manager=pm)
        qapp.processEvents()
        yield window
        window.close()
        window.deleteLater()
        qapp.processEvents()
        qapp.processEvents()
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
        from ui.pages import DetectionPage, HomePage, SettingsPage

        assert all([DetectionPage, HomePage, SettingsPage])

    def test_import_widgets(self):
        from ui.widgets import BlastRunCard, BlastSampleCard, ExecutionHistoryCard, StageStatusWidget

        assert all([BlastRunCard, BlastSampleCard, ExecutionHistoryCard, StageStatusWidget])


class TestMainWindowStartup:
    def test_create_main_window(self, main_window):
        assert main_window is not None
        assert main_window.windowTitle() != ""

    def test_has_service_locator(self, main_window):
        assert main_window.service_locator is not None

    def test_has_expected_pages(self, main_window):
        assert hasattr(main_window, "_project_selector_btn")
        assert hasattr(main_window, "home_page")
        assert hasattr(main_window, "detection_page")
        assert hasattr(main_window, "settings_page")
        assert hasattr(main_window, "log_page")

    def test_has_database_page(self, main_window):
        assert hasattr(main_window, "database_page")

    def test_sidebar_count(self, main_window):
        assert main_window.sidebar.count() == 5

    def test_auto_open_recent_project_when_none_active(self, qapp, tmp_path):
        from ui.main_window import MainWindow

        pm = ProjectManager(
            projects_root=tmp_path / "projects",
            index_path=tmp_path / "projects.json",
            last_project_path=tmp_path / "last_project.txt",
        )
        pm.create_project("auto-open target", "startup fallback")
        assert pm.current_project is None

        with patch("ui.main_window.DetectionPage", _make_fake_detection_page()):
            window = MainWindow(project_manager=pm)
            qapp.processEvents()
            try:
                assert pm.current_project is not None
                assert "新建项目" not in window._project_selector_btn.text()
            finally:
                window.close()
                window.deleteLater()
                qapp.processEvents()
                qapp.processEvents()
        pm.close()

    def test_install_status_click_opens_task_panel(self, temp_main_window, qapp):
        window = temp_main_window
        window._on_install_task_event(
            {
                "task_id": "db:kraken2_standard",
                "title": "数据库安装 · Kraken2 Standard Database",
                "source": "db",
                "state": "running",
                "message": "下载中",
                "progress_text": "20%",
                "location_hint": "database",
            }
        )
        _flush_events(qapp)
        assert window._install_task_panel is not None
        assert not window._install_task_panel.isVisible()

        window.status_bar.install_status_clicked.emit()
        _flush_events(qapp)
        assert window._install_task_panel.isVisible()

    def test_install_panel_detail_text_explains_background_flow(self, temp_main_window, qapp):
        window = temp_main_window
        window._on_install_task_event(
            {
                "task_id": "tool_env:kraken2",
                "title": "工具环境安装 · kraken2",
                "source": "tool_env",
                "state": "failed",
                "message": "安装失败",
                "location_hint": "settings",
            }
        )
        _flush_events(qapp)
        assert window._install_task_panel is not None

        text = window._install_task_panel._build_task_detail_text(
            {
                "task_id": "tool_env:kraken2",
                "title": "工具环境安装 · kraken2",
                "source": "tool_env",
                "state": "failed",
                "message": "安装失败",
                "location_hint": "settings",
            }
        )
        assert "任务: kraken2" in text
        assert "类型: 工具环境安装" in text
        assert "处理方式: 通过 SSH 提交远端后台安装脚本" in text
        assert "设置 > Linux 环境" in text


class TestPageStartup:
    def test_detection_page_starts(self, qapp):
        from ui.pages.detection_page_web import DetectionPageWeb

        page = DetectionPageWeb(main_window=None, enable_webengine=False)
        assert page is not None
        assert hasattr(page, "execution_history")
        assert page.web_view is None

class TestDetectionIntegratedWorkbench:
    def test_tool_bridge_parses_primer_result_text(self):
        from core.execution.tool_bridge_service import ToolBridgeService

        rows = ToolBridgeService.parse_primer_result_text(
            "Virus_A\tregion_1\tAAA\tTTT\t10-120\tATGC\n"
            "Virus_B\tregion_2\tCCC\tGGG\t30-150\tCGTA\n"
        )

        assert len(rows) == 2
        assert rows[0]["pathogen"] == "Virus_A"
        assert rows[1]["reverse_primer"] == "GGG"

    def test_tool_bridge_parses_multiplex_result_text(self):
        from core.execution.tool_bridge_service import ToolBridgeService

        rows = ToolBridgeService.parse_multiplex_result_text(
            "pathogen\tregion_id\tforward_primer\treverse_primer\tTm_F\tTm_R\tGC_F\tGC_R\tamplicon_length\ttarget_sequence\tconservation_score\tspecificity_score\tamplicon_seq\tpool_id\tpool_dimer_score\n"
            "Virus_A\tregion_1\tAAA\tTTT\t58.1\t58.3\t45\t47\t150\tATGC\t8\t0.950\tATGC\tpool_1\t0\n"
            "Virus_B\tregion_2\tCCC\tGGG\t59.0\t59.2\t50\t51\t172\tCGTA\t9\t-1\tCGTA\tpool_1\t2\n"
        )

        assert len(rows) == 2
        assert rows[0]["tm_f"] == "58.1"
        assert rows[0]["amplicon_length"] == "150"
        assert rows[0]["target_sequence"] == "ATGC"
        assert rows[1]["specificity_score"] == "-1"
        assert rows[1]["pool_dimer_score"] == "2"

    def test_tool_bridge_parses_legacy_multiplex_result_text(self):
        from core.execution.tool_bridge_service import ToolBridgeService

        rows = ToolBridgeService.parse_multiplex_result_text(
            "pathogen\tregion_id\tforward_primer\treverse_primer\ttm_f\ttm_r\tgc_f\tgc_r\tamplicon_length\tpool_score\n"
            "Virus_A\tregion_1\tAAA\tTTT\t58.1\t58.3\t45\t47\t150\tpass\n"
        )

        assert len(rows) == 1
        assert rows[0]["pool_dimer_score"] == "pass"
        assert rows[0]["target_sequence"] == ""

    def test_tool_bridge_merges_live_primer_results(self, monkeypatch):
        from core.execution.tool_bridge_service import ToolBridgeService

        service = ToolBridgeService()
        monkeypatch.setattr(
            service,
            "get_live_primer_design_view",
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

        payload = service.get_integrated_workbench_config()

        assert payload["views"]["primer_design"]["title"] == "实时引物结果"
        assert payload["views"]["primer_design"]["rows"][0]["pathogen"] == "Virus_A"

    def test_tool_bridge_falls_back_to_default_remote_result_dir(self, monkeypatch):
        from core.execution.tool_bridge_service import ToolBridgeService

        service = ToolBridgeService()
        monkeypatch.setattr(service, "get_live_primer_design_view", lambda: None)
        monkeypatch.setattr(
            service,
            "get_default_primer_result_dir",
            lambda: "/remote/default/primer_design/my_result",
        )
        monkeypatch.setattr(
            service,
            "build_primer_view_from_result_dir",
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

        payload = service.get_integrated_workbench_config()

        assert payload["views"]["primer_design"]["rows"][0]["pathogen"] == "Virus_Default"
        assert payload["views"]["primer_design"]["remote_result_dir"] == "/remote/default/primer_design/my_result"

    def test_tool_bridge_exposes_multiplex_feature(self):
        from core.execution.tool_bridge_service import ToolBridgeService

        service = ToolBridgeService()
        payload = service.get_integrated_workbench_config()

        feature_ids = [item["id"] for item in payload["features"]]
        assert "multiplex_primer_panel" in feature_ids
        assert payload["views"]["multiplex_primer_panel"]["tool_ids"] == ["multiplex_primer_panel"]

    def test_tool_bridge_exposes_metagenomics_features(self):
        from core.execution.tool_bridge_service import ToolBridgeService

        service = ToolBridgeService()
        payload = service.get_integrated_workbench_config()

        feature_ids = [item["id"] for item in payload["features"]]
        assert "wastewater_metagenomics_basic" in feature_ids
        assert "animal_metagenomics_basic" in feature_ids
        assert payload["views"]["wastewater_metagenomics_basic"]["tool_ids"] == ["wastewater_metagenomics_basic"]
        assert payload["views"]["animal_metagenomics_basic"]["tool_ids"] == ["animal_metagenomics_basic"]

    def test_targeted_results_route_detection_workflow_view(self, monkeypatch, tmp_path: Path):
        from core.execution.tool_bridge_service import ToolBridgeService

        pm = ProjectManager(
            projects_root=tmp_path / "projects",
            index_path=tmp_path / "projects.json",
            last_project_path=tmp_path / "last_project.txt",
        )
        project_id = pm.create_project("route metagenomics")
        pm.open_project(project_id)
        pm.db.execute(
            "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
            ("smp_meta", "meta", "test", "{}"),
        )
        pm.db.execute(
            "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("exec_meta", "smp_meta", "wastewater_metagenomics_basic", "1.0", "{}", "completed", "manual", 1.0),
        )
        pm.db.commit()

        class _Locator:
            project_manager = pm

        service = ToolBridgeService(service_locator=_Locator())
        monkeypatch.setattr(
            service,
            "_build_workflow_product_view_for_execution",
            lambda execution_id, row=None, execution_row=None, feature_id=None: {
                "feature_id": "wastewater_metagenomics_basic",
                "archetype": "workflow_product",
                "hero": {"execution_id": execution_id},
            },
        )

        payload = service.get_targeted_seq_results_for_execution("exec_meta")

        assert payload["status"] == "ok"
        assert payload["view"]["feature_id"] == "wastewater_metagenomics_basic"
        assert payload["view"]["hero"]["execution_id"] == "exec_meta"
        assert payload["view"]["archetype"] == "workflow_product"
        pm.close()

    def test_tool_bridge_parses_bracken_rows(self, tmp_path: Path):
        from core.execution.tool_bridge_service import ToolBridgeService

        tsv_path = tmp_path / "demo.bracken.tsv"
        tsv_path.write_text(
            "name\ttaxonomy_id\ttaxonomy_lvl\tkraken_assigned_reads\tadded_reads\tnew_est_reads\tfraction_total_reads\n"
            "Escherichia coli\t562\tS\t10\t5\t20\t0.40\n"
            "Klebsiella pneumoniae\t573\tS\t8\t2\t12\t0.24\n",
            encoding="utf-8",
        )

        rows = ToolBridgeService._parse_bracken_abundance_rows(tsv_path)

        assert rows[0]["name"] == "Escherichia coli"
        assert rows[0]["reads"] == "20"
        assert rows[0]["percentage"] == "40.00%"

    def test_tool_bridge_builds_read_flow_chart(self, tmp_path: Path):
        from core.execution.tool_bridge_service import ToolBridgeService

        fastp_json = tmp_path / "fastp.json"
        fastp_json.write_text(
            json.dumps(
                {
                    "summary": {
                        "before_filtering": {"total_reads": 1000},
                        "after_filtering": {"total_reads": 800},
                    }
                }
            ),
            encoding="utf-8",
        )

        chart = ToolBridgeService._build_read_flow_chart(
            fastp_json,
            {"total_reads": 700, "classified_reads": 500, "unclassified_reads": 200},
        )

        assert chart is not None
        assert chart["type"] == "funnel"
        assert [item["name"] for item in chart["data"]] == ["原始 Reads", "QC 后", "送分类 Reads", "已分类", "未分类"]

    def test_history_query_does_not_reconcile_running_execution(self, tmp_path: Path):
        from core.execution.tool_bridge_service import ToolBridgeService

        pm = ProjectManager(
            projects_root=tmp_path / "projects",
            index_path=tmp_path / "projects.json",
            last_project_path=tmp_path / "last_project.txt",
        )
        project_id = pm.create_project("history reconcile")
        pm.open_project(project_id)
        pm.db.execute(
            "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
            ("smp_demo", "demo", "test", "{}"),
        )
        pm.db.execute(
            "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("exec_demo", "smp_demo", "primer_design", "1.0", "{}", "running", "manual", 1.0),
        )
        pm.db.commit()

        class _FakeSSH:
            is_connected = True

            def run(self, cmd, timeout=10):
                if "screen -ls" in cmd:
                    return 1, "", ""
                if "exit_code.txt" in cmd:
                    return 0, "0\n", ""
                if "test -f" in cmd:
                    return 1, "", ""
                return 0, "", ""

        class _FakeEngine:
            def __init__(self):
                self.completed = []

            def on_job_completed(self, execution_id, descriptor, sample_id, output_dir):
                self.completed.append((execution_id, sample_id, output_dir))
                pm.db.execute(
                    "UPDATE executions SET status = 'completed', completed_at = ? WHERE execution_id = ?",
                    (2.0, execution_id),
                )
                pm.db.commit()

            def on_job_failed(self, execution_id, error):
                raise AssertionError("should not fail")

        class _Locator:
            project_manager = pm
            ssh_service = _FakeSSH()
            tool_engine = _FakeEngine()

        service = ToolBridgeService(service_locator=_Locator())
        history = service.get_execution_history()
        assert history and history[0]["execution_id"] == "exec_demo"

        row = pm.db.execute(
            "SELECT status FROM executions WHERE execution_id = ?",
            ("exec_demo",),
        ).fetchone()
        assert row["status"] == "running"
        pm.close()

    def test_tool_bridge_returns_remote_primer_results_payload(self, monkeypatch):
        from core.execution.tool_bridge_service import ToolBridgeService

        service = ToolBridgeService()
        monkeypatch.setattr(
            service,
            "build_primer_view_from_result_dir",
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

        payload = service.get_remote_primer_results("/remote/primer_job/my_result")

        assert payload["status"] == "ok"
        assert payload["view"]["remote_result_dir"] == "/remote/primer_job/my_result"

    def test_tool_bridge_returns_primer_results_for_execution(self, monkeypatch):
        from core.execution.tool_bridge_service import ToolBridgeService

        service = ToolBridgeService()
        monkeypatch.setattr(
            service,
            "_get_execution_result_row",
            lambda execution_id: {"execution_id": execution_id, "tool_id": "primer_design"},
        )
        monkeypatch.setattr(
            service,
            "_build_workflow_product_view_for_execution",
            lambda execution_id, row: {
                "title": "history primer",
                "feature_id": "primer_design",
                "archetype": "workflow_product",
                "hero": {"execution_id": execution_id},
            },
        )

        payload = service.get_primer_results_for_execution("exec_abc123")

        assert payload["status"] == "ok"
        assert payload["view"]["hero"]["execution_id"] == "exec_abc123"
        assert payload["view"]["archetype"] == "workflow_product"

    def test_tool_bridge_lists_local_execution_artifacts(self, tmp_path: Path):
        from core.data.project_manager import ProjectManager
        from core.execution.tool_bridge_service import ToolBridgeService

        pm = ProjectManager(
            projects_root=tmp_path / "projects",
            index_path=tmp_path / "projects.json",
            last_project_path=tmp_path / "last_project.txt",
        )
        project_id = pm.create_project("artifact project")
        pm.open_project(project_id)
        results_dir = pm.current_project_dir / "results" / "exec_demo"
        results_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = results_dir / "primer_result_final_2.txt"
        artifact_path.write_text("demo", encoding="utf-8")
        (results_dir / "artifacts_manifest.json").write_text(
            json.dumps(
                {
                    "execution_id": "exec_demo",
                    "tool_id": "primer_design",
                    "artifacts": [
                        {
                            "name": "primer_result_final_2.txt",
                            "remote_path": "/remote/primer_result_final_2.txt",
                            "local_path": str(artifact_path),
                            "available": True,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        class _Locator:
            project_manager = pm

        service = ToolBridgeService(service_locator=_Locator())
        artifacts = service.list_local_execution_artifacts("exec_demo")

        assert artifacts[0]["name"] == "primer_result_final_2.txt"
        assert artifacts[0]["available"] is True

    def test_tool_bridge_returns_multiplex_results_for_execution(self, monkeypatch):
        from core.execution.tool_bridge_service import ToolBridgeService

        service = ToolBridgeService()
        monkeypatch.setattr(
            service,
            "_get_execution_result_row",
            lambda execution_id: {"execution_id": execution_id, "tool_id": "multiplex_primer_panel"},
        )
        monkeypatch.setattr(
            service,
            "_build_workflow_product_view_for_execution",
            lambda execution_id, row: {
                "title": "history multiplex",
                "feature_id": "multiplex_primer_panel",
                "archetype": "workflow_product",
                "hero": {"execution_id": execution_id},
            },
        )

        payload = service.get_multiplex_results_for_execution("exec_mux123")

        assert payload["status"] == "ok"
        assert payload["view"]["hero"]["execution_id"] == "exec_mux123"
        assert payload["view"]["archetype"] == "workflow_product"

    def test_tool_bridge_normalizes_legacy_project_remote_base(self):
        from core.execution.tool_bridge_service import ToolBridgeService

        class _FakeSSH:
            is_connected = True

            def run(self, cmd, timeout=10):
                return 0, "/home/tester", ""

        class _FakeProject:
            project_id = "proj_demo123456"
            remote_base = "/h2ometa/projects/proj_demo123456"

        class _FakePM:
            def __init__(self):
                self.current_project = _FakeProject()
                self._index = {
                    self.current_project.project_id: {
                        "remote_base": self.current_project.remote_base,
                    }
                }
                self.saved = False

            def _save_index(self):
                self.saved = True

        service = ToolBridgeService()
        service._service_locator = type("SL", (), {"ssh_service": _FakeSSH()})()
        pm = _FakePM()

        service.normalize_project_remote_base(pm)

        assert pm.current_project.remote_base == "/home/tester/.h2ometa/projects/proj_demo123456"
        assert pm._index["proj_demo123456"]["remote_base"] == "/home/tester/.h2ometa/projects/proj_demo123456"
        assert pm.saved is True

    def test_detection_asset_contains_integrated_console_markup(self):
        html = Path("ui/pages/detection_page_assets/index_galaxy.html").read_text(encoding="utf-8")
        js = Path("ui/pages/detection_page_assets/app_galaxy.js").read_text(encoding="utf-8")

        assert 'id="tab-integrated"' in html
        assert 'id="integrated-feature-list"' in html
        assert 'id="integrated-run-card"' in html
        assert 'id="integrated-run-btn"' in html
        assert 'id="integrated-input-list"' in html
        assert 'id="integrated-table-body"' in html
        assert 'id="integrated-html-card"' in html
        assert 'id="integrated-html-frame"' in html
        assert 'id="integrated-sections-card"' in html
        assert 'id="integrated-sections-list"' in html
        assert 'id="integrated-provenance-list"' in html
        assert 'loadExecutionResultsFromHistory' in js
        assert 'resolveHistoryResultContext' in js
        assert 'ensureIntegratedWorkbenchViews' in js
        assert 'getIntegratedWorkbenchFeature' in js
        assert 'clearIntegratedTemporaryFeatures' in js
        assert 'upsertIntegratedHistoryFeature' in js
        assert 'renderIntegratedProvenance' in js
        assert 'renderIntegratedSections' in js
        assert 'temporary' in js
        assert 'get_results_for_execution' in js
        assert "get_primer_results_for_execution" in js
        assert "loadPrimerResultsFromHistory" in js
        assert "get_multiplex_results_for_execution" in js
        assert "loadMultiplexResultsFromHistory" in js
        assert "get_targeted_seq_results_for_execution" in js
        assert "loadTargetedSeqResultsFromHistory" in js
        assert "renderIntegratedHtmlPreview" in js
        assert "localPathToFileUrl" in js
        assert "chartType === 'sunburst'" in js
        assert "chartType === 'funnel'" in js
        assert "wastewater_metagenomics_basic" in js
        assert "animal_metagenomics_basic" in js
        assert "需要输入文件" in js

        context_priority = js.find("context.featureId")
        payload_priority = js.find("payload.view.feature_id")
        assert context_priority != -1
        assert payload_priority != -1
        assert context_priority < payload_priority
        assert "featureId: 'fastp'" in js


class TestHomePageFlows:
    def test_home_page_is_intentionally_blank(self, qapp, temp_main_window):
        home_page = temp_main_window.home_page
        _flush_events(qapp)

        assert len(home_page._card_widgets) == 0
        assert home_page._proj_name_label.text() == ""
        assert home_page._stat_samples.text() == ""

    def test_continue_analysis_is_ignored_after_workbench_removal(self, qapp, temp_main_window):
        from core.data.sample_service import SampleService

        home_page = temp_main_window.home_page
        pm = temp_main_window._pm

        service = SampleService(pm.db)
        service.add_sample(
            name="sample_B",
            source="river",
            metadata={"r1": "C:/reads/sample_B_R1.fastq.gz", "r2": "C:/reads/sample_B_R2.fastq.gz"},
        )
        sample_id = pm.db.execute(
            "SELECT sample_id FROM samples WHERE name = ?",
            ("sample_B",),
        ).fetchone()[0]

        current_row = temp_main_window.sidebar.currentRow()
        home_page._on_continue_analysis(sample_id)
        _flush_events(qapp)

        assert temp_main_window.sidebar.currentRow() == current_row
        assert pm.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1

    def test_project_switch_refreshes_home_without_analysis_page(self, qapp, tmp_path: Path):
        from ui.main_window import MainWindow

        pm = ProjectManager(
            projects_root=tmp_path / "projects",
            index_path=tmp_path / "projects.json",
            last_project_path=tmp_path / "last_project.txt",
        )
        project_one = pm.create_project("project one", "first project")
        pm.open_project(project_one)
        _insert_sample(pm, "smp_alpha", "alpha", "C:/reads/alpha_R1.fastq.gz")

        project_two = pm.create_project("project two", "second project")
        pm.open_project(project_one)

        with patch("ui.main_window.DetectionPage", _make_fake_detection_page()):
            window = MainWindow(project_manager=pm)
        _flush_events(qapp)

        assert window.home_page._proj_name_label.text() == ""
        assert len(window.home_page._card_widgets) == 0

        pm.open_project(project_two)
        window._on_project_switched(project_two)
        _flush_events(qapp)

        assert window.home_page._proj_name_label.text() == ""
        assert len(window.home_page._card_widgets) == 0
        assert window.home_page._stat_samples.text() == ""

        window.close()
        window.deleteLater()
        _flush_events(qapp)
        pm.close()


class TestServiceLocatorStartup:
    def test_initialize_without_ssh(self, tmp_path: Path):
        from core.service_locator import ServiceLocator

        pm = ProjectManager(
            projects_root=tmp_path / "projects",
            index_path=tmp_path / "projects.json",
            last_project_path=tmp_path / "last_project.txt",
        )
        locator = ServiceLocator(ssh_service=None, project_manager=pm)
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
    schema["databases"] = {
        "db_root": "/data/databases",
        "overrides": {"blast_nt": "/remote/blast_nt"},
    }
    config.save_config(schema)

    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
        last_project_path=tmp_path / "last_project.txt",
    )
    project_id = pm.create_project("test_project", "ui verification")
    pm.open_project(project_id)

    with patch("ui.main_window.DetectionPage", _make_fake_detection_page()):
        window = MainWindow(project_manager=pm)
    _flush_events(qapp)

    assert "execution" not in config.get_config()

    settings_page = window.settings_page
    settings_page.ncbi_card.set_values(email="user@example.com")
    settings_page.save_config()
    _flush_events(qapp)

    saved = config.get_config()
    assert "execution" not in saved
    assert saved["databases"]["db_root"] == "/data/databases"
    assert saved["databases"]["overrides"]["blast_nt"] == "/remote/blast_nt"
    assert config.get_database_path("blast_nt") == "/remote/blast_nt"
    assert config.get_ncbi_setting("email") == "user@example.com"

    window.close()
    window.deleteLater()
    _flush_events(qapp)
    pm.close()


def test_linux_settings_web_install_is_deferred(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)

    card = LinuxSettingsCard()
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
    monkeypatch.setattr(card, "_make_ssh_run_fn", lambda: MagicMock())
    events = []
    card.install_task_event.connect(lambda payload: events.append(payload))

    finished = {"count": 0}

    class _Bridge:
        @staticmethod
        def emit_install_finished(_tool_id, _success):
            finished["count"] += 1

    card._bridge = _Bridge()

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
    assert finished["count"] == 0
    assert events == []

    card.close()


def test_linux_settings_reopen_running_dialog_attaches_without_resubmit(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard
    from PyQt6.QtCore import pyqtSignal
    from PyQt6.QtWidgets import QDialog

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card._tools = [{"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"}]
    card._installing_tool_ids.add("fastp")
    card._update_tool_install_snapshot("fastp", status="RUNNING", message="安装中……", log_text="existing log")

    submit_called = {"count": 0}
    monkeypatch.setattr(
        card,
        "_start_tool_install_submit",
        lambda *_args, **_kwargs: submit_called.__setitem__("count", submit_called["count"] + 1),
    )
    monkeypatch.setattr(card, "_ensure_tool_install_polling", lambda: None)

    dialogs = []

    class _FakeDialog(QDialog):
        install_requested = pyqtSignal(str)

        def __init__(self, tool, conda_executable="", parent=None):
            super().__init__(parent)
            self.tool = tool
            self.conda_executable = conda_executable
            self.parent = parent
            self.applied = []
            self.show_count = 0
            self.raise_count = 0
            self.activate_count = 0
            dialogs.append(self)

        def on_snapshot_updated(self, tool_id, snapshot):
            return None

        def apply_install_snapshot(self, snapshot):
            self.applied.append(snapshot)

        def show(self):
            self.show_count += 1

        def showNormal(self):
            self.show_count += 1

        def raise_(self):
            self.raise_count += 1

        def activateWindow(self):
            self.activate_count += 1

        def exec(self):  # pragma: no cover - must never be called
            raise AssertionError("exec should not be used")

    monkeypatch.setattr("ui.widgets.linux_settings_card.EnvInstallDialog", _FakeDialog)

    card._do_install_tool({"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"})
    card._do_install_tool({"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"})

    assert len(dialogs) == 1
    assert dialogs[0].conda_executable == card._conda_executable
    assert dialogs[0].applied and dialogs[0].applied[0].get("status") == "RUNNING"
    assert dialogs[0].show_count == 2
    assert dialogs[0].raise_count == 2
    assert dialogs[0].activate_count == 2
    assert submit_called["count"] == 0
    card.close()


def test_linux_settings_dialog_show_error_keeps_running_install(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard
    from PyQt6.QtCore import pyqtSignal
    from PyQt6.QtWidgets import QDialog

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card._conda_executable = "/home/user/.h2ometa/conda/bin/conda"
    card._tools = [{"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"}]
    card._installing_tool_ids.add("fastp")
    card._update_tool_install_snapshot("fastp", status="RUNNING", message="安装中……")

    finished = {"count": 0}
    events = []
    card.install_task_event.connect(lambda payload: events.append(payload))

    class _Bridge:
        @staticmethod
        def emit_install_finished(_tool_id, _success):
            finished["count"] += 1

    card._bridge = _Bridge()

    critical_calls = []
    monkeypatch.setattr(
        "ui.widgets.linux_settings_card.QMessageBox.critical",
        lambda *args: critical_calls.append(args),
    )

    class _FakeDialog(QDialog):
        install_requested = pyqtSignal(str)

        def __init__(self, tool, conda_executable="", parent=None):
            super().__init__(parent)
            self.tool = tool
            self.conda_executable = conda_executable
            self.parent = parent

        def on_snapshot_updated(self, tool_id, snapshot):
            return None

        def apply_install_snapshot(self, snapshot):
            return None

        def show(self):
            raise RuntimeError("show boom")

    monkeypatch.setattr("ui.widgets.linux_settings_card.EnvInstallDialog", _FakeDialog)

    card._do_install_tool({"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"})

    assert "fastp" in card._installing_tool_ids
    assert finished["count"] == 0
    assert events == []
    assert card.status_label.text() == "安装窗口异常关闭，后台任务仍在继续: fastp"
    assert len(critical_calls) == 1

    card.close()


def test_linux_settings_dialog_cleanup_after_close(qapp, monkeypatch):
    from ui.widgets.linux_settings_card import LinuxSettingsCard
    from PyQt6.QtCore import pyqtSignal
    from PyQt6.QtWidgets import QDialog

    monkeypatch.setattr(LinuxSettingsCard, "_build_tool_env_web_view", lambda self, layout: None)
    card = LinuxSettingsCard()
    card._tools = [{"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"}]

    class _FakeDialog(QDialog):
        install_requested = pyqtSignal(str)

        def __init__(self, tool, conda_executable="", parent=None):
            super().__init__(parent)
            self.tool = tool
            self.conda_executable = conda_executable

        def on_snapshot_updated(self, tool_id, snapshot):
            return None

        def apply_install_snapshot(self, snapshot):
            return None

        def show(self):
            return None

        def raise_(self):
            return None

        def activateWindow(self):
            return None

    monkeypatch.setattr("ui.widgets.linux_settings_card.EnvInstallDialog", _FakeDialog)

    card._do_install_tool({"id": "fastp", "name": "fastp", "install_cmd": "conda create -n fastp_env -y"})

    assert "fastp" in card._tool_install_dialogs
    dialog = card._tool_install_dialogs["fastp"]
    dialog.reject()
    qapp.processEvents()

    assert "fastp" not in card._tool_install_dialogs
    card.close()
