"""ToolEngine + DataImporter + CommandBuilder 单元测试

所有外部依赖（SSH、PluginRegistry、ProjectManager、JobQueue）均使用 mock。
SQLite 使用 :memory: 数据库。
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, call, patch

import pytest
from PyQt6.QtCore import QObject

from core.data_registry import DataRegistry
from core.project_manager import ProjectInfo, _SCHEMA_SQL
from core.data_importer import DataImporter
from core.command_builder import CommandBuilder, CommandBuildError
from core.tool_engine import ExecutionRecord, ToolEngine


# ── 测试用 Mock / Fake 对象 ──────────────────────────────


class FakeSSHService:
    """模拟 SSH 服务"""

    def __init__(self) -> None:
        self.commands_run: list[str] = []
        self.uploads: list[tuple[str, str]] = []

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        self.commands_run.append(cmd)
        # 模拟文件存在性检查: test -f 总是返回成功
        return (0, "", "")

    def upload(self, local_path: str, remote_path: str) -> None:
        self.uploads.append((local_path, remote_path))


class FakeJobQueue:
    """模拟 JobQueue"""

    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []

    def submit(
        self,
        execution_id: str,
        command: str,
        callback_on_start: Any = None,
        metadata: Any = None,
    ) -> str:
        self.submitted.append({
            "execution_id": execution_id,
            "command": command,
            "metadata": metadata,
        })
        return "started"


class FakeProjectManager:
    """模拟 ProjectManager"""

    def __init__(self, conn: sqlite3.Connection, project: ProjectInfo) -> None:
        self._conn = conn
        self._project = project

    @property
    def current_project(self) -> Optional[ProjectInfo]:
        return self._project

    @property
    def db(self) -> sqlite3.Connection:
        return self._conn


# ── 示例 tool.yaml descriptor ─────────────────────────────

FASTP_DESCRIPTOR: dict[str, Any] = {
    "id": "fastp",
    "name": "fastp",
    "version": "0.23.4",
    "category": "qc",
    "conda_env": "fastp_env",
    "inputs": [
        {"name": "reads_1", "type": "fastq", "required": True},
        {"name": "reads_2", "type": "fastq", "required": False},
    ],
    "outputs": [
        {
            "name": "clean_1",
            "type": "fastq",
            "tier": "intermediate",
            "pattern": "{output_dir}/{sample_id}.clean.R1.fq.gz",
        },
        {
            "name": "clean_2",
            "type": "fastq",
            "tier": "intermediate",
            "pattern": "{output_dir}/{sample_id}.clean.R2.fq.gz",
        },
        {
            "name": "report_html",
            "type": "html",
            "tier": "result",
            "pattern": "{output_dir}/{sample_id}.fastp.html",
        },
    ],
    "parameters": [
        {"name": "qualified_quality_phred", "type": "int", "default": 15},
        {"name": "length_required", "type": "int", "default": 50},
        {"name": "thread", "type": "int", "default": 4},
    ],
    "command_template": (
        "fastp "
        "-i {{ reads_1 }} "
        "-o {{ clean_1 }} "
        "-h {{ report_html }} "
        "-q {{ qualified_quality_phred }} "
        "-l {{ length_required }} "
        "-w {{ thread }}"
    ),
    "databases": [],
}


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """内存 SQLite 数据库"""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    return conn


@pytest.fixture()
def registry(db_conn: sqlite3.Connection) -> DataRegistry:
    return DataRegistry(db_conn)


@pytest.fixture()
def sample_id(registry: DataRegistry) -> str:
    return registry.add_sample("测试样本", source="water")


@pytest.fixture()
def project() -> ProjectInfo:
    return ProjectInfo(
        project_id="proj_test123456",
        name="测试项目",
        description="",
        created_at=time.time(),
        status="active",
        remote_base="/h2ometa/projects/proj_test123456",
    )


@pytest.fixture()
def ssh() -> FakeSSHService:
    return FakeSSHService()


@pytest.fixture()
def queue() -> FakeJobQueue:
    return FakeJobQueue()


@pytest.fixture()
def plugin_registry() -> MagicMock:
    mock = MagicMock()
    mock.get_descriptor.return_value = FASTP_DESCRIPTOR
    return mock


@pytest.fixture()
def pm(db_conn: sqlite3.Connection, project: ProjectInfo) -> FakeProjectManager:
    return FakeProjectManager(db_conn, project)


@pytest.fixture()
def engine(
    ssh: FakeSSHService,
    plugin_registry: MagicMock,
    pm: FakeProjectManager,
    registry: DataRegistry,
    queue: FakeJobQueue,
) -> ToolEngine:
    return ToolEngine(
        ssh_service=ssh,
        plugin_registry=plugin_registry,
        project_manager=pm,
        data_registry=registry,
        job_queue=queue,
    )


# ── CommandBuilder 测试 ───────────────────────────────────


class TestCommandBuilder:
    """CommandBuilder.build() 测试（使用外部 Jinja2 版本）"""

    def test_build_basic(self) -> None:
        output_dir = "/h2ometa/projects/proj_x/intermediate/sample1/fastp"
        output_paths = CommandBuilder.resolve_output_paths(
            FASTP_DESCRIPTOR, output_dir, "sample1",
        )
        cmd = CommandBuilder.build(
            descriptor=FASTP_DESCRIPTOR,
            parameters={
                "qualified_quality_phred": 20,
                "length_required": 60,
                "thread": 8,
            },
            input_paths={"reads_1": "/data/sample1.R1.fq.gz", **output_paths},
            output_dir=output_dir,
            sample_id="sample1",
        )
        assert "fastp" in cmd
        assert "/data/sample1.R1.fq.gz" in cmd
        assert "-q 20" in cmd
        assert "-l 60" in cmd
        assert "-w 8" in cmd
        assert "sample1.clean.R1.fq.gz" in cmd

    def test_build_syntax_error_raises(self) -> None:
        """Jinja2 语法错误应抛出 CommandBuildError"""
        descriptor = {
            "id": "broken_tool",
            "command_template": "{% if unclosed %}",
            "inputs": [],
            "parameters": [],
        }
        with pytest.raises(CommandBuildError):
            CommandBuilder.build(
                descriptor=descriptor,
                parameters={},
                input_paths={},
                output_dir="/tmp",
                sample_id="s1",
            )

    def test_build_includes_output_dir(self) -> None:
        output_dir = "/proj/intermediate/s1/fastp"
        output_paths = CommandBuilder.resolve_output_paths(
            FASTP_DESCRIPTOR, output_dir, "s1",
        )
        cmd = CommandBuilder.build(
            descriptor=FASTP_DESCRIPTOR,
            parameters={
                "qualified_quality_phred": 15,
                "length_required": 50,
                "thread": 4,
            },
            input_paths={"reads_1": "/data/r1.fq", **output_paths},
            output_dir=output_dir,
            sample_id="s1",
        )
        assert "/proj/intermediate/s1/fastp" in cmd


# ── ExecutionRecord 数据类测试 ─────────────────────────────


class TestExecutionRecord:
    """ExecutionRecord 数据类测试"""

    def test_defaults(self) -> None:
        r = ExecutionRecord(
            execution_id="exec_abc",
            sample_id="smp_123",
            tool_id="fastp",
            tool_version="0.23.4",
            parameters={"q": 15},
            status="pending",
            triggered_by="manual",
            created_at=1000.0,
        )
        assert r.completed_at is None
        assert r.error is None
        assert r.retry_count == 0
        assert r.retry_of is None
        assert r.remote_job_id is None


# ── ToolEngine.execute 完整流程测试 ────────────────────────


class TestToolEngineExecute:
    """ToolEngine.execute() 完整流程测试"""

    def test_execute_returns_execution_id(
        self, engine: ToolEngine, registry: DataRegistry, sample_id: str
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={"thread": 8},
            sample_id=sample_id,
        )
        assert exec_id.startswith("exec_")

    def test_execute_saves_record_to_db(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        db_conn: sqlite3.Connection,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        row = db_conn.execute(
            "SELECT * FROM executions WHERE execution_id = ?", (exec_id,)
        ).fetchone()
        assert row is not None
        assert row["tool_id"] == "fastp"
        assert row["status"] == "running"
        assert row["triggered_by"] == "manual"

    def test_execute_records_input_io(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        db_conn: sqlite3.Connection,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        rows = db_conn.execute(
            "SELECT * FROM execution_io WHERE execution_id = ? AND direction = 'input'",
            (exec_id,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["data_id"] == data_id

    def test_execute_submits_to_queue(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        queue: FakeJobQueue,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        assert len(queue.submitted) == 1
        submitted = queue.submitted[0]
        assert submitted["execution_id"] == exec_id
        assert "fastp" in submitted["command"]
        assert submitted["metadata"]["tool_id"] == "fastp"

    def test_execute_merges_defaults(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        queue: FakeJobQueue,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={"thread": 16},  # 覆盖默认值 4
            sample_id=sample_id,
        )

        cmd = queue.submitted[0]["command"]
        assert "-w 16" in cmd  # 用户值覆盖了默认值

    def test_execute_creates_remote_dir(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        ssh: FakeSSHService,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        # 应调用 mkdir -p 创建输出目录
        mkdir_cmds = [c for c in ssh.commands_run if "mkdir -p" in c]
        assert len(mkdir_cmds) == 1
        assert sample_id in mkdir_cmds[0]

    def test_execute_emits_started_signal(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
    ) -> None:
        received: list[str] = []
        engine.execution_started.connect(received.append)

        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        assert received == [exec_id]

    def test_execute_no_project_raises(
        self,
        ssh: FakeSSHService,
        plugin_registry: MagicMock,
        registry: DataRegistry,
        queue: FakeJobQueue,
        db_conn: sqlite3.Connection,
    ) -> None:
        pm_no_project = FakeProjectManager(db_conn, None)  # type: ignore[arg-type]
        engine = ToolEngine(
            ssh_service=ssh,
            plugin_registry=plugin_registry,
            project_manager=pm_no_project,
            data_registry=registry,
            job_queue=queue,
        )

        with pytest.raises(ValueError, match="请先选择或创建项目"):
            engine.execute(
                tool_id="fastp",
                input_data_ids=["dat_x"],
                parameters={},
                sample_id="smp_x",
            )

    def test_execute_missing_required_input_raises(
        self,
        engine: ToolEngine,
        sample_id: str,
    ) -> None:
        """缺少必需输入数据时应抛出 ValueError"""
        with pytest.raises(ValueError, match="缺少必需的输入"):
            engine.execute(
                tool_id="fastp",
                input_data_ids=[],  # 空输入，但 reads_1 是 required
                parameters={},
                sample_id=sample_id,
            )

    def test_execute_nonexistent_input_raises(
        self,
        engine: ToolEngine,
        sample_id: str,
    ) -> None:
        """输入数据 ID 不存在时应抛出 ValueError"""
        with pytest.raises(ValueError, match="输入数据不存在"):
            engine.execute(
                tool_id="fastp",
                input_data_ids=["dat_nonexistent"],
                parameters={},
                sample_id=sample_id,
            )

    def test_execute_custom_triggered_by(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        db_conn: sqlite3.Connection,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
            triggered_by="wizard",
        )

        row = db_conn.execute(
            "SELECT triggered_by FROM executions WHERE execution_id = ?",
            (exec_id,),
        ).fetchone()
        assert row["triggered_by"] == "wizard"


# ── ToolEngine.on_job_completed 测试 ──────────────────────


class TestToolEngineOnCompleted:
    """on_job_completed() 回调测试"""

    def test_on_completed_registers_outputs(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        db_conn: sqlite3.Connection,
    ) -> None:
        # 先 execute 创建执行记录
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )
        output_dir = f"/h2ometa/projects/proj_test123456/intermediate/{sample_id}/fastp"

        # 模拟完成
        engine.on_job_completed(exec_id, FASTP_DESCRIPTOR, sample_id, output_dir)

        # 检查输出数据注册
        outputs = db_conn.execute(
            "SELECT * FROM execution_io WHERE execution_id = ? AND direction = 'output'",
            (exec_id,),
        ).fetchall()
        assert len(outputs) == 3  # fastp 有 3 个输出

    def test_on_completed_updates_status(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        db_conn: sqlite3.Connection,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )
        output_dir = f"/h2ometa/projects/proj_test123456/intermediate/{sample_id}/fastp"

        engine.on_job_completed(exec_id, FASTP_DESCRIPTOR, sample_id, output_dir)

        row = db_conn.execute(
            "SELECT status, completed_at FROM executions WHERE execution_id = ?",
            (exec_id,),
        ).fetchone()
        assert row["status"] == "completed"
        assert row["completed_at"] is not None

    def test_on_completed_emits_signal(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )
        output_dir = f"/h2ometa/projects/proj_test123456/intermediate/{sample_id}/fastp"

        received: list[str] = []
        engine.execution_completed.connect(received.append)
        engine.on_job_completed(exec_id, FASTP_DESCRIPTOR, sample_id, output_dir)

        assert received == [exec_id]


# ── ToolEngine.on_job_failed 测试 ─────────────────────────


class TestToolEngineOnFailed:
    """on_job_failed() 回调测试"""

    def test_on_failed_updates_status(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        db_conn: sqlite3.Connection,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        engine.on_job_failed(exec_id, "内存不足")

        row = db_conn.execute(
            "SELECT status, error FROM executions WHERE execution_id = ?",
            (exec_id,),
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error"] == "内存不足"

    def test_on_failed_emits_signal(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        received: list[tuple[str, str]] = []
        engine.execution_failed.connect(lambda eid, err: received.append((eid, err)))
        engine.on_job_failed(exec_id, "Segfault")

        assert len(received) == 1
        assert received[0] == (exec_id, "Segfault")


# ── ToolEngine.get_record 测试 ────────────────────────────


class TestToolEngineGetRecord:
    """get_record() 测试"""

    def test_get_record_after_execute(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={"thread": 8},
            sample_id=sample_id,
        )

        record = engine.get_record(exec_id)
        assert record is not None
        assert record.execution_id == exec_id
        assert record.tool_id == "fastp"
        assert record.parameters["thread"] == 8

    def test_get_record_not_found(self, engine: ToolEngine) -> None:
        record = engine.get_record("exec_nonexistent")
        assert record is None


# ── DataImporter 测试 ─────────────────────────────────────


class TestDataImporter:
    """DataImporter 单元测试"""

    @pytest.fixture()
    def importer(
        self, ssh: FakeSSHService, registry: DataRegistry
    ) -> DataImporter:
        return DataImporter(ssh_service=ssh, registry=registry)

    def test_import_file_basic(
        self,
        importer: DataImporter,
        ssh: FakeSSHService,
        registry: DataRegistry,
        sample_id: str,
        tmp_path: Path,
    ) -> None:
        # 创建临时本地文件
        local_file = tmp_path / "sample1.R1.fq.gz"
        local_file.write_text("fake fastq data")

        data_id = importer.import_file(
            local_path=str(local_file),
            sample_id=sample_id,
            data_type="fastq",
            project_remote_base="/h2ometa/projects/proj_x",
        )

        assert data_id.startswith("dat_")

        # 验证 SSH mkdir 和 upload 被调用
        assert any("mkdir -p" in c for c in ssh.commands_run)
        assert len(ssh.uploads) == 1
        assert ssh.uploads[0][1] == f"/h2ometa/projects/proj_x/raw/{sample_id}/sample1.R1.fq.gz"

        # 验证已注册到 DataRegistry
        item = registry.get_item(data_id)
        assert item is not None
        assert item.data_type == "fastq"
        assert item.tier == "raw"

    def test_import_file_not_found_raises(
        self, importer: DataImporter, sample_id: str
    ) -> None:
        with pytest.raises(FileNotFoundError, match="本地文件不存在"):
            importer.import_file(
                local_path="/nonexistent/file.fq",
                sample_id=sample_id,
                data_type="fastq",
                project_remote_base="/h2ometa/projects/proj_x",
            )

    def test_import_file_emits_signals(
        self,
        importer: DataImporter,
        sample_id: str,
        tmp_path: Path,
    ) -> None:
        local_file = tmp_path / "test.fq"
        local_file.write_text("data")

        progress_events: list[tuple[str, int]] = []
        completed_events: list[str] = []
        importer.upload_progress.connect(
            lambda name, pct: progress_events.append((name, pct))
        )
        importer.import_completed.connect(completed_events.append)

        data_id = importer.import_file(
            local_path=str(local_file),
            sample_id=sample_id,
            data_type="fastq",
            project_remote_base="/proj",
        )

        # 应有进度事件 (0%, 10%, 90%, 100%)
        percents = [p[1] for p in progress_events]
        assert 0 in percents
        assert 100 in percents

        # 应有完成事件
        assert completed_events == [data_id]

    def test_import_file_ssh_failure_emits_failed(
        self,
        registry: DataRegistry,
        sample_id: str,
        tmp_path: Path,
    ) -> None:
        # 创建一个 mkdir 会失败的 SSH mock
        failing_ssh = FakeSSHService()
        failing_ssh.run = lambda cmd, timeout=10: (1, "", "Permission denied")  # type: ignore[assignment]

        importer = DataImporter(ssh_service=failing_ssh, registry=registry)

        local_file = tmp_path / "test.fq"
        local_file.write_text("data")

        failed_events: list[tuple[str, str]] = []
        importer.import_failed.connect(
            lambda name, err: failed_events.append((name, err))
        )

        with pytest.raises(RuntimeError, match="创建远端目录失败"):
            importer.import_file(
                local_path=str(local_file),
                sample_id=sample_id,
                data_type="fastq",
                project_remote_base="/proj",
            )

        assert len(failed_events) == 1
        assert "Permission denied" in failed_events[0][1]

    def test_import_batch(
        self,
        importer: DataImporter,
        registry: DataRegistry,
        sample_id: str,
        tmp_path: Path,
    ) -> None:
        f1 = tmp_path / "s1.R1.fq"
        f2 = tmp_path / "s1.R2.fq"
        f1.write_text("R1")
        f2.write_text("R2")

        data_ids = importer.import_batch(
            files=[
                {"local_path": str(f1), "sample_id": sample_id, "data_type": "fastq"},
                {"local_path": str(f2), "sample_id": sample_id, "data_type": "fastq"},
            ],
            project_remote_base="/proj",
        )

        assert len(data_ids) == 2
        assert all(did.startswith("dat_") for did in data_ids)


# ── ToolEngine._merge_defaults 测试 ───────────────────────


class TestMergeDefaults:
    """_merge_defaults 静态方法测试"""

    def test_defaults_only(self) -> None:
        merged = ToolEngine._merge_defaults(FASTP_DESCRIPTOR, {})
        assert merged["qualified_quality_phred"] == 15
        assert merged["length_required"] == 50
        assert merged["thread"] == 4

    def test_user_overrides(self) -> None:
        merged = ToolEngine._merge_defaults(
            FASTP_DESCRIPTOR, {"thread": 16, "length_required": 100}
        )
        assert merged["thread"] == 16
        assert merged["length_required"] == 100
        assert merged["qualified_quality_phred"] == 15  # 保持默认

    def test_extra_user_params_preserved(self) -> None:
        merged = ToolEngine._merge_defaults(
            FASTP_DESCRIPTOR, {"custom_param": "value"}
        )
        assert merged["custom_param"] == "value"

    def test_empty_descriptor_params(self) -> None:
        descriptor: dict[str, Any] = {"parameters": []}
        merged = ToolEngine._merge_defaults(descriptor, {"x": 1})
        assert merged == {"x": 1}
