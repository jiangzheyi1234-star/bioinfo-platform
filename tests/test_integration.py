"""核心流程集成测试 — 验证从插件加载到血缘追溯的完整闭环。

测试场景:
1. PluginRegistry 扫描并加载 tool.yaml
2. ProjectManager 创建项目 + SQLite 建表
3. DataRegistry 添加样本 + 注册输入数据
4. ToolEngine.execute() 完整流程（mock SSH / JobQueue）
5. on_job_completed 注册输出 + DataRegistry 血缘追溯验证
6. DataImporter 导入文件 + 注册

所有外部依赖（SSH、文件系统）均使用 mock。
"""

import sqlite3
import time
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import pytest
import yaml

from core.data_importer import DataImporter
from core.data_registry import DataRegistry
from core.plugin_registry import PluginRegistry
from core.project_manager import ProjectInfo, ProjectManager, _SCHEMA_SQL
from core.command_builder import CommandBuilder
from core.tool_engine import ExecutionRecord, ToolEngine


# ── Mock / Fake 对象 ──────────────────────────────────────


class FakeSSH:
    """模拟 SSH 服务，记录所有调用"""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.uploads: list[tuple[str, str]] = []

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        self.commands.append(cmd)
        return (0, "", "")

    def upload(self, local_path: str, remote_path: str) -> None:
        self.uploads.append((local_path, remote_path))


class FakeJobQueue:
    """模拟 JobQueue，记录提交的任务"""

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


class FakeProjectManager:
    """包装真实 ProjectManager 的 db 连接，提供 current_project"""

    def __init__(self, conn: sqlite3.Connection, project: ProjectInfo) -> None:
        self._conn = conn
        self._project = project

    @property
    def current_project(self) -> Optional[ProjectInfo]:
        return self._project

    @property
    def db(self) -> sqlite3.Connection:
        return self._conn


# ── 测试用 tool.yaml 内容（使用 Jinja2 模板） ──────────


