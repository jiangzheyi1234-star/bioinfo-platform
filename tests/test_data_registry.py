"""DataRegistry 单元测试"""

import json
import sqlite3
import time
from unittest.mock import patch

import pytest

from core.data.data_registry import DataItem, DataRegistry, SampleInfo
from core.data.project_manager import _SCHEMA_SQL


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """创建内存 SQLite 数据库并初始化 schema"""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA_SQL)
    yield conn
    conn.close()


@pytest.fixture()
def registry(db_conn: sqlite3.Connection) -> DataRegistry:
    """创建 DataRegistry 实例"""
    return DataRegistry(db_conn)


@pytest.fixture()
def sample_id(registry: DataRegistry) -> str:
    """预先创建一个样本并返回其 ID"""
    return registry.add_sample("测试样本", source="water")


# ── SampleInfo 数据类 ─────────────────────────────────────


class TestSampleInfo:
    """SampleInfo 数据类测试"""

    def test_sample_defaults(self) -> None:
        s = SampleInfo(sample_id="smp_abc", name="样本A")
        assert s.source is None
        assert s.metadata == {}


# ── DataRegistry.add_sample ───────────────────────────────


class TestAddSample:
    """add_sample 方法测试"""

    def test_add_sample_basic(self, registry: DataRegistry) -> None:
        sid = registry.add_sample("样本A", source="human")
        assert sid.startswith("smp_")
        assert len(sid) == 16  # "smp_" + 12 hex

    def test_add_sample_with_metadata(self, registry: DataRegistry) -> None:
        sid = registry.add_sample(
            "样本B", source="soil", metadata={"site": "北京", "depth": "10cm"}
        )
        sample = registry.get_sample(sid)
        assert sample is not None
        assert sample.metadata["site"] == "北京"

    def test_add_sample_empty_name_raises(self, registry: DataRegistry) -> None:
        with pytest.raises(ValueError, match="样本名称不能为空"):
            registry.add_sample("")

    def test_get_sample_not_found(self, registry: DataRegistry) -> None:
        assert registry.get_sample("smp_nonexistent") is None

    def test_list_samples(self, registry: DataRegistry) -> None:
        registry.add_sample("样本1")
        registry.add_sample("样本2")
        samples = registry.list_samples()
        assert len(samples) == 2
        names = {s.name for s in samples}
        assert names == {"样本1", "样本2"}


# ── DataRegistry.register_input ───────────────────────────


