from __future__ import annotations

import time
from pathlib import Path

from core.data.project_manager import ProjectManager
from core.execution.tool_bridge_service import ToolBridgeService


class _FakeSSH:
    is_connected = True

    def __init__(self) -> None:
        self.calls = 0

    def run(self, cmd: str, timeout: int = 10):
        self.calls += 1
        if "__STATUS__" in cmd and "__EXIT__" in cmd and "__HEARTBEAT__" in cmd:
            hb = int(time.time()) - 5
            return 0, f"__STATUS__\nRUNNING\n__EXIT__\n\n__HEARTBEAT__\n{hb}\n", ""
        if "screen -ls" in cmd:
            return 0, "", ""
        if "tail -n 20" in cmd:
            return 0, "line1\nline2\n", ""
        return 1, "", ""


def test_parse_remote_status_block() -> None:
    parsed = ToolBridgeService._parse_remote_status_block(
        "__STATUS__\nDONE\n__EXIT__\n0\n__HEARTBEAT__\n12345\n"
    )
    assert parsed["status"] == "DONE"
    assert parsed["exit"] == "0"
    assert parsed["heartbeat"] == "12345"


def test_get_execution_remote_status_uses_aggregated_status_block(tmp_path: Path) -> None:
    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
        last_project_path=tmp_path / "last_project.txt",
    )
    project_id = pm.create_project("status project")
    pm.open_project(project_id)
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_demo", "demo", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, parameters, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("exec_demo", "smp_demo", "fastp", "{}", "running", time.time()),
    )
    pm.db.commit()

    class _Locator:
        project_manager = pm
        ssh_service = _FakeSSH()

    service = ToolBridgeService(service_locator=_Locator())
    payload = service.get_execution_remote_status("exec_demo")

    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["remote_status"] == "RUNNING"
    assert data["screen_running"] is True
    assert data["log_tail"].startswith("line1")
    assert isinstance(data["heartbeat_age_sec"], int)
    pm.close()


def test_get_execution_remote_status_uses_cache_within_ttl(tmp_path: Path) -> None:
    pm = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
        last_project_path=tmp_path / "last_project.txt",
    )
    project_id = pm.create_project("status cache project")
    pm.open_project(project_id)
    pm.db.execute(
        "INSERT INTO samples (sample_id, name, source, metadata) VALUES (?, ?, ?, ?)",
        ("smp_cache", "cache", "test", "{}"),
    )
    pm.db.execute(
        "INSERT INTO executions (execution_id, sample_id, tool_id, parameters, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("exec_cache", "smp_cache", "fastp", "{}", "running", time.time()),
    )
    pm.db.commit()

    ssh = _FakeSSH()

    class _Locator:
        project_manager = pm
        ssh_service = ssh

    service = ToolBridgeService(service_locator=_Locator())
    first = service.get_execution_remote_status("exec_cache")
    first_calls = ssh.calls
    second = service.get_execution_remote_status("exec_cache")

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert first_calls > 0
    assert ssh.calls == first_calls
    pm.close()
