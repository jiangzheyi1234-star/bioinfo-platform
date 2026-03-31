"""Focused tests for ToolEngine's Phase 2 preparation flow."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from core.data.data_registry import DataRegistry
from core.data.project_manager import ProjectInfo, _SCHEMA_SQL
from core.execution.command_builder import CommandBuilder
from core.execution.tool_engine import ExecutionRecord, ToolEngine

_MANAGED_CONDA = "/home/user/.h2ometa/conda/bin/conda"


class FakeSSHService:
    def __init__(self) -> None:
        self.commands_run: list[str] = []
        self.downloads: list[tuple[str, str]] = []

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        self.commands_run.append(cmd)
        return (0, "", "")

    def download(self, remote_path: str, local_path: str) -> None:
        self.downloads.append((remote_path, local_path))
        path = Path(local_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"downloaded from {remote_path}", encoding="utf-8")


class FakeJobQueue:
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []

    def submit(
        self,
        execution_id: str,
        command: str,
        callback_on_start: Any = None,
        metadata: Any = None,
    ) -> str:
        self.submitted.append(
            {
                "execution_id": execution_id,
                "command": command,
                "metadata": metadata,
            }
        )
        return "started"


class FakePreparationScheduler:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def __call__(self, request: Any) -> None:
        self.requests.append(request)


class FakeProjectManager:
    def __init__(
        self,
        conn: sqlite3.Connection,
        project: ProjectInfo | None,
        project_dir: Path | None = None,
    ) -> None:
        self._conn = conn
        self._project = project
        self._project_dir = project_dir or Path.cwd() / "tmp_project"

    @property
    def current_project(self) -> Optional[ProjectInfo]:
        return self._project

    @property
    def db(self) -> sqlite3.Connection:
        return self._conn

    @property
    def current_project_dir(self) -> Path:
        return self._project_dir


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


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
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
def scheduler() -> FakePreparationScheduler:
    return FakePreparationScheduler()


@pytest.fixture()
def plugin_registry() -> MagicMock:
    mock = MagicMock()
    mock.get_descriptor.return_value = FASTP_DESCRIPTOR
    return mock


@pytest.fixture()
def pm(db_conn: sqlite3.Connection, project: ProjectInfo, tmp_path: Path) -> FakeProjectManager:
    return FakeProjectManager(db_conn, project, tmp_path / project.project_id)


@pytest.fixture()
def engine(
    ssh: FakeSSHService,
    plugin_registry: MagicMock,
    pm: FakeProjectManager,
    registry: DataRegistry,
    queue: FakeJobQueue,
    scheduler: FakePreparationScheduler,
) -> ToolEngine:
    return ToolEngine(
        ssh_service=ssh,
        plugin_registry=plugin_registry,
        project_manager=pm,
        data_registry=registry,
        job_queue=queue,
        schedule_preparation_fn=scheduler,
        conda_executable=_MANAGED_CONDA,
    )


class TestExecutionRecord:
    def test_defaults(self) -> None:
        record = ExecutionRecord(
            execution_id="exec_abc",
            sample_id="smp_123",
            tool_id="fastp",
            tool_version="0.23.4",
            parameters={"q": 15},
            status="pending",
            triggered_by="manual",
            created_at=1000.0,
        )
        assert record.completed_at is None
        assert record.error is None
        assert record.retry_count == 0


class TestToolEngineExecute:
    def test_execute_returns_execution_id_and_schedules_preparation(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        queue: FakeJobQueue,
        scheduler: FakePreparationScheduler,
        ssh: FakeSSHService,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")

        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={"thread": 8},
            sample_id=sample_id,
        )

        assert exec_id.startswith("exec_")
        assert queue.submitted == []
        assert ssh.commands_run == []
        assert len(scheduler.requests) == 1
        request = scheduler.requests[0]
        assert request.execution_id == exec_id
        assert request.tool_id == "fastp"
        assert request.sample_id == sample_id
        assert request.merged_params["thread"] == 8
        assert request.merged_params["length_required"] == 50

    def test_execute_saves_record_and_input_io(
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
            "SELECT tool_id, status, triggered_by FROM executions WHERE execution_id = ?",
            (exec_id,),
        ).fetchone()
        assert row is not None
        assert row["tool_id"] == "fastp"
        assert row["status"] == "pending"
        assert row["triggered_by"] == "manual"

        io_rows = db_conn.execute(
            "SELECT * FROM execution_io WHERE execution_id = ? AND direction = 'input'",
            (exec_id,),
        ).fetchall()
        assert len(io_rows) == 1
        assert io_rows[0]["data_id"] == data_id

    def test_execute_emits_started_signal(self, engine: ToolEngine, registry: DataRegistry, sample_id: str) -> None:
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

    def test_execute_uses_remote_base_as_preparation_input(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        pm: FakeProjectManager,
        scheduler: FakePreparationScheduler,
    ) -> None:
        pm.current_project.remote_base = "/proj base/with spaces"
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")

        engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        assert scheduler.requests[0].remote_base == "/proj base/with spaces"

    def test_execute_no_project_raises(
        self,
        ssh: FakeSSHService,
        plugin_registry: MagicMock,
        registry: DataRegistry,
        queue: FakeJobQueue,
        db_conn: sqlite3.Connection,
        scheduler: FakePreparationScheduler,
    ) -> None:
        pm_no_project = FakeProjectManager(db_conn, None)  # type: ignore[arg-type]
        engine = ToolEngine(
            ssh_service=ssh,
            plugin_registry=plugin_registry,
            project_manager=pm_no_project,
            data_registry=registry,
            job_queue=queue,
            schedule_preparation_fn=scheduler,
        )

        with pytest.raises(ValueError, match="请先选择或创建项目"):
            engine.execute(
                tool_id="fastp",
                input_data_ids=["dat_x"],
                parameters={},
                sample_id="smp_x",
            )

    def test_execute_requires_managed_conda_when_env_declared(
        self,
        ssh: FakeSSHService,
        plugin_registry: MagicMock,
        pm: FakeProjectManager,
        registry: DataRegistry,
        queue: FakeJobQueue,
        scheduler: FakePreparationScheduler,
        sample_id: str,
    ) -> None:
        engine = ToolEngine(
            ssh_service=ssh,
            plugin_registry=plugin_registry,
            project_manager=pm,
            data_registry=registry,
            job_queue=queue,
            schedule_preparation_fn=scheduler,
            conda_executable="",
        )
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")

        with pytest.raises(ValueError, match="运行环境未就绪"):
            engine.execute(
                tool_id="fastp",
                input_data_ids=[data_id],
                parameters={},
                sample_id=sample_id,
            )

        row = pm.db.execute(
            "SELECT COUNT(*) AS cnt FROM executions",
        ).fetchone()
        assert int(row["cnt"]) == 0
        assert queue.submitted == []

    def test_execute_rejects_non_managed_conda(
        self,
        ssh: FakeSSHService,
        plugin_registry: MagicMock,
        pm: FakeProjectManager,
        registry: DataRegistry,
        queue: FakeJobQueue,
        scheduler: FakePreparationScheduler,
        sample_id: str,
    ) -> None:
        engine = ToolEngine(
            ssh_service=ssh,
            plugin_registry=plugin_registry,
            project_manager=pm,
            data_registry=registry,
            job_queue=queue,
            schedule_preparation_fn=scheduler,
            conda_executable="/opt/conda/bin/conda",
        )
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")

        with pytest.raises(ValueError, match="运行环境未就绪"):
            engine.execute(
                tool_id="fastp",
                input_data_ids=[data_id],
                parameters={},
                sample_id=sample_id,
            )

        row = pm.db.execute(
            "SELECT COUNT(*) AS cnt FROM executions",
        ).fetchone()
        assert int(row["cnt"]) == 0
        assert queue.submitted == []

    def test_execute_missing_required_input_raises(self, engine: ToolEngine, sample_id: str) -> None:
        with pytest.raises(ValueError, match="缺少必需的输入"):
            engine.execute(
                tool_id="fastp",
                input_data_ids=[],
                parameters={},
                sample_id=sample_id,
            )

    def test_mark_execution_running_updates_status(
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

        engine.mark_execution_running(exec_id)

        row = db_conn.execute(
            "SELECT status FROM executions WHERE execution_id = ?",
            (exec_id,),
        ).fetchone()
        assert row["status"] == "running"


class TestToolEngineCallbacks:
    def test_on_completed_registers_outputs_and_manifest(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        db_conn: sqlite3.Connection,
        pm: FakeProjectManager,
        ssh: FakeSSHService,
    ) -> None:
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )
        output_dir = f"/h2ometa/projects/proj_test123456/intermediate/{sample_id}/fastp_exec"

        engine.on_job_completed(exec_id, FASTP_DESCRIPTOR, sample_id, output_dir)

        outputs = db_conn.execute(
            "SELECT * FROM execution_io WHERE execution_id = ? AND direction = 'output'",
            (exec_id,),
        ).fetchall()
        assert len(outputs) == 2

        row = db_conn.execute(
            "SELECT status, completed_at FROM executions WHERE execution_id = ?",
            (exec_id,),
        ).fetchone()
        assert row["status"] == "completed"
        assert row["completed_at"] is not None

        manifest_path = pm.current_project_dir / "results" / exec_id / "artifacts_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["execution_id"] == exec_id
        assert manifest["artifacts"][0]["artifact_type"] in {"html", "binary", "json", "tsv", "text", "fasta", "archive"}
        assert manifest["artifacts"][0]["display_role"]
        assert manifest["artifacts"][0]["viewer_hint"]
        assert ssh.downloads

    def test_on_completed_emits_signal(self, engine: ToolEngine, registry: DataRegistry, sample_id: str) -> None:
        received: list[str] = []
        engine.execution_completed.connect(received.append)

        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )
        output_dir = f"/h2ometa/projects/proj_test123456/intermediate/{sample_id}/fastp_exec"

        engine.on_job_completed(exec_id, FASTP_DESCRIPTOR, sample_id, output_dir)

        assert received == [exec_id]

    def test_on_failed_updates_status_and_emits_signal(
        self,
        engine: ToolEngine,
        registry: DataRegistry,
        sample_id: str,
        db_conn: sqlite3.Connection,
    ) -> None:
        received: list[tuple[str, str]] = []
        engine.execution_failed.connect(lambda eid, err: received.append((eid, err)))

        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        exec_id = engine.execute(
            tool_id="fastp",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        engine.on_job_failed(exec_id, "Segfault")

        row = db_conn.execute(
            "SELECT status, error FROM executions WHERE execution_id = ?",
            (exec_id,),
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error"] == "Segfault"
        assert received == [(exec_id, "Segfault")]

    def test_get_record_returns_saved_execution(self, engine: ToolEngine, registry: DataRegistry, sample_id: str) -> None:
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


def test_command_builder_still_builds_fastp_command() -> None:
    output_dir = "/h2ometa/projects/proj_x/intermediate/sample1/fastp"
    output_paths = CommandBuilder.resolve_output_paths(FASTP_DESCRIPTOR, output_dir, "sample1")
    cmd = CommandBuilder.build(
        descriptor=FASTP_DESCRIPTOR,
        parameters={"qualified_quality_phred": 20, "length_required": 60, "thread": 8},
        input_paths={"reads_1": "/data/sample1.R1.fq.gz", **output_paths},
        output_dir=output_dir,
        sample_id="sample1",
        conda_executable=_MANAGED_CONDA,
    )

    assert "fastp" in cmd
    assert "-q 20" in cmd
    assert "-l 60" in cmd
    assert "-w 8" in cmd
