"""ServiceLocator 单元测试 — 验证信号链路完整性和模块连接。"""

import sqlite3
import time
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QObject

from core.data_registry import DataRegistry
from core.project_manager import ProjectInfo, ProjectManager, _SCHEMA_SQL
from core.service_locator import ServiceLocator


# ── Fake / Mock ──────────────────────────────────────────


class FakeSSHService:
    """模拟 SSH 服务"""

    def __init__(self) -> None:
        self.commands_run: list[str] = []
        self.is_connected = True

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        self.commands_run.append(cmd)
        return (0, "", "")

    def upload(self, local_path: str, remote_path: str) -> None:
        pass


class FakeProjectManager:
    """模拟 ProjectManager，支持 project_opened 信号"""

    def __init__(self, conn: sqlite3.Connection, project: ProjectInfo) -> None:
        self._conn = conn
        self._project = project
        self._callbacks: list = []

    @property
    def current_project(self) -> Optional[ProjectInfo]:
        return self._project

    @property
    def db(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        pass


# ── Fixtures ──────────────────────────────────────────────


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
        name="ServiceLocator 测试",
        description="",
        created_at=time.time(),
        status="active",
        remote_base="/h2ometa/projects/proj_svc_test01",
    )


@pytest.fixture()
def ssh() -> FakeSSHService:
    return FakeSSHService()


# ── 测试 ─────────────────────────────────────────────────


class TestServiceLocatorInitialization:
    """初始化测试"""

    def test_initialize_scans_plugins(self, tmp_path) -> None:
        """initialize() 应扫描 plugins 目录"""
        # 创建空 plugins 目录
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        count = locator.initialize()
        assert count == 0  # 空目录

    def test_plugin_registry_accessible(self, tmp_path) -> None:
        """初始化后 plugin_registry 应可访问"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()
        assert locator.plugin_registry is not None

    def test_job_queue_accessible(self, tmp_path) -> None:
        """job_queue 应可访问"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()
        assert locator.job_queue is not None

    def test_job_monitor_accessible(self, tmp_path) -> None:
        """job_monitor 应可访问"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()
        assert locator.job_monitor is not None


class TestServiceLocatorSSH:
    """SSH 相关测试"""

    def test_ssh_service_hot_swap(self, ssh: FakeSSHService, tmp_path) -> None:
        """应支持 SSH 服务热切换"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        assert locator.ssh_service is None
        locator.ssh_service = ssh
        assert locator.ssh_service is ssh


class TestServiceLocatorProjectSwitch:
    """项目切换测试"""

    def test_data_registry_rebuilt_on_project(
        self, db_conn, project, tmp_path,
    ) -> None:
        """项目打开后 data_registry 应被重建"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()

        # 有项目打开，所以 data_registry 应已创建
        assert locator.data_registry is not None
        assert locator.tool_engine is not None


class TestServiceLocatorSignalChain:
    """信号链路测试"""

    def test_execution_context_registration(self, tmp_path) -> None:
        """执行上下文应正确存储"""
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

    def test_on_completed_emits_signal(
        self, db_conn, project, ssh, tmp_path,
    ) -> None:
        """_on_completed 应发射 execution_completed 信号"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            ssh_service=ssh,  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()

        # 注册上下文
        locator.register_execution_context(
            execution_id="exec_test002",
            command="echo done",
            descriptor={"id": "test", "outputs": []},
            sample_id="smp_001",
            output_dir="/output",
            task_dir="/tmp/task",
        )

        # 在 executions 表中插入记录（on_job_completed 需要更新状态）
        db_conn.execute(
            "INSERT INTO samples (sample_id, name) VALUES (?, ?)",
            ("smp_001", "测试"),
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

    def test_on_failed_emits_signal(
        self, db_conn, project, ssh, tmp_path,
    ) -> None:
        """_on_failed 应发射 execution_failed 信号"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        pm = FakeProjectManager(db_conn, project)
        locator = ServiceLocator(
            ssh_service=ssh,  # type: ignore[arg-type]
            plugins_dir=plugins_dir,
            project_manager=pm,  # type: ignore[arg-type]
        )
        locator.initialize()

        # 插入测试数据
        db_conn.execute(
            "INSERT INTO samples (sample_id, name) VALUES (?, ?)",
            ("smp_002", "测试2"),
        )
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("exec_fail001", "smp_002", "test", "{}", "running", time.time()),
        )
        db_conn.commit()

        received: list[tuple[str, str]] = []
        locator.execution_failed.connect(
            lambda eid, err: received.append((eid, err))
        )

        locator._on_failed("exec_fail001", "内存不足")
        assert len(received) == 1
        assert received[0] == ("exec_fail001", "内存不足")


class TestServiceLocatorShutdown:
    """关闭测试"""

    def test_shutdown_does_not_error(self, tmp_path) -> None:
        """shutdown() 应安全执行"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()
        locator.shutdown()


class TestServiceLocatorCondaExecutable:
    """conda_executable 传播测试"""

    def test_conda_executable_default_empty(self, tmp_path) -> None:
        """conda_executable 默认为空字符串"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()
        assert locator.conda_executable == ""

    def test_conda_executable_setter_updates(self, tmp_path) -> None:
        """设置 conda_executable 后应可读取"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        locator.conda_executable = "/home/user/miniconda3/bin/conda"
        assert locator.conda_executable == "/home/user/miniconda3/bin/conda"

    def test_conda_executable_propagates_to_engine(
        self, db_conn, project, ssh, tmp_path,
    ) -> None:
        """设置 conda_executable 后应触发 engine 重建并传播"""
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

        # 设置 conda_executable 触发 engine 重建
        locator.conda_executable = "/opt/conda/bin/conda"
        assert locator.tool_engine._conda_executable == "/opt/conda/bin/conda"

    def test_conda_executable_none_converts_to_empty(self, tmp_path) -> None:
        """设置 None 应转为空字符串"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        locator = ServiceLocator(plugins_dir=plugins_dir)
        locator.initialize()

        locator.conda_executable = None  # type: ignore[assignment]
        assert locator.conda_executable == ""
