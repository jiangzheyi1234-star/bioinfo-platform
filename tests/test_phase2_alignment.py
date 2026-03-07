import json
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

import config
from config import default_settings_schema
from core.data_registry import DataRegistry
from ui.pages.analysis_page import AnalysisPage
from ui.pages.settings_page import SettingsPage
from ui.widgets.input_data_selector import InputDataSelector


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture()
def local_tmp_dir() -> Path:
    root = Path.cwd() / ".pytest_tmp"
    root.mkdir(parents=True, exist_ok=True)

    case_dir = root / f"case_{uuid.uuid4().hex}"
    case_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield case_dir
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def _legacy_config() -> dict:
    return {
        "server_ip": "10.1.2.3",
        "ssh_user": "legacy_user",
        "ssh_pwd": "legacy_pwd",
        "remote_db": "/legacy/db",
        "blast_bin": "/legacy/bin/blastn",
    }


def test_get_config_no_longer_reads_legacy_schema(local_tmp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = local_tmp_dir / "config.json"
    config_path.write_text(json.dumps(_legacy_config(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config, "_CONFIG_PATH", config_path)

    loaded = config.get_config()
    defaults = default_settings_schema()

    assert loaded["version"] == 2
    assert loaded["ssh"]["host"] == defaults["ssh"]["host"]
    assert loaded["ssh"]["host"] != "10.1.2.3"


def test_settings_page_migrate_confirm_yes(qapp, local_tmp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = local_tmp_dir / "config.json"
    legacy = _legacy_config()
    config_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    infos: list[tuple[str, str]] = []

    monkeypatch.setattr(config, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, text: infos.append((title, text)) or QMessageBox.StandardButton.Ok,
    )

    page = SettingsPage()

    raw = config.load_raw_config()
    assert raw["version"] == 2
    assert raw["ssh"]["host"] == "10.1.2.3"

    backups = list(local_tmp_dir.glob("config.legacy.*.bak.json"))
    assert len(backups) == 1
    assert "server_ip" not in raw
    assert any(title == "迁移完成" for title, _ in infos)

    page.close()


def test_settings_page_migrate_confirm_no(qapp, local_tmp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = local_tmp_dir / "config.json"
    legacy = _legacy_config()
    config_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    infos: list[tuple[str, str]] = []

    monkeypatch.setattr(config, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, text: infos.append((title, text)) or QMessageBox.StandardButton.Ok,
    )

    page = SettingsPage()

    raw_text = config_path.read_text(encoding="utf-8")
    assert json.loads(raw_text) == legacy

    defaults = default_settings_schema()
    assert page.ssh_card.get_values()["server_ip"] == defaults["ssh"]["host"]
    assert any(title == "未迁移" for title, _ in infos)

    page.close()


def test_analysis_page_renders_from_yaml_without_python_changes(
    qapp,
    local_tmp_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    yaml_path = local_tmp_dir / "analysis_paths.yaml"
    yaml_path.write_text(
        """
paths:
  read_based:
    name: "测试路径"
    stages:
      - tool_id: demo_tool
        input_type: fastq
        required: true
""".strip(),
        encoding="utf-8",
    )

    descriptor = {
        "id": "demo_tool",
        "name": "Demo Tool",
        "category": "demo",
        "parameters": [
            {"name": "threads", "type": "int", "default": 2, "label": "线程数"},
        ],
        "databases": [
            {"param_name": "db", "required": True},
        ],
    }

    class _Signal:
        def connect(self, _slot):
            return None

    class _Registry:
        def get_descriptor(self, tool_id: str):
            assert tool_id == "demo_tool"
            return descriptor

    class _ProjectManager:
        current_project = None

    class _Locator:
        plugin_registry = _Registry()
        execution_completed = _Signal()
        execution_failed = _Signal()
        ssh_service = None
        project_manager = _ProjectManager()

    class _MainWindow:
        service_locator = _Locator()

    monkeypatch.setattr(AnalysisPage, "_analysis_paths_file", lambda self: yaml_path)

    page = AnalysisPage(main_window=_MainWindow())

    assert len(page._pipeline_stages) == 1
    assert page._pipeline_stages[0]["tool_id"] == "demo_tool"
    assert "threads" in page._param_widgets["demo_tool"]
    assert "db" in page._db_widgets["demo_tool"]

    page.close()


def test_input_selector_recommended_sort_uses_execution_tool_id() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript(
        """
        CREATE TABLE samples (
            sample_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source TEXT,
            metadata TEXT
        );
        CREATE TABLE executions (
            execution_id TEXT PRIMARY KEY,
            sample_id TEXT,
            tool_id TEXT NOT NULL,
            tool_version TEXT,
            parameters TEXT NOT NULL,
            status TEXT NOT NULL,
            triggered_by TEXT,
            created_at REAL NOT NULL,
            completed_at REAL,
            error TEXT,
            retry_count INTEGER DEFAULT 0,
            retry_of TEXT,
            remote_job_id TEXT
        );
        CREATE TABLE data_items (
            data_id TEXT PRIMARY KEY,
            sample_id TEXT,
            file_path TEXT NOT NULL,
            data_type TEXT NOT NULL,
            tier TEXT NOT NULL,
            produced_by TEXT,
            created_at REAL NOT NULL,
            metadata TEXT
        );
        """
    )

    conn.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("s1", "sample1", None, "{}"),
    )

    conn.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("e_fastp", "s1", "fastp", "0.1", "{}", "completed", "manual", 1000.0),
    )
    conn.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("e_k2", "s1", "kraken2", "0.1", "{}", "completed", "manual", 1001.0),
    )

    conn.execute(
        "INSERT INTO data_items (data_id, sample_id, file_path, data_type, tier, produced_by, created_at, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("d_fastp", "s1", "/tmp/fastp.fq.gz", "fastq", "intermediate", "e_fastp", 1000.0, "{}"),
    )
    conn.execute(
        "INSERT INTO data_items (data_id, sample_id, file_path, data_type, tier, produced_by, created_at, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("d_k2", "s1", "/tmp/k2.fq.gz", "fastq", "intermediate", "e_k2", 1002.0, "{}"),
    )
    conn.commit()

    registry = DataRegistry(conn)
    items = registry.find_compatible("s1", "fastq")

    sorted_items, tool_map = InputDataSelector._sort_by_recommendation(items, ["fastp"], registry)

    assert sorted_items[0].produced_by == "e_fastp"
    assert sorted_items[1].produced_by == "e_k2"
    assert tool_map["e_fastp"] == "fastp"

def test_helper_reads_v2_schema_after_save(local_tmp_dir: Path) -> None:
    schema = default_settings_schema()
    schema["execution"]["max_concurrent"] = 6
    schema["execution"]["poll_interval"] = 9
    schema["execution"]["screen_check_timeout"] = 17
    schema["databases"]["blast_nt"] = "/db/blast_nt"
    schema["ncbi"]["email"] = "user@example.com"

    original_path = config._CONFIG_PATH
    try:
        config._CONFIG_PATH = local_tmp_dir / "config.json"
        config.save_config(schema)

        assert config.get_runtime_setting("max_concurrent") == 6
        assert config.get_runtime_setting("poll_interval") == 9
        assert config.get_runtime_setting("screen_check_timeout") == 17
        assert config.get_database_path("blast_nt") == "/db/blast_nt"
        assert config.get_ncbi_setting("email") == "user@example.com"
    finally:
        config._CONFIG_PATH = original_path



