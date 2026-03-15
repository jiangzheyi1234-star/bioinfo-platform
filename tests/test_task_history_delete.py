import time
from pathlib import Path

import pytest

from core.data.project_manager import ProjectManager
from core.execution.tool_bridge_service import ToolBridgeService


@pytest.fixture()
def pm(tmp_path: Path) -> ProjectManager:
    manager = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
    )
    project_id = manager.create_project("history delete test")
    manager.open_project(project_id)
    yield manager
    manager.close()


def _insert_sample(pm: ProjectManager, sample_id: str, name: str) -> None:
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        (sample_id, name, "test", "{}"),
    )
    pm.db.commit()


def _insert_execution(
    pm: ProjectManager,
    execution_id: str,
    sample_id: str,
    *,
    status: str,
    archived_at: float | None = None,
) -> None:
    now = time.time()
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, tool_version, parameters, "
        "status, triggered_by, created_at, completed_at, archived_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            execution_id,
            sample_id,
            "primer_design",
            "1.0.0",
            '{"mode":"quick"}',
            status,
            "manual",
            now,
            now if status == "completed" else None,
            archived_at,
        ),
    )
    pm.db.commit()


def _make_service(pm: ProjectManager) -> ToolBridgeService:
    class _ServiceLocator:
        project_manager = pm

    return ToolBridgeService(service_locator=_ServiceLocator())


def test_delete_execution_history_archives_and_hides_record(pm: ProjectManager) -> None:
    _insert_sample(pm, "smp_1", "sample one")
    _insert_execution(pm, "exec_1", "smp_1", status="completed")
    service = _make_service(pm)

    history_before = service.get_execution_history()
    assert [row["execution_id"] for row in history_before] == ["exec_1"]

    result = service.delete_execution_history("exec_1")

    assert result["status"] == "ok"
    archived_at = pm.db.execute(
        "SELECT archived_at FROM executions WHERE execution_id = ?",
        ("exec_1",),
    ).fetchone()["archived_at"]
    assert archived_at is not None
    assert service.get_execution_history() == []


def test_delete_execution_history_rejects_running_record(pm: ProjectManager) -> None:
    _insert_sample(pm, "smp_2", "sample two")
    _insert_execution(pm, "exec_running", "smp_2", status="running")
    service = _make_service(pm)

    result = service.delete_execution_history("exec_running")

    assert result["status"] == "error"
    assert "不能删除" in result["message"]
    archived_at = pm.db.execute(
        "SELECT archived_at FROM executions WHERE execution_id = ?",
        ("exec_running",),
    ).fetchone()["archived_at"]
    assert archived_at is None
