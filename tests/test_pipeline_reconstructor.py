"""PipelineReconstructor 单元测试"""

import json
import sqlite3
import time

import pytest

from core.pipeline_reconstructor import (
    DAGEdge,
    DAGNode,
    ExecutionDAG,
    PipelineReconstructor,
)


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def db():
    """内存 SQLite 数据库，已创建 schema"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE samples (
            sample_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source TEXT,
            metadata TEXT
        );
        CREATE TABLE executions (
            execution_id TEXT PRIMARY KEY,
            sample_id TEXT,
            tool_id TEXT NOT NULL,
            tool_version TEXT,
            parameters TEXT NOT NULL,
            status TEXT NOT NULL,
            triggered_by TEXT,
            created_at REAL NOT NULL,
            completed_at REAL,
            error TEXT,
            retry_count INTEGER DEFAULT 0,
            retry_of TEXT,
            remote_job_id TEXT
        );
        CREATE TABLE data_items (
            data_id TEXT PRIMARY KEY,
            sample_id TEXT,
            file_path TEXT NOT NULL,
            data_type TEXT NOT NULL,
            tier TEXT NOT NULL,
            produced_by TEXT,
            created_at REAL NOT NULL,
            metadata TEXT
        );
        CREATE TABLE execution_io (
            execution_id TEXT,
            data_id TEXT,
            direction TEXT,
            PRIMARY KEY (execution_id, data_id, direction)
        );
    """)
    yield conn
    conn.close()


@pytest.fixture
def three_stage_pipeline(db):
    """创建 fastp → hostile → kraken2 三阶段流水线测试数据"""
    now = time.time()

    # 样本
    db.execute("INSERT INTO samples VALUES (?, ?, ?, ?)",
               ("smp_001", "test_sample", "water", "{}"))

    # 原始输入数据
    db.execute(
        "INSERT INTO data_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("dat_raw", "smp_001", "/data/raw/sample.R1.fq.gz", "fastq", "raw",
         None, now, "{}"),
    )

    # fastp 执行
    db.execute(
        "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_fastp", "smp_001", "fastp", "0.23.4", '{"thread": 4}',
         "completed", "pipeline", now, now + 100, None, 0, None, None),
    )
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_fastp", "dat_raw", "input"))
    db.execute(
        "INSERT INTO data_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("dat_fastp_out", "smp_001", "/data/inter/sample.clean.R1.fq.gz",
         "fastq", "intermediate", "exec_fastp", now + 100, "{}"),
    )
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_fastp", "dat_fastp_out", "output"))

    # hostile 执行
    db.execute(
        "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_hostile", "smp_001", "hostile", "1.1.0",
         '{"aligner": "bowtie2"}', "completed", "pipeline",
         now + 100, now + 200, None, 0, None, None),
    )
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_hostile", "dat_fastp_out", "input"))
    db.execute(
        "INSERT INTO data_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("dat_hostile_out", "smp_001", "/data/inter/sample.host_removed.R1.fq.gz",
         "fastq", "intermediate", "exec_hostile", now + 200, "{}"),
    )
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_hostile", "dat_hostile_out", "output"))

    # kraken2 执行
    db.execute(
        "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_kraken2", "smp_001", "kraken2", "2.1.3",
         '{"confidence": 0.5}', "completed", "pipeline",
         now + 200, now + 300, None, 0, None, None),
    )
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_kraken2", "dat_hostile_out", "input"))
    db.execute(
        "INSERT INTO data_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("dat_kreport", "smp_001", "/data/result/sample.kreport",
         "kreport", "result", "exec_kraken2", now + 300, "{}"),
    )
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_kraken2", "dat_kreport", "output"))

    db.commit()
    return db


# ── DAG 数据类测试 ─────────────────────────────────────────


class TestDAGDataClasses:
    """测试 DAG 数据类"""

    def test_dag_node_creation(self):
        node = DAGNode(
            execution_id="exec_1", tool_id="fastp", tool_version="0.23.4",
            sample_id="smp_1", parameters={"thread": 4}, status="completed",
            created_at=1000.0,
        )
        assert node.execution_id == "exec_1"
        assert node.input_data_ids == []
        assert node.output_data_ids == []

    def test_dag_edge_creation(self):
        edge = DAGEdge(
            from_execution_id="exec_1", to_execution_id="exec_2",
            data_id="dat_1", data_type="fastq", file_path="/path/to/file",
        )
        assert edge.from_execution_id == "exec_1"

    def test_dag_roots_and_leaves(self):
        n1 = DAGNode("e1", "fastp", "0.23", "s1", {}, "completed", 1.0)
        n2 = DAGNode("e2", "hostile", "1.1", "s1", {}, "completed", 2.0)
        edge = DAGEdge("e1", "e2", "d1", "fastq", "/f")
        dag = ExecutionDAG(nodes=[n1, n2], edges=[edge], sample_ids=["s1"])

        assert len(dag.roots) == 1
        assert dag.roots[0].execution_id == "e1"
        assert len(dag.leaves) == 1
        assert dag.leaves[0].execution_id == "e2"

    def test_topological_order(self):
        n1 = DAGNode("e1", "fastp", "", "s1", {}, "completed", 1.0)
        n2 = DAGNode("e2", "hostile", "", "s1", {}, "completed", 2.0)
        n3 = DAGNode("e3", "kraken2", "", "s1", {}, "completed", 3.0)
        edges = [
            DAGEdge("e1", "e2", "d1", "fastq", "/f1"),
            DAGEdge("e2", "e3", "d2", "fastq", "/f2"),
        ]
        dag = ExecutionDAG(nodes=[n1, n2, n3], edges=edges, sample_ids=["s1"])

        order = dag.topological_order()
        ids = [n.execution_id for n in order]
        assert ids == ["e1", "e2", "e3"]

    def test_topological_order_empty(self):
        dag = ExecutionDAG(nodes=[], edges=[], sample_ids=[])
        assert dag.topological_order() == []

    def test_get_node(self):
        n1 = DAGNode("e1", "fastp", "", "s1", {}, "completed", 1.0)
        dag = ExecutionDAG(nodes=[n1], edges=[], sample_ids=["s1"])
        assert dag.get_node("e1") is n1
        assert dag.get_node("nonexistent") is None