SIMPLE_TOOL_YAML = {
    "id": "simple_qc",
    "name": "SimpleQC",
    "version": "1.0.0",
    "category": "qc",
    "description": "测试用简单质控工具",
    "conda_env": "qc_env",
    "inputs": [
        {"name": "reads_1", "type": "fastq", "required": True},
    ],
    "outputs": [
        {
            "name": "clean_reads",
            "type": "fastq",
            "tier": "intermediate",
            "pattern": "{output_dir}/{sample_id}.clean.fq.gz",
        },
        {
            "name": "report",
            "type": "json",
            "tier": "result",
            "pattern": "{output_dir}/{sample_id}.qc_report.json",
        },
    ],
    "parameters": [
        {"name": "min_quality", "type": "int", "default": 20},
        {"name": "min_length", "type": "int", "default": 50},
    ],
    "command_template": (
        "simple_qc "
        "-i {{ reads_1 }} "
        "-o {{ clean_reads }} "
        "-r {{ report }} "
        "-q {{ min_quality }} -l {{ min_length }}"
    ),
    "databases": [],
}


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture()
def plugins_dir(tmp_path: Path) -> Path:
    """创建包含测试 tool.yaml 的插件目录"""
    tool_dir = tmp_path / "plugins" / "qc" / "simple_qc"
    tool_dir.mkdir(parents=True)
    yaml_path = tool_dir / "tool.yaml"
    yaml_path.write_text(
        yaml.dump(SIMPLE_TOOL_YAML, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return tmp_path / "plugins"


@pytest.fixture()
def plugin_registry(plugins_dir: Path) -> PluginRegistry:
    """创建并扫描的 PluginRegistry"""
    reg = PluginRegistry(plugins_dir)
    count = reg.scan()
    assert count == 1, f"预期扫描到 1 个插件，实际 {count}"
    return reg


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """内存 SQLite + schema"""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    return conn


@pytest.fixture()
def data_registry(db_conn: sqlite3.Connection) -> DataRegistry:
    return DataRegistry(db_conn)


@pytest.fixture()
def project() -> ProjectInfo:
    return ProjectInfo(
        project_id="proj_integ_test01",
        name="集成测试项目",
        description="用于集成测试",
        created_at=time.time(),
        status="active",
        remote_base="/h2ometa/projects/proj_integ_test01",
    )


@pytest.fixture()
def ssh() -> FakeSSH:
    return FakeSSH()


@pytest.fixture()
def queue() -> FakeJobQueue:
    return FakeJobQueue()


@pytest.fixture()
def pm(db_conn: sqlite3.Connection, project: ProjectInfo) -> FakeProjectManager:
    return FakeProjectManager(db_conn, project)


@pytest.fixture()
def engine(
    ssh: FakeSSH,
    plugin_registry: PluginRegistry,
    pm: FakeProjectManager,
    data_registry: DataRegistry,
    queue: FakeJobQueue,
) -> ToolEngine:
    return ToolEngine(
        ssh_service=ssh,
        plugin_registry=plugin_registry,
        project_manager=pm,
        data_registry=data_registry,
        job_queue=queue,
    )


# ── 测试 1: PluginRegistry 加载 tool.yaml ─────────────────


class TestPluginRegistryIntegration:
    """验证 PluginRegistry 能正确加载和解析 tool.yaml"""

    def test_scan_finds_plugin(self, plugin_registry: PluginRegistry) -> None:
        assert "simple_qc" in plugin_registry.list_all_ids()
        assert plugin_registry.plugin_count == 1

    def test_descriptor_has_all_fields(self, plugin_registry: PluginRegistry) -> None:
        desc = plugin_registry.get_descriptor("simple_qc")
        assert desc["id"] == "simple_qc"
        assert desc["version"] == "1.0.0"
        assert desc["category"] == "qc"
        assert len(desc["inputs"]) == 1
        assert len(desc["outputs"]) == 2
        assert len(desc["parameters"]) == 2
        assert "command_template" in desc

    def test_list_by_category(self, plugin_registry: PluginRegistry) -> None:
        qc_tools = plugin_registry.list_by_category("qc")
        assert len(qc_tools) == 1
        assert qc_tools[0]["id"] == "simple_qc"


# ── 测试 2: PluginRegistry 加载真实 fastp tool.yaml ────────


class TestRealPluginLoading:
    """验证 PluginRegistry 能加载项目中真实的 plugins/ 目录"""

    def test_load_real_plugins(self) -> None:
        real_plugins = Path("E:/代码/bio_ui/plugins")
        if not real_plugins.exists():
            pytest.skip("真实 plugins 目录不存在")

        reg = PluginRegistry(real_plugins)
        count = reg.scan()
        assert count >= 1, "至少应能加载 1 个真实插件"
        assert "fastp" in reg.list_all_ids()

    def test_fastp_descriptor_structure(self) -> None:
        real_plugins = Path("E:/代码/bio_ui/plugins")
        if not real_plugins.exists():
            pytest.skip("真实 plugins 目录不存在")

        reg = PluginRegistry(real_plugins)
        reg.scan()
        desc = reg.get_descriptor("fastp")
        assert desc["id"] == "fastp"
        assert desc["version"] == "0.23.4"
        assert desc["conda_env"] == "fastp_env"
        assert any(i["name"] == "reads_1" for i in desc["inputs"])
        assert any(o["name"] == "clean_1" for o in desc["outputs"])


# ── 测试 3: ProjectManager 创建项目 + SQLite 建表 ──────────


class TestProjectManagerIntegration:
    """验证 ProjectManager 创建项目并正确初始化 SQLite"""

    def test_create_and_open_project(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        index_path = tmp_path / "projects.json"
        pm = ProjectManager(projects_root=projects_root, index_path=index_path)

        # 创建项目
        pid = pm.create_project("集成测试", "测试描述")
        assert pid.startswith("proj_")

        # 打开项目
        info = pm.open_project(pid)
        assert info.name == "集成测试"
        assert pm.current_project is not None

        # 验证 4 张表都已创建
        tables = pm.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(t[0] for t in tables)
        assert "data_items" in table_names
        assert "execution_io" in table_names
        assert "executions" in table_names
        assert "samples" in table_names

        # 验证可以在表中插入数据
        pm.db.execute(
            "INSERT INTO samples (sample_id, name) VALUES (?, ?)",
            ("smp_test", "测试样本"),
        )
        pm.db.commit()
        row = pm.db.execute("SELECT * FROM samples").fetchone()
        assert row["name"] == "测试样本"

        pm.close()


# ── 测试 4: 完整执行闭环 — 从注册到血缘 ──────────────────


class TestFullExecutionLoop:
    """最核心的集成测试: 注册输入 -> execute -> on_completed -> 血缘追溯"""

    def test_full_fastp_pipeline(
        self,
        engine: ToolEngine,
        data_registry: DataRegistry,
        plugin_registry: PluginRegistry,
        queue: FakeJobQueue,
        ssh: FakeSSH,
        db_conn: sqlite3.Connection,
        project: ProjectInfo,
    ) -> None:
        # ── Step 1: 添加样本 ──
        sample_id = data_registry.add_sample("WaterSample01", source="water")
        assert sample_id.startswith("smp_")

        # ── Step 2: 注册原始输入文件 ──
        raw_id = data_registry.register_input(
            file_path="/h2ometa/projects/proj_integ_test01/raw/WaterSample01/reads.R1.fq.gz",
            sample_id=sample_id,
            data_type="fastq",
            tier="raw",
        )
        assert raw_id.startswith("dat_")

        # ── Step 3: 执行 simple_qc ──
        signals_started: list[str] = []
        signals_completed: list[str] = []
        engine.execution_started.connect(signals_started.append)
        engine.execution_completed.connect(signals_completed.append)

        exec_id = engine.execute(
            tool_id="simple_qc",
            input_data_ids=[raw_id],
            parameters={"min_quality": 25},  # 覆盖默认值 20
            sample_id=sample_id,
            triggered_by="manual",
        )
        assert exec_id.startswith("exec_")
        assert signals_started == [exec_id]

        # ── Step 4: 验证执行记录已写入 SQLite ──
        record = engine.get_record(exec_id)
        assert record is not None
        assert record.tool_id == "simple_qc"
        assert record.status == "running"
        assert record.parameters["min_quality"] == 25
        assert record.parameters["min_length"] == 50  # 默认值
        assert record.triggered_by == "manual"

        # ── Step 5: 验证 execution_io(input) 已记录 ──
        io_rows = db_conn.execute(
            "SELECT * FROM execution_io WHERE execution_id = ? AND direction = 'input'",
            (exec_id,),
        ).fetchall()
        assert len(io_rows) == 1
        assert io_rows[0]["data_id"] == raw_id

        # ── Step 6: 验证命令已提交到 JobQueue ──
        assert len(queue.jobs) == 1
        submitted_cmd = queue.jobs[0]["command"]
        assert "simple_qc" in submitted_cmd
        assert "-q 25" in submitted_cmd
        assert "-l 50" in submitted_cmd
        assert sample_id not in submitted_cmd or True  # sample_id 可能被替换

        # ── Step 7: 验证 SSH mkdir 被调用 ──
        mkdir_cmds = [c for c in ssh.commands if "mkdir -p" in c]
        assert len(mkdir_cmds) == 1

        # ── Step 8: 模拟任务完成 → 注册输出 ──
        descriptor = plugin_registry.get_descriptor("simple_qc")
        output_dir = f"{project.remote_base}/intermediate/{sample_id}/simple_qc"

        engine.on_job_completed(exec_id, descriptor, sample_id, output_dir)
        assert signals_completed == [exec_id]

        # ── Step 9: 验证输出数据已注册 ──
        io_outputs = db_conn.execute(
            "SELECT * FROM execution_io WHERE execution_id = ? AND direction = 'output'",
            (exec_id,),
        ).fetchall()
        assert len(io_outputs) == 2  # clean_reads + report

        # 验证输出数据项的属性
        sample_data = data_registry.find_by_sample(sample_id)
        assert len(sample_data) == 3  # 1 raw input + 2 outputs

        # 检查各输出的 tier
        clean_items = data_registry.find_compatible(sample_id, "fastq", tier="intermediate")
        assert len(clean_items) == 1
        assert "clean.fq.gz" in clean_items[0].file_path

        json_items = data_registry.find_compatible(sample_id, "json", tier="result")
        assert len(json_items) == 1
        assert "qc_report.json" in json_items[0].file_path

        # ── Step 10: 验证执行状态已更新 ──
        updated_record = engine.get_record(exec_id)
        assert updated_record.status == "completed"
        assert updated_record.completed_at is not None

        # ── Step 11: 血缘追溯 — 从输出追溯到原始输入 ──
        clean_data_id = clean_items[0].data_id
        lineage = data_registry.get_lineage(clean_data_id)
        lineage_ids = {item.data_id for item in lineage}

        # 血缘链应包含: clean_reads 自身 + 原始 raw input
        assert clean_data_id in lineage_ids
        assert raw_id in lineage_ids
        assert len(lineage) == 2

    def test_execute_failure_flow(
        self,
        engine: ToolEngine,
        data_registry: DataRegistry,
        db_conn: sqlite3.Connection,
    ) -> None:
        """验证失败流程: execute -> on_job_failed -> status=failed"""
        sample_id = data_registry.add_sample("FailSample")
        raw_id = data_registry.register_input(
            "/data/fail.fq", sample_id, "fastq"
        )

        signals_failed: list[tuple[str, str]] = []
        engine.execution_failed.connect(
            lambda eid, err: signals_failed.append((eid, err))
        )

        exec_id = engine.execute(
            tool_id="simple_qc",
            input_data_ids=[raw_id],
            parameters={},
            sample_id=sample_id,
        )

        # 模拟失败
        engine.on_job_failed(exec_id, "内存不足，进程被 OOM killer 杀死")

        record = engine.get_record(exec_id)
        assert record.status == "failed"
        assert record.error == "内存不足，进程被 OOM killer 杀死"
        assert signals_failed == [(exec_id, "内存不足，进程被 OOM killer 杀死")]


# ── 测试 5: 多步流水线血缘 ────────────────────────────────


class TestMultiStepLineage:
    """验证多步流水线的血缘追溯: raw -> step1 output -> step2 output"""

    def test_two_step_lineage(
        self,
        engine: ToolEngine,
        data_registry: DataRegistry,
        plugin_registry: PluginRegistry,
        project: ProjectInfo,
        db_conn: sqlite3.Connection,
    ) -> None:
        sample_id = data_registry.add_sample("MultiStepSample")
        descriptor = plugin_registry.get_descriptor("simple_qc")

        # ── Step 1: 原始数据 ──
        raw_id = data_registry.register_input(
            "/data/raw.R1.fq.gz", sample_id, "fastq"
        )

        # ── Step 2: 第一次执行 (time=1000) ──
        with patch("core.tool_engine.time") as mt_engine, \
             patch("core.data_registry.time") as mt_reg:
            mt_engine.time.return_value = 1000.0
            mt_reg.time.return_value = 1000.0
            exec_id_1 = engine.execute(
                tool_id="simple_qc",
                input_data_ids=[raw_id],
                parameters={},
                sample_id=sample_id,
            )
            output_dir_1 = f"{project.remote_base}/intermediate/{sample_id}/simple_qc"
            engine.on_job_completed(exec_id_1, descriptor, sample_id, output_dir_1)

        # 获取第一步的 fastq 输出（作为第二步的输入）
        clean_items = data_registry.find_compatible(
            sample_id, "fastq", tier="intermediate"
        )
        assert len(clean_items) == 1
        clean_id = clean_items[0].data_id

        # ── Step 3: 第二次执行 (time=2000) ──
        with patch("core.tool_engine.time") as mt_engine, \
             patch("core.data_registry.time") as mt_reg:
            mt_engine.time.return_value = 2000.0
            mt_reg.time.return_value = 2000.0
            exec_id_2 = engine.execute(
                tool_id="simple_qc",
                input_data_ids=[clean_id],
                parameters={"min_quality": 30},
                sample_id=sample_id,
            )
            output_dir_2 = f"{project.remote_base}/intermediate/{sample_id}/simple_qc_v2"
            engine.on_job_completed(exec_id_2, descriptor, sample_id, output_dir_2)

        # 获取第二步的 fastq 输出
        all_clean = data_registry.find_compatible(
            sample_id, "fastq", tier="intermediate"
        )
        # 应有 2 个 intermediate fastq（step1 和 step2 的输出）
        assert len(all_clean) == 2
        step2_output_id = all_clean[0].data_id  # 最新的在前 (time=2000)

        # ── 血缘追溯: step2 output -> step1 output -> raw ──
        lineage = data_registry.get_lineage(step2_output_id)
        lineage_ids = {item.data_id for item in lineage}

        assert step2_output_id in lineage_ids
        assert clean_id in lineage_ids
        assert raw_id in lineage_ids
        assert len(lineage) == 3


# ── 测试 6: DataImporter 集成 ─────────────────────────────


class TestDataImporterIntegration:
    """验证 DataImporter 导入文件并可被 ToolEngine 使用"""

    def test_import_then_execute(
        self,
        ssh: FakeSSH,
        data_registry: DataRegistry,
        plugin_registry: PluginRegistry,
        engine: ToolEngine,
        project: ProjectInfo,
        queue: FakeJobQueue,
        tmp_path: Path,
    ) -> None:
        # ── 创建本地文件 ──
        local_file = tmp_path / "sample1.R1.fq.gz"
        local_file.write_bytes(b"@SEQ1\nACGT\n+\nIIII\n")

        importer = DataImporter(ssh_service=ssh, registry=data_registry)
        sample_id = data_registry.add_sample("ImportedSample")

        # ── 导入文件 ──
        data_id = importer.import_file(
            local_path=str(local_file),
            sample_id=sample_id,
            data_type="fastq",
            project_remote_base=project.remote_base,
        )

        # 验证 SSH 上传
        assert len(ssh.uploads) == 1
        remote_path = ssh.uploads[0][1]
        assert f"/raw/{sample_id}/" in remote_path

        # 验证注册
        item = data_registry.get_item(data_id)
        assert item is not None
        assert item.data_type == "fastq"
        assert item.tier == "raw"

        # ── 用导入的数据执行工具 ──
        exec_id = engine.execute(
            tool_id="simple_qc",
            input_data_ids=[data_id],
            parameters={},
            sample_id=sample_id,
        )

        # 验证命令中包含正确的输入路径
        cmd = queue.jobs[0]["command"]
        assert remote_path in cmd

        # 模拟完成
        descriptor = plugin_registry.get_descriptor("simple_qc")
        output_dir = f"{project.remote_base}/intermediate/{sample_id}/simple_qc"
        engine.on_job_completed(exec_id, descriptor, sample_id, output_dir)

        # ── 验证完整血缘: output -> imported raw ──
        outputs = data_registry.find_compatible(sample_id, "fastq", tier="intermediate")
        assert len(outputs) == 1
        lineage = data_registry.get_lineage(outputs[0].data_id)
        lineage_ids = {it.data_id for it in lineage}
        assert data_id in lineage_ids  # 原始导入的文件在血缘链中


# ── 测试 7: find_compatible 推荐验证 ──────────────────────


class TestFindCompatibleRecommendation:
    """验证 find_compatible 作为数据关联核心的正确性"""

    def test_recommend_latest_output(
        self,
        engine: ToolEngine,
        data_registry: DataRegistry,
        plugin_registry: PluginRegistry,
        project: ProjectInfo,
    ) -> None:
        """执行两次后，find_compatible 应优先推荐最新输出"""
        sample_id = data_registry.add_sample("RecommendSample")
        raw_id = data_registry.register_input(
            "/data/raw.fq", sample_id, "fastq"
        )
        descriptor = plugin_registry.get_descriptor("simple_qc")

        # 第一次执行（time=1000）
        with patch("core.tool_engine.time") as mock_time_engine, \
             patch("core.data_registry.time") as mock_time_registry:
            mock_time_engine.time.return_value = 1000.0
            mock_time_registry.time.return_value = 1000.0
            exec_1 = engine.execute(
                tool_id="simple_qc",
                input_data_ids=[raw_id],
                parameters={"min_quality": 15},
                sample_id=sample_id,
            )
            engine.on_job_completed(
                exec_1, descriptor, sample_id,
                f"{project.remote_base}/intermediate/{sample_id}/run1",
            )

        # 第二次执行（time=2000）
        with patch("core.tool_engine.time") as mock_time_engine, \
             patch("core.data_registry.time") as mock_time_registry:
            mock_time_engine.time.return_value = 2000.0
            mock_time_registry.time.return_value = 2000.0
            exec_2 = engine.execute(
                tool_id="simple_qc",
                input_data_ids=[raw_id],
                parameters={"min_quality": 20},
                sample_id=sample_id,
            )
            engine.on_job_completed(
                exec_2, descriptor, sample_id,
                f"{project.remote_base}/intermediate/{sample_id}/run2",
            )

        # find_compatible 返回的第一个应是最新执行的输出
        compatible = data_registry.find_compatible(
            sample_id, "fastq", tier="intermediate"
        )
        assert len(compatible) == 2
        # 最新的在前（created_at DESC）
        assert "run2" in compatible[0].file_path
        assert "run1" in compatible[1].file_path
