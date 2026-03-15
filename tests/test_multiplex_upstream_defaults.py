from pathlib import Path

from core.data.project_manager import ProjectManager
from core.execution.tool_bridge_service import ToolBridgeService


def _make_pm(tmp_path: Path) -> ProjectManager:
    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
    )
    project_id = pm.create_project("multiplex upstream")
    pm.open_project(project_id)
    return pm


def test_resolve_default_upstream_inputs_uses_latest_primer_execution(tmp_path: Path) -> None:
    pm = _make_pm(tmp_path)
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_primer", "primer sample", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, status, triggered_by, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_primer", "smp_primer", "primer_design", "1.0", "{}", "completed", "manual", 1.0, 2.0),
    )
    pm.db.execute(
        "INSERT INTO data_items (data_id, sample_id, file_path, data_type, tier, produced_by, created_at, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("dat_input", "smp_primer", "/remote/raw/demo.fasta", "archive", "raw", None, 1.0, "{}"),
    )
    pm.db.execute(
        "INSERT INTO execution_io (execution_id, data_id, direction) VALUES (?, ?, ?)",
        ("exec_primer", "dat_input", "input"),
    )
    pm.db.execute(
        "INSERT INTO data_items (data_id, sample_id, file_path, data_type, tier, produced_by, created_at, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("dat_output", "smp_primer", "/remote/intermediate/primer_result.txt", "tsv", "result", "exec_primer", 2.0, "{}"),
    )
    pm.db.execute(
        "INSERT INTO execution_io (execution_id, data_id, direction) VALUES (?, ?, ?)",
        ("exec_primer", "dat_output", "output"),
    )
    pm.db.commit()

    class _Locator:
        project_manager = pm

    service = ToolBridgeService(service_locator=_Locator())
    params = service.resolve_default_upstream_inputs("multiplex_primer_panel", {})

    assert params["primer_candidates"] == "/remote/intermediate/primer_result.txt"
    assert params["genomes_bundle"] == "/remote/raw/demo.fasta"
    pm.close()


def test_import_inputs_accepts_remote_paths_without_upload(tmp_path: Path) -> None:
    pm = _make_pm(tmp_path)

    class _Registry:
        def __init__(self):
            self.calls = []

        def register_input(self, **kwargs):
            self.calls.append(kwargs)
            return "dat_remote"

    class _SSH:
        is_connected = True

    service = ToolBridgeService()
    registry = _Registry()
    service._get_data_registry = lambda: registry  # type: ignore[method-assign]
    service._get_ssh_service = lambda: _SSH()  # type: ignore[method-assign]

    descriptor = {
        "inputs": [
            {"name": "primer_candidates", "type": "tsv", "required": True},
            {"name": "genomes_bundle", "type": "archive", "required": True},
        ]
    }
    params = {
        "primer_candidates": "/remote/intermediate/primer_result.txt",
        "genomes_bundle": "/remote/raw/demo.fasta",
    }

    data_ids = service.import_inputs(pm, "smp_demo", descriptor, params)

    assert data_ids == ["dat_remote", "dat_remote"]
    assert registry.calls[0]["file_path"] == "/remote/intermediate/primer_result.txt"
    assert registry.calls[1]["file_path"] == "/remote/raw/demo.fasta"
    pm.close()
