"""PipelineRunner 单元测试 — 验证线性流水线编排。"""

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest
import yaml
from PyQt6.QtCore import QObject, pyqtSignal

from core.execution.command_builder import CommandBuilder
from core.data.data_registry import DataRegistry
from core.environment.h2o_env_paths import H2O_CONDA_EXE
from core.pipeline.pipeline_runner import PipelineRunner, PipelineStage
from core.data.project_manager import ProjectInfo, _SCHEMA_SQL


# ── Fake 对象 ─────────────────────────────────────────────


class FakeSSHService:
    """模拟 SSH"""

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        return (0, "", "")

    def upload(self, local_path: str, remote_path: str) -> None:
        pass


class FakeProjectManager:
    def __init__(self, conn: sqlite3.Connection, project: ProjectInfo) -> None:
        self._conn = conn
        self._project = project

    @property
    def current_project(self) -> Optional[ProjectInfo]:
        return self._project

    @property
    def db(self) -> sqlite3.Connection:
        return self._conn


class FakeJobQueue:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    def submit(
        self,
        execution_id: str,
        command: str,
        callback_on_start: Any = None,
        metadata: Any = None,
    ) -> str:
        self.jobs.append({
            "execution_id": execution_id,
            "command": command,
            "metadata": metadata,
        })
        return "started"


# ── Fixtures ──────────────────────────────────────────────


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
    return registry.add_sample("PipelineSample", source="water")


@pytest.fixture()
def project() -> ProjectInfo:
    return ProjectInfo(
        project_id="proj_pipe_test",
        name="Pipeline测试",
        description="",
        created_at=time.time(),
        status="active",
        remote_base="/h2ometa/projects/proj_pipe_test",
    )


@pytest.fixture()
def ssh() -> FakeSSHService:
    return FakeSSHService()


@pytest.fixture()
def queue() -> FakeJobQueue:
    return FakeJobQueue()


# 三个阶段的 tool descriptors

FASTP_DESC = {
    "id": "fastp",
    "name": "fastp",
    "version": "0.23.4",
    "category": "qc",
    "conda_env": "fastp_env",
    "inputs": [{"name": "reads_1", "type": "fastq", "required": True}],
    "outputs": [
        {"name": "clean_1", "type": "fastq", "tier": "intermediate",
         "pattern": "{output_dir}/{sample_id}.clean.R1.fq.gz"},
    ],
    "parameters": [
        {"name": "qualified_quality_phred", "type": "int", "default": 15},
        {"name": "thread", "type": "int", "default": 4},
    ],
    "command_template": "fastp -i {{ reads_1 }} -o {{ clean_1 }} -q {{ qualified_quality_phred }}",
    "databases": [],
}

HOSTILE_DESC = {
    "id": "hostile",
    "name": "hostile",
    "version": "1.1.0",
    "category": "host_removal",
    "conda_env": "hostile_env",
    "inputs": [{"name": "reads_1", "type": "fastq", "required": True}],
    "outputs": [
        {"name": "clean_1", "type": "fastq", "tier": "intermediate",
         "pattern": "{output_dir}/{sample_id}.host_removed.R1.fq.gz"},
    ],
    "parameters": [{"name": "threads", "type": "int", "default": 4}],
    "command_template": "hostile clean --fastq1 {{ reads_1 }} --threads {{ threads }}",
    "databases": [],
}

KRAKEN2_DESC = {
    "id": "kraken2",
    "name": "Kraken2",
    "version": "2.1.3",
    "category": "taxonomy",
    "conda_env": "kraken2_env",
    "inputs": [{"name": "reads", "type": "fastq", "required": True}],
    "outputs": [
        {"name": "k2_report", "type": "kreport", "tier": "result",
         "pattern": "{output_dir}/{sample_id}.kreport"},
    ],
    "parameters": [
        {"name": "confidence", "type": "float", "default": 0.0},
        {"name": "threads", "type": "int", "default": 8},
    ],
    "command_template": "kraken2 --db {{ db }} --threads {{ threads }} {{ input_reads }}",
    "databases": [{"id": "k2_standard", "param_name": "db", "required": True}],
}


@pytest.fixture()
def plugin_registry() -> MagicMock:
    mock = MagicMock()
    descriptors = {
        "fastp": FASTP_DESC,
        "hostile": HOSTILE_DESC,
        "kraken2": KRAKEN2_DESC,
    }
    mock.get_descriptor.side_effect = lambda tid: descriptors[tid]
    return mock


@pytest.fixture()
def engine(ssh, plugin_registry, db_conn, project, registry, queue):
    from core.execution.tool_engine import ToolEngine

    pm = FakeProjectManager(db_conn, project)
    return ToolEngine(
        ssh_service=ssh,
        plugin_registry=plugin_registry,
        project_manager=pm,
        data_registry=registry,
        job_queue=queue,
        conda_executable=H2O_CONDA_EXE,
    )


@pytest.fixture()
def runner(engine, registry) -> PipelineRunner:
    return PipelineRunner(tool_engine=engine, data_registry=registry)


# ── 测试 ─────────────────────────────────────────────────