class TestRegisterInput:
    """register_input 方法测试"""

    def test_register_input_basic(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        data_id = registry.register_input(
            file_path="/data/sample1.R1.fq.gz",
            sample_id=sample_id,
            data_type="fastq",
        )
        assert data_id.startswith("dat_")

        item = registry.get_item(data_id)
        assert item is not None
        assert item.file_path == "/data/sample1.R1.fq.gz"
        assert item.data_type == "fastq"
        assert item.tier == "raw"
        assert item.produced_by is None  # 原始上传

    def test_register_input_custom_tier(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        data_id = registry.register_input(
            file_path="/data/file.fasta",
            sample_id=sample_id,
            data_type="fasta",
            tier="intermediate",
        )
        item = registry.get_item(data_id)
        assert item.tier == "intermediate"

    def test_register_input_with_metadata(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        data_id = registry.register_input(
            file_path="/data/sample1.fq",
            sample_id=sample_id,
            data_type="fastq",
            metadata={"read_count": 1000000},
        )
        item = registry.get_item(data_id)
        assert item.metadata["read_count"] == 1000000

    def test_register_input_empty_path_raises(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        with pytest.raises(ValueError, match="file_path 不能为空"):
            registry.register_input("", sample_id, "fastq")

    def test_register_input_empty_data_type_raises(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        with pytest.raises(ValueError, match="data_type 不能为空"):
            registry.register_input("/path/file.fq", sample_id, "")

    def test_register_input_invalid_tier_raises(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        with pytest.raises(ValueError, match="tier 必须是"):
            registry.register_input(
                "/path/file.fq", sample_id, "fastq", tier="invalid"
            )

    def test_get_item_not_found(self, registry: DataRegistry) -> None:
        assert registry.get_item("dat_nonexistent") is None


# ── DataRegistry.register_output ──────────────────────────


class TestRegisterOutput:
    """register_output 方法测试"""

    def test_register_output_basic(
        self, registry: DataRegistry, sample_id: str, db_conn: sqlite3.Connection
    ) -> None:
        # 先创建一个 execution 记录
        exec_id = "exec_test001"
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (exec_id, sample_id, "fastp", "{}", "running", time.time()),
        )
        db_conn.commit()

        data_id = registry.register_output(
            execution_id=exec_id,
            file_path="/data/sample1.clean.R1.fq.gz",
            data_type="fastq",
            sample_id=sample_id,
            tier="intermediate",
        )

        item = registry.get_item(data_id)
        assert item is not None
        assert item.produced_by == exec_id
        assert item.tier == "intermediate"

        # 检查 execution_io 记录
        row = db_conn.execute(
            "SELECT * FROM execution_io WHERE execution_id = ? AND data_id = ?",
            (exec_id, data_id),
        ).fetchone()
        assert row is not None
        assert row["direction"] == "output"

    def test_register_output_empty_execution_id_raises(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        with pytest.raises(ValueError, match="execution_id 不能为空"):
            registry.register_output(
                execution_id="",
                file_path="/path/file.fq",
                data_type="fastq",
                sample_id=sample_id,
            )


# ── DataRegistry.add_execution_io ─────────────────────────


class TestAddExecutionIo:
    """add_execution_io 方法测试"""

    def test_add_execution_io_input(
        self, registry: DataRegistry, sample_id: str, db_conn: sqlite3.Connection
    ) -> None:
        # 创建父表记录以满足外键约束
        exec_id = "exec_io_test"
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (exec_id, sample_id, "fastp", "{}", "running", time.time()),
        )
        db_conn.commit()
        data_id = registry.register_input("/data/test.fq", sample_id, "fastq")

        registry.add_execution_io(exec_id, data_id, "input")
        # 验证记录已插入
        row = db_conn.execute(
            "SELECT * FROM execution_io WHERE execution_id = ? AND data_id = ?",
            (exec_id, data_id),
        ).fetchone()
        assert row is not None
        assert row["direction"] == "input"

    def test_add_execution_io_invalid_direction(self, registry: DataRegistry) -> None:
        with pytest.raises(ValueError, match="direction 必须是"):
            registry.add_execution_io("exec_1", "dat_1", "invalid")

    def test_add_execution_io_idempotent(
        self, registry: DataRegistry, sample_id: str, db_conn: sqlite3.Connection
    ) -> None:
        """重复插入相同记录不应报错（INSERT OR IGNORE）"""
        exec_id = "exec_idem_test"
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (exec_id, sample_id, "fastp", "{}", "running", time.time()),
        )
        db_conn.commit()
        data_id = registry.register_input("/data/test.fq", sample_id, "fastq")

        registry.add_execution_io(exec_id, data_id, "input")
        registry.add_execution_io(exec_id, data_id, "input")  # 不报错


# ── DataRegistry.find_compatible ──────────────────────────


class TestFindCompatible:
    """find_compatible 方法测试 — 数据关联核心逻辑"""

    def test_find_compatible_basic(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        registry.register_input("/data/s1.R1.fq", sample_id, "fastq")
        registry.register_input("/data/s1.R2.fq", sample_id, "fastq")
        registry.register_input("/data/s1.ref.fa", sample_id, "fasta")

        results = registry.find_compatible(sample_id, "fastq")
        assert len(results) == 2
        assert all(r.data_type == "fastq" for r in results)

    def test_find_compatible_empty(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        results = registry.find_compatible(sample_id, "kreport")
        assert results == []

    def test_find_compatible_cross_sample_isolation(
        self, registry: DataRegistry
    ) -> None:
        """不同样本的数据不应互相干扰"""
        sid_a = registry.add_sample("样本A")
        sid_b = registry.add_sample("样本B")

        registry.register_input("/data/a.fq", sid_a, "fastq")
        registry.register_input("/data/b.fq", sid_b, "fastq")

        results_a = registry.find_compatible(sid_a, "fastq")
        assert len(results_a) == 1
        assert results_a[0].file_path == "/data/a.fq"

        results_b = registry.find_compatible(sid_b, "fastq")
        assert len(results_b) == 1
        assert results_b[0].file_path == "/data/b.fq"

    def test_find_compatible_with_tier_filter(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        registry.register_input("/data/raw.fq", sample_id, "fastq", tier="raw")
        registry.register_input(
            "/data/clean.fq", sample_id, "fastq", tier="intermediate"
        )

        # 只查 raw
        raw_results = registry.find_compatible(sample_id, "fastq", tier="raw")
        assert len(raw_results) == 1
        assert raw_results[0].file_path == "/data/raw.fq"

        # 只查 intermediate
        int_results = registry.find_compatible(
            sample_id, "fastq", tier="intermediate"
        )
        assert len(int_results) == 1
        assert int_results[0].file_path == "/data/clean.fq"

        # 不过滤 tier
        all_results = registry.find_compatible(sample_id, "fastq")
        assert len(all_results) == 2

    def test_find_compatible_order_newest_first(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        """结果应按创建时间倒序排列"""
        with patch("core.data.data_registry.time") as mock_time:
            mock_time.time.return_value = 1000.0
            id1 = registry.register_input("/data/old.fq", sample_id, "fastq")
            mock_time.time.return_value = 2000.0
            id2 = registry.register_input("/data/new.fq", sample_id, "fastq")

        results = registry.find_compatible(sample_id, "fastq")
        assert len(results) == 2
        # 后注册的在前
        assert results[0].data_id == id2
        assert results[1].data_id == id1

    def test_find_compatible_multiple_types(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        """不同 data_type 不应混淆"""
        registry.register_input("/data/s1.fq", sample_id, "fastq")
        registry.register_input("/data/s1.kreport", sample_id, "kreport")
        registry.register_input("/data/s1.gff", sample_id, "gff")

        assert len(registry.find_compatible(sample_id, "fastq")) == 1
        assert len(registry.find_compatible(sample_id, "kreport")) == 1
        assert len(registry.find_compatible(sample_id, "gff")) == 1
        assert len(registry.find_compatible(sample_id, "tsv")) == 0


# ── DataRegistry.find_by_sample ───────────────────────────


class TestFindBySample:
    """find_by_sample 方法测试"""

    def test_find_by_sample_empty(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        results = registry.find_by_sample(sample_id)
        assert results == []

    def test_find_by_sample_multiple(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        registry.register_input("/data/s1.fq", sample_id, "fastq")
        registry.register_input("/data/s1.fa", sample_id, "fasta")
        results = registry.find_by_sample(sample_id)
        assert len(results) == 2


# ── DataRegistry.get_lineage ──────────────────────────────


class TestGetLineage:
    """get_lineage 血缘追溯测试"""

    def test_lineage_single_item(
        self, registry: DataRegistry, sample_id: str
    ) -> None:
        """没有上游的数据项，血缘链只有自身"""
        data_id = registry.register_input("/data/raw.fq", sample_id, "fastq")
        lineage = registry.get_lineage(data_id)
        assert len(lineage) == 1
        assert lineage[0].data_id == data_id

    def test_lineage_chain(
        self, registry: DataRegistry, sample_id: str, db_conn: sqlite3.Connection
    ) -> None:
        """raw.fq → [fastp exec] → clean.fq，追溯 clean.fq 的血缘应包含 raw.fq"""
        # 1. 注册原始文件
        raw_id = registry.register_input("/data/raw.fq", sample_id, "fastq")

        # 2. 创建 execution 记录
        exec_id = "exec_fastp_001"
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (exec_id, sample_id, "fastp", "{}", "completed", time.time()),
        )
        db_conn.commit()

        # 3. 记录输入关系
        registry.add_execution_io(exec_id, raw_id, "input")

        # 4. 注册输出文件
        clean_id = registry.register_output(
            execution_id=exec_id,
            file_path="/data/clean.fq",
            data_type="fastq",
            sample_id=sample_id,
            tier="intermediate",
        )

        # 追溯 clean.fq 的血缘
        lineage = registry.get_lineage(clean_id)
        lineage_ids = {item.data_id for item in lineage}
        assert clean_id in lineage_ids
        assert raw_id in lineage_ids
        assert len(lineage) == 2

    def test_lineage_three_levels(
        self, registry: DataRegistry, sample_id: str, db_conn: sqlite3.Connection
    ) -> None:
        """三级血缘链: raw.fq → clean.fq → kreport"""
        # Level 1: 原始文件
        raw_id = registry.register_input("/data/raw.fq", sample_id, "fastq")

        # Level 2: fastp 处理
        exec_fastp = "exec_fastp"
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (exec_fastp, sample_id, "fastp", "{}", "completed", time.time()),
        )
        db_conn.commit()
        registry.add_execution_io(exec_fastp, raw_id, "input")
        clean_id = registry.register_output(
            execution_id=exec_fastp,
            file_path="/data/clean.fq",
            data_type="fastq",
            sample_id=sample_id,
            tier="intermediate",
        )

        # Level 3: kraken2 分类
        exec_kraken = "exec_kraken"
        db_conn.execute(
            "INSERT INTO executions "
            "(execution_id, sample_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (exec_kraken, sample_id, "kraken2", "{}", "completed", time.time()),
        )
        db_conn.commit()
        registry.add_execution_io(exec_kraken, clean_id, "input")
        kreport_id = registry.register_output(
            execution_id=exec_kraken,
            file_path="/data/sample.kreport",
            data_type="kreport",
            sample_id=sample_id,
            tier="result",
        )

        # 从 kreport 追溯应到 raw.fq
        lineage = registry.get_lineage(kreport_id)
        lineage_ids = {item.data_id for item in lineage}
        assert kreport_id in lineage_ids
        assert clean_id in lineage_ids
        assert raw_id in lineage_ids
        assert len(lineage) == 3

    def test_lineage_nonexistent_item(self, registry: DataRegistry) -> None:
        """不存在的数据项应返回空列表"""
        lineage = registry.get_lineage("dat_nonexistent")
        assert lineage == []


# ── DataItem 数据类 ───────────────────────────────────────


class TestDataItem:
    """DataItem 数据类测试"""

    def test_data_item_defaults(self) -> None:
        item = DataItem(
            data_id="dat_abc",
            sample_id="smp_123",
            file_path="/path/file.fq",
            data_type="fastq",
            tier="raw",
        )
        assert item.produced_by is None
        assert item.created_at == 0.0
        assert item.metadata == {}