# ── PipelineReconstructor 重建测试 ─────────────────────────


class TestRebuildDAG:
    """测试 DAG 重建"""

    def test_rebuild_empty_db(self, db):
        reconstructor = PipelineReconstructor(db)
        dag = reconstructor.rebuild_dag()
        assert len(dag.nodes) == 0
        assert len(dag.edges) == 0

    def test_rebuild_three_stage(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        dag = reconstructor.rebuild_dag()

        assert len(dag.nodes) == 3
        assert len(dag.edges) == 2
        assert len(dag.sample_ids) == 1

        # 验证边的方向
        edge_pairs = [(e.from_execution_id, e.to_execution_id) for e in dag.edges]
        assert ("exec_fastp", "exec_hostile") in edge_pairs
        assert ("exec_hostile", "exec_kraken2") in edge_pairs

    def test_rebuild_by_sample(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)

        dag = reconstructor.rebuild_dag(sample_id="smp_001")
        assert len(dag.nodes) == 3

        dag_empty = reconstructor.rebuild_dag(sample_id="nonexistent")
        assert len(dag_empty.nodes) == 0

    def test_roots_and_leaves_from_db(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        dag = reconstructor.rebuild_dag()

        assert len(dag.roots) == 1
        assert dag.roots[0].tool_id == "fastp"
        assert len(dag.leaves) == 1
        assert dag.leaves[0].tool_id == "kraken2"

    def test_topological_order_from_db(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        dag = reconstructor.rebuild_dag()

        order = dag.topological_order()
        tool_ids = [n.tool_id for n in order]
        assert tool_ids == ["fastp", "hostile", "kraken2"]

    def test_node_io_data(self, three_stage_pipeline):
        """每个节点应有正确的输入/输出数据 ID"""
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        dag = reconstructor.rebuild_dag()

        fastp_node = dag.get_node("exec_fastp")
        assert fastp_node is not None
        assert "dat_raw" in fastp_node.input_data_ids
        assert "dat_fastp_out" in fastp_node.output_data_ids


# ── Execution Lineage 测试 ────────────────────────────────


class TestExecutionLineage:
    """测试执行血缘追溯"""

    def test_lineage_leaf_node(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        lineage = reconstructor.get_execution_lineage("exec_kraken2")

        assert len(lineage) == 3
        # depth DESC: fastp(2) → hostile(1) → kraken2(0)
        assert lineage[0]["tool_id"] == "fastp"
        assert lineage[0]["depth"] == 2
        assert lineage[-1]["tool_id"] == "kraken2"
        assert lineage[-1]["depth"] == 0

    def test_lineage_root_node(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        lineage = reconstructor.get_execution_lineage("exec_fastp")

        # 根节点只有自身
        assert len(lineage) == 1
        assert lineage[0]["tool_id"] == "fastp"

    def test_lineage_nonexistent(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        lineage = reconstructor.get_execution_lineage("nonexistent")
        assert len(lineage) == 0


# ── Snakefile 生成测试 ─────────────────────────────────────


class TestGenerateSnakefile:
    """测试 Snakefile 生成"""

    def test_empty_dag_snakefile(self, db):
        reconstructor = PipelineReconstructor(db)
        dag = reconstructor.rebuild_dag()
        content = reconstructor.generate_snakefile(dag)
        assert "空流水线" in content

    def test_snakefile_has_rules(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        dag = reconstructor.rebuild_dag()
        content = reconstructor.generate_snakefile(dag)

        assert "rule all:" in content
        assert "rule fastp_" in content
        assert "rule hostile_" in content
        assert "rule kraken2_" in content
        assert "input:" in content
        assert "output:" in content

    def test_snakefile_with_descriptors(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        dag = reconstructor.rebuild_dag()
        descriptors = {
            "fastp": {"conda_env": "fastp_env"},
            "hostile": {"conda_env": "hostile_env"},
        }
        content = reconstructor.generate_snakefile(dag, descriptors)
        assert 'conda: "fastp_env"' in content
        assert 'conda: "hostile_env"' in content

    def test_snakefile_contains_file_paths(self, three_stage_pipeline):
        reconstructor = PipelineReconstructor(three_stage_pipeline)
        dag = reconstructor.rebuild_dag()
        content = reconstructor.generate_snakefile(dag)

        assert "sample.clean.R1.fq.gz" in content
        assert "sample.kreport" in content


# ── 多样本 DAG 测试 ───────────────────────────────────────


class TestMultiSampleDAG:
    """测试多样本 DAG"""

    def test_two_samples_independent(self, db):
        now = time.time()

        for i, sid in enumerate(["smp_a", "smp_b"]):
            db.execute("INSERT INTO samples VALUES (?, ?, ?, ?)",
                       (sid, f"sample_{i}", None, "{}"))
            db.execute(
                "INSERT INTO executions VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"exec_{sid}", sid, "fastp", "0.23", '{}', "completed",
                 "manual", now + i, None, None, 0, None, None),
            )

        db.commit()

        reconstructor = PipelineReconstructor(db)
        dag = reconstructor.rebuild_dag()

        assert len(dag.nodes) == 2
        assert len(dag.edges) == 0  # 独立的，无共享数据
        assert len(dag.sample_ids) == 2