class TestPipelineRunnerBasic:
    """基本功能测试"""

    def test_run_returns_run_id(
        self, runner, registry, sample_id,
    ) -> None:
        """run() 应返回 pipeline_run_id"""
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        stages = [PipelineStage(tool_id="fastp")]
        run_id = runner.run(stages, sample_id, [data_id])
        assert run_id.startswith("run_")

    def test_single_stage_pipeline(
        self, runner, engine, registry, sample_id, plugin_registry, project,
    ) -> None:
        """单阶段流水线: 完成后应发 pipeline_completed"""
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        stages = [PipelineStage(tool_id="fastp")]

        completed_runs: list[str] = []
        runner.pipeline_completed.connect(completed_runs.append)

        run_id = runner.run(stages, sample_id, [data_id])

        # 获取 execution_id
        assert len(runner._active_runs) == 1
        state = runner._active_runs[run_id]
        exec_id = state.current_execution_id

        # 模拟完成
        output_dir = f"{project.remote_base}/intermediate/{sample_id}/fastp"
        engine.on_job_completed(exec_id, FASTP_DESC, sample_id, output_dir)

        assert completed_runs == [run_id]

    def test_empty_stages_raises(self, runner, sample_id) -> None:
        with pytest.raises(ValueError, match="至少需要一个阶段"):
            runner.run([], sample_id, ["dat_x"])

    def test_empty_inputs_raises(self, runner, sample_id) -> None:
        with pytest.raises(ValueError, match="初始输入数据不能为空"):
            runner.run([PipelineStage(tool_id="fastp")], sample_id, [])


class TestPipelineRunnerMultiStage:
    """多阶段流水线测试"""

    def test_three_stage_pipeline(
        self, runner, engine, registry, sample_id, plugin_registry, project,
    ) -> None:
        """3 阶段流水线: fastp → hostile → kraken2"""
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        stages = [
            PipelineStage(tool_id="fastp"),
            PipelineStage(tool_id="hostile", input_type="fastq"),
            PipelineStage(
                tool_id="kraken2",
                input_type="fastq",
                database_paths={"db": "/db/k2"},
            ),
        ]

        stage_events: list[tuple[str, int, int]] = []
        completed_runs: list[str] = []
        runner.stage_completed.connect(
            lambda rid, idx, total: stage_events.append((rid, idx, total))
        )
        runner.pipeline_completed.connect(completed_runs.append)

        run_id = runner.run(stages, sample_id, [data_id])

        # ── 阶段 0: fastp ──
        state = runner._active_runs[run_id]
        exec_id_0 = state.current_execution_id

        output_dir_0 = f"{project.remote_base}/intermediate/{sample_id}/fastp"
        engine.on_job_completed(exec_id_0, FASTP_DESC, sample_id, output_dir_0)

        assert len(stage_events) == 1
        assert stage_events[0] == (run_id, 0, 3)

        # ── 阶段 1: hostile ──
        assert state.current_stage == 1
        exec_id_1 = state.current_execution_id

        output_dir_1 = f"{project.remote_base}/intermediate/{sample_id}/hostile"
        engine.on_job_completed(exec_id_1, HOSTILE_DESC, sample_id, output_dir_1)

        assert len(stage_events) == 2
        assert stage_events[1] == (run_id, 1, 3)

        # ── 阶段 2: kraken2 ──
        assert state.current_stage == 2
        exec_id_2 = state.current_execution_id

        output_dir_2 = f"{project.remote_base}/intermediate/{sample_id}/kraken2"
        engine.on_job_completed(exec_id_2, KRAKEN2_DESC, sample_id, output_dir_2)

        assert len(stage_events) == 3
        assert stage_events[2] == (run_id, 2, 3)
        assert completed_runs == [run_id]


class TestPipelineRunnerFailure:
    """失败流程测试"""

    def test_stage_failure_stops_pipeline(
        self, runner, engine, registry, sample_id,
    ) -> None:
        """阶段失败应停止流水线并发信号"""
        data_id = registry.register_input("/data/r1.fq", sample_id, "fastq")
        stages = [
            PipelineStage(tool_id="fastp"),
            PipelineStage(tool_id="hostile"),
        ]

        failed_events: list[tuple[str, int, str]] = []
        runner.pipeline_failed.connect(
            lambda rid, idx, err: failed_events.append((rid, idx, err))
        )

        run_id = runner.run(stages, sample_id, [data_id])
        state = runner._active_runs[run_id]
        exec_id = state.current_execution_id

        # 模拟阶段 0 失败
        engine.on_job_failed(exec_id, "内存不足")

        assert len(failed_events) == 1
        assert failed_events[0][0] == run_id
        assert failed_events[0][1] == 0
        assert "内存不足" in failed_events[0][2]


class TestPipelineRunnerYAML:
    """YAML 加载测试"""

    def test_load_stages_from_yaml(self, tmp_path) -> None:
        """应正确从 YAML 加载流水线阶段"""
        yaml_content = {
            "paths": {
                "read_based": {
                    "name": "读长分析路径",
                    "stages": [
                        {"tool_id": "fastp", "input_type": "fastq", "required": True},
                        {"tool_id": "hostile", "input_type": "fastq"},
                        {"tool_id": "kraken2", "input_type": "fastq"},
                    ],
                },
            },
        }
        yaml_path = tmp_path / "analysis_paths.yaml"
        yaml_path.write_text(
            yaml.dump(yaml_content, allow_unicode=True),
            encoding="utf-8",
        )

        stages = PipelineRunner.load_stages_from_yaml(
            str(yaml_path),
            "read_based",
            user_params={"fastp": {"thread": 16}},
            user_db_paths={"kraken2": {"db": "/db/k2"}},
        )

        assert len(stages) == 3
        assert stages[0].tool_id == "fastp"
        assert stages[0].parameters == {"thread": 16}
        assert stages[1].tool_id == "hostile"
        assert stages[2].tool_id == "kraken2"
        assert stages[2].database_paths == {"db": "/db/k2"}

    def test_load_nonexistent_path_raises(self, tmp_path) -> None:
        yaml_path = tmp_path / "test.yaml"
        yaml_path.write_text("paths: {}", encoding="utf-8")

        with pytest.raises(ValueError, match="流水线路径不存在"):
            PipelineRunner.load_stages_from_yaml(str(yaml_path), "nonexistent")
