"""ServiceLocator unit tests."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

import pytest

from core.data.project_manager import ProjectInfo, _SCHEMA_SQL
from core.service_locator import ServiceLocator


class FakeSSHService:
    """Minimal SSH test double."""

    def __init__(self) -> None:
        self.commands_run: list[str] = []
        self.is_connected = True

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        self.commands_run.append(cmd)
        return (0, "", "")

    def upload(self, local_path: str, remote_path: str) -> None:
        pass


class FakeProjectManager:
    """Minimal ProjectManager test double."""

    def __init__(self, conn: sqlite3.Connection, project: ProjectInfo) -> None:
        self._conn = conn
        self._project = project

    @property
    def current_project(self) -> Optional[ProjectInfo]:
        return self._project

    @property
    def db(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        pass


class ImmediateTaskRunner:
    """TaskRunner stand-in that records submitted work without threading."""

    def __init__(self) -> None:
        self.submissions: list[tuple[Any, tuple[Any, ...], str]] = []
        self.wait_timeout: int | None = None
        self.task_succeeded = _FakeSignal()
        self.task_failed = _FakeSignal()

    def submit(self, fn, *args, task_id: str) -> None:
        self.submissions.append((fn, args, task_id))

    def wait_for_done(self, timeout_ms: int = 30000) -> bool:
        self.wait_timeout = timeout_ms
        return True


class _FakeSignal:
    def disconnect(self, callback: Any) -> None:
        return None


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        if kwargs:
            self.calls.append((args, kwargs))
        else:
            self.calls.append(args)


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    return conn


@pytest.fixture()
def project() -> ProjectInfo:
    return ProjectInfo(
        project_id="proj_svc_test01",
        name="ServiceLocator test",
        description="",
        created_at=time.time(),
        status="active",
        remote_base="/h2ometa/projects/proj_svc_test01",
    )


@pytest.fixture()
def ssh() -> FakeSSHService:
    return FakeSSHService()


class TestServiceLocatorInitialization:
    def test_initialize_scans_plugins(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        count = locator.initialize()

        assert count == 0

    def test_plugin_registry_accessible(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        assert locator.plugin_registry is not None

    def test_job_queue_accessible(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        assert locator.job_queue is not None


class TestServiceLocatorSSH:
    def test_ssh_service_hot_swap(self, ssh: FakeSSHService, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        assert locator.ssh_service is None
        locator.ssh_service = ssh
        assert locator.ssh_service is ssh


class TestServiceLocatorProjectSwitch:
    def test_data_registry_rebuilt_on_project(self, db_conn, project, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()

        assert locator.data_registry is not None
        assert locator.tool_engine is not None


class TestServiceLocatorSignalChain:
    def test_execution_context_registration(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        locator.register_execution_context(
            execution_id="exec_test001",
            command="echo hello",
            descriptor={"id": "test", "outputs": []},
            sample_id="smp_001",
            output_dir="/output",
            task_dir="/tmp/task",
        )

        assert "exec_test001" in locator._execution_ctx

    def test_on_dispatch_submits_to_task_runner(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(
            ssh_service=FakeSSHService(),  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
        )
        locator.initialize()
        runner = ImmediateTaskRunner()
        locator._task_runner = runner  # type: ignore[assignment]

        locator.register_execution_context(
            execution_id="exec_dispatch001",
            command="echo hello",
            descriptor={"id": "test", "outputs": []},
            sample_id="smp_001",
            output_dir="/output",
            task_dir="/tmp/task",
        )

        locator._on_dispatch("exec_dispatch001")

        assert len(runner.submissions) == 1
        fn, args, task_id = runner.submissions[0]
        assert fn == locator._dispatch_job
        assert args[0] == "exec_dispatch001"
        assert task_id == "exec_dispatch001"

    def test_on_dispatch_without_ssh_is_ignored(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        locator.register_execution_context(
            execution_id="exec_dispatch_missing_ssh",
            command="echo hello",
            descriptor={"id": "test", "outputs": []},
            sample_id="smp_001",
            output_dir="/output",
            task_dir="/tmp/task",
        )

        locator._on_dispatch("exec_dispatch_missing_ssh")

        assert locator.get_task_dir("exec_dispatch_missing_ssh") is None

    def test_on_dispatch_submitted_starts_waiting(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        ssh = FakeSSHService()
        locator = ServiceLocator(
            ssh_service=ssh,  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
        )
        locator.initialize()
        locator.register_execution_context(
            execution_id="exec_dispatch002",
            command="echo hello",
            descriptor={"id": "test", "outputs": []},
            sample_id="smp_001",
            output_dir="/output",
            task_dir="/tmp/task",
        )
        recorder = Recorder()
        locator._job_dispatcher.start_waiting = recorder  # type: ignore[assignment]

        locator._on_dispatch_submitted(
            "exec_dispatch002",
            {
                "execution_id": "exec_dispatch002",
                "job_id": "h2o_exec_dispatch002",
                "task_dir": "/tmp/task",
            },
        )

        assert recorder.calls == [(
            (),
            {
                "ssh_service": ssh,
                "execution_id": "exec_dispatch002",
                "job_id": "h2o_exec_dispatch002",
                "task_dir": "/tmp/task",
            },
        )]
        assert locator.get_task_dir("exec_dispatch002") == "/tmp/task"

    def test_on_dispatch_failed_routes_to_on_failed(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(
            ssh_service=FakeSSHService(),  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
        )
        locator.initialize()
        recorder = Recorder()
        locator._on_failed = recorder  # type: ignore[assignment]

        locator._on_dispatch_failed("exec_dispatch003", "boom")

        assert recorder.calls == [("exec_dispatch003", "boom")]

    def test_on_dispatch_failed_ignored_during_shutdown(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(
            ssh_service=FakeSSHService(),  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
        )
        locator.initialize()
        recorder = Recorder()
        locator._on_failed = recorder  # type: ignore[assignment]
        locator._shutting_down = True

        locator._on_dispatch_failed("exec_dispatch004", "boom")

        assert recorder.calls == []

    def test_on_completed_emits_signal(self, db_conn, project, ssh, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            ssh_service=ssh,  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()
        locator.register_execution_context(
            execution_id="exec_test002",
            command="echo done",
            descriptor={"id": "test", "outputs": []},
            sample_id="smp_001",
            output_dir="/output",
            task_dir="/tmp/task",
        )

        db_conn.execute(
            "INSERT INTO samples (sample_id, name) VALUES (?, ?)",
            ("smp_001", "test"),
        )
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("exec_test002", "smp_001", "test", "{}", "running", time.time()),
        )
        db_conn.commit()

        received: list[str] = []
        locator.execution_completed.connect(received.append)

        locator._on_completed("exec_test002")

        assert received == ["exec_test002"]

    def test_on_failed_emits_signal(self, db_conn, project, ssh, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            ssh_service=ssh,  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()

        db_conn.execute(
            "INSERT INTO samples (sample_id, name) VALUES (?, ?)",
            ("smp_002", "test2"),
        )
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("exec_fail001", "smp_002", "test", "{}", "running", time.time()),
        )
        db_conn.commit()

        received: list[tuple[str, str]] = []
        locator.execution_failed.connect(lambda eid, err: received.append((eid, err)))

        locator.register_execution_context(
            execution_id="exec_fail001",
            command="test cmd",
            descriptor={"id": "test"},
            sample_id="smp_002",
            output_dir="/tmp/test",
            task_dir="/tmp/test",
        )

        locator._on_failed("exec_fail001", "内存不足")

        assert received == [("exec_fail001", "内存不足")]

    def test_resume_execution_waiting_starts_waiter(self, db_conn, project, ssh, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            ssh_service=ssh,  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()

        start_calls = Recorder()
        locator._job_dispatcher.start_waiting = start_calls  # type: ignore[assignment]
        locator._plugin_registry.get_descriptor = lambda _tool_id: {"id": "fastp", "outputs": []}  # type: ignore[assignment]

        ok = locator.resume_execution_waiting(
            execution_id="exec_resume_001",
            sample_id="smp_001",
            tool_id="fastp",
            task_dir="/remote/task/exec_resume_001",
        )

        assert ok is True
        assert start_calls.calls
        assert locator.get_task_dir("exec_resume_001") == "/remote/task/exec_resume_001"

    def test_resume_execution_waiting_skips_when_already_waiting(self, db_conn, project, ssh, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            ssh_service=ssh,  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()
        locator._job_dispatcher.is_waiting = lambda _execution_id: True  # type: ignore[assignment]

        ok = locator.resume_execution_waiting(
            execution_id="exec_resume_002",
            sample_id="smp_001",
            tool_id="fastp",
            task_dir="/remote/task/exec_resume_002",
        )

        assert ok is False

    def test_on_completed_ignores_non_active_execution(self, db_conn, project, ssh, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            ssh_service=ssh,  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()

        db_conn.execute(
            "INSERT INTO samples (sample_id, name) VALUES (?, ?)",
            ("smp_003", "test3"),
        )
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("exec_done_ignored", "smp_003", "test", "{}", "completed", time.time(), time.time()),
        )
        db_conn.commit()

        received: list[str] = []
        locator.execution_completed.connect(received.append)
        locator._on_completed("exec_done_ignored")
        assert received == []


class TestServiceLocatorShutdown:
    def test_shutdown_does_not_error(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()
        locator.shutdown()

    def test_shutdown_waits_for_task_runner(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()
        runner = ImmediateTaskRunner()
        locator._task_runner = runner  # type: ignore[assignment]

        locator.shutdown()

        assert runner.wait_timeout == 30000


class TestServiceLocatorCondaExecutable:
    def test_conda_executable_default_empty(self, tmp_path, monkeypatch) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        monkeypatch.setattr(
            "core.service_locator.get_config",
            lambda: {"linux": {"conda_executable": ""}},
        )

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        assert locator.conda_executable == ""

    def test_initialize_loads_managed_conda_from_config(self, tmp_path, monkeypatch) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        managed = "/home/user/.h2ometa/conda/bin/conda"
        monkeypatch.setattr(
            "core.service_locator.get_config",
            lambda: {"linux": {"conda_executable": managed}},
        )

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        assert locator.conda_executable == managed

    def test_initialize_ignores_non_managed_conda_from_config(self, tmp_path, monkeypatch) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        monkeypatch.setattr(
            "core.service_locator.get_config",
            lambda: {"linux": {"conda_executable": "/opt/conda/bin/conda"}},
        )

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        assert locator.conda_executable == ""

    def test_conda_executable_setter_updates(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        locator.conda_executable = "/home/user/miniconda3/bin/conda"

        assert locator.conda_executable == "/home/user/miniconda3/bin/conda"

    def test_conda_executable_propagates_to_engine(self, db_conn, project, ssh, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            ssh_service=ssh,  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()

        assert locator.tool_engine is not None

        locator.conda_executable = "/opt/conda/bin/conda"

        assert locator.tool_engine._conda_executable == "/opt/conda/bin/conda"

    def test_conda_executable_none_converts_to_empty(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        locator.conda_executable = None  # type: ignore[assignment]

        assert locator.conda_executable == ""
