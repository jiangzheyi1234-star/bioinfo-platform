"""ProjectExporter 单元测试"""

import csv
import json
import sqlite3
import time
from io import StringIO
from pathlib import Path

import pytest

from core.pipeline.project_exporter import ProjectExporter


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def db():
    """内存 SQLite 数据库"""
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
def populated_db(db):
    """带有完整流水线数据的数据库"""
    now = time.time()

    db.execute("INSERT INTO samples VALUES (?, ?, ?, ?)",
               ("smp_001", "water_sample", "river", "{}"))

    # fastp 执行（已完成）
    db.execute(
        "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_fastp", "smp_001", "fastp", "0.23.4",
         '{"qualified_quality_phred": 15, "length_required": 50, "thread": 4}',
         "completed", "pipeline", now, now + 60, None, 0, None, None),
    )

    # kraken2 执行（已完成）
    db.execute(
        "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_kraken2", "smp_001", "kraken2", "2.1.3",
         '{"confidence": 0.5, "threads": 8}',
         "completed", "pipeline", now + 60, now + 200, None, 0, None, None),
    )

    # 失败的执行（不应出现在论文导出中）
    db.execute(
        "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("exec_failed", "smp_001", "hostile", "1.1.0",
         '{}', "failed", "manual", now + 300, None, "OOM", 0, None, None),
    )

    # 数据项
    db.execute(
        "INSERT INTO data_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("dat_raw", "smp_001", "/data/raw/s1.fq.gz", "fastq", "raw",
         None, now, "{}"),
    )
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_fastp", "dat_raw", "input"))
    db.execute(
        "INSERT INTO data_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("dat_clean", "smp_001", "/data/inter/s1.clean.fq.gz", "fastq",
         "intermediate", "exec_fastp", now + 60, "{}"),
    )
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_fastp", "dat_clean", "output"))
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_kraken2", "dat_clean", "input"))
    db.execute(
        "INSERT INTO data_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("dat_kreport", "smp_001", "/data/result/s1.kreport", "kreport",
         "result", "exec_kraken2", now + 200, "{}"),
    )
    db.execute("INSERT INTO execution_io VALUES (?, ?, ?)",
               ("exec_kraken2", "dat_kreport", "output"))

    db.commit()
    return db


@pytest.fixture
def plugin_descriptors():
    """工具描述符"""
    return {
        "fastp": {
            "id": "fastp",
            "name": "fastp",
            "version": "0.23.4",
            "conda_env": "fastp_env",
            "databases": [],
            "methods_template": (
                "Raw reads were quality-filtered using fastp v{version} "
                "(minimum quality score = {qualified_quality_phred}, "
                "minimum length = {length_required})."
            ),
        },
        "kraken2": {
            "id": "kraken2",
            "name": "Kraken2",
            "version": "2.1.3",
            "conda_env": "kraken2_env",
            "databases": [
                {"id": "kraken2_standard", "description": "Kraken2 Standard DB"},
            ],
            "methods_template": (
                "Taxonomic classification was performed using Kraken2 v{version} "
                "with the {db_name} database (confidence threshold = {confidence})."
            ),
        },
    }


# ── Methods 生成测试 ──────────────────────────────────────


class TestGenerateMethods:
    """测试 Methods 段落生成"""

    def test_methods_empty_db(self, db):
        exporter = ProjectExporter(db)
        text = exporter.generate_methods()
        assert "No analysis executions" in text

    def test_methods_with_templates(self, populated_db, plugin_descriptors):
        exporter = ProjectExporter(populated_db, plugin_descriptors)
        text = exporter.generate_methods()

        assert "fastp v0.23.4" in text
        assert "quality score = 15" in text
        assert "Kraken2 v2.1.3" in text
        assert "confidence threshold = 0.5" in text

    def test_methods_skips_failed(self, populated_db, plugin_descriptors):
        """失败的执行不应出现在 Methods 中"""
        exporter = ProjectExporter(populated_db, plugin_descriptors)
        text = exporter.generate_methods()
        assert "hostile" not in text.lower() or "Hostile" not in text

    def test_methods_without_descriptors(self, populated_db):
        """没有描述符时使用默认文本"""
        exporter = ProjectExporter(populated_db, plugin_descriptors={})
        text = exporter.generate_methods()
        assert "default parameters" in text

    def test_methods_deduplicates_tools(self, db, plugin_descriptors):
        """同一工具执行多次只描述一次"""
        now = time.time()
        db.execute("INSERT INTO samples VALUES (?, ?, ?, ?)",
                   ("s1", "sample", None, "{}"))
        for i in range(3):
            db.execute(
                "INSERT INTO executions VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"e_{i}", "s1", "fastp", "0.23.4",
                 '{"qualified_quality_phred": 15, "length_required": 50}',
                 "completed", "manual", now + i, now + i + 10,
                 None, 0, None, None),
            )
        db.commit()

        exporter = ProjectExporter(db, plugin_descriptors)
        text = exporter.generate_methods()
        assert text.count("fastp v0.23.4") == 1


# ── Parameters CSV 测试 ───────────────────────────────────


class TestGenerateParametersCSV:
    """测试参数 CSV 生成"""

    def test_csv_empty_db(self, db):
        exporter = ProjectExporter(db)
        csv_text = exporter.generate_parameters_csv()
        reader = csv.reader(StringIO(csv_text))
        rows = list(reader)
        assert len(rows) == 1  # 只有表头
        assert rows[0][0] == "tool_id"

    def test_csv_with_data(self, populated_db):
        exporter = ProjectExporter(populated_db)
        csv_text = exporter.generate_parameters_csv()
        reader = csv.reader(StringIO(csv_text))
        rows = list(reader)

        # 表头 + fastp 3参数 + kraken2 2参数 = 6 行
        assert len(rows) >= 4
        assert rows[0] == [
            "tool_id", "tool_version", "parameter_name",
            "parameter_value", "sample_id", "execution_id",
        ]

        # 验证 fastp 参数存在
        fastp_rows = [r for r in rows if r[0] == "fastp"]
        assert len(fastp_rows) == 3
        param_names = {r[2] for r in fastp_rows}
        assert "thread" in param_names

    def test_csv_excludes_failed(self, populated_db):
        """失败的执行不出现在 CSV 中"""
        exporter = ProjectExporter(populated_db)
        csv_text = exporter.generate_parameters_csv()
        assert "exec_failed" not in csv_text


# ── Paper Export 测试 ─────────────────────────────────────


class TestExportForPaper:
    """测试论文导出"""

    def test_export_creates_files(self, populated_db, plugin_descriptors, tmp_path):
        exporter = ProjectExporter(populated_db, plugin_descriptors)
        result = exporter.export_for_paper(tmp_path / "paper")

        assert "methods.txt" in result
        assert "parameters.csv" in result
        assert Path(result["methods.txt"]).exists()
        assert Path(result["parameters.csv"]).exists()

    def test_export_methods_content(self, populated_db, plugin_descriptors, tmp_path):
        exporter = ProjectExporter(populated_db, plugin_descriptors)
        exporter.export_for_paper(tmp_path)

        methods = (tmp_path / "methods.txt").read_text(encoding="utf-8")
        assert "fastp" in methods


# ── Reproducibility Export 测试 ───────────────────────────


class TestExportForReproducibility:
    """测试可复现性导出"""

    def test_export_creates_snakefile(self, populated_db, plugin_descriptors, tmp_path):
        exporter = ProjectExporter(populated_db, plugin_descriptors)
        result = exporter.export_for_reproducibility(tmp_path / "repro")

        assert "Snakefile" in result
        assert "config.yaml" in result
        assert Path(result["Snakefile"]).exists()
        assert Path(result["config.yaml"]).exists()

    def test_snakefile_content(self, populated_db, plugin_descriptors, tmp_path):
        exporter = ProjectExporter(populated_db, plugin_descriptors)
        exporter.export_for_reproducibility(tmp_path)

        snakefile = (tmp_path / "Snakefile").read_text(encoding="utf-8")
        assert "rule" in snakefile

    def test_config_yaml_content(self, populated_db, plugin_descriptors, tmp_path):
        exporter = ProjectExporter(populated_db, plugin_descriptors)
        exporter.export_for_reproducibility(tmp_path)

        import yaml
        config = yaml.safe_load(
            (tmp_path / "config.yaml").read_text(encoding="utf-8")
        )
        assert "samples" in config
        assert "tools" in config
        assert "smp_001" in config["samples"]

    def test_export_by_sample(self, populated_db, plugin_descriptors, tmp_path):
        exporter = ProjectExporter(populated_db, plugin_descriptors)
        result = exporter.export_for_reproducibility(
            tmp_path, sample_id="smp_001",
        )
        assert Path(result["Snakefile"]).exists()


# ── Archive Export 测试 ───────────────────────────────────


class TestExportArchive:
    """测试归档导出"""

    def test_archive_creates_zip(self, populated_db, plugin_descriptors, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        # 创建一个假的 project.db
        (project_dir / "project.db").write_bytes(b"fake db")

        exporter = ProjectExporter(
            populated_db, plugin_descriptors, project_name="TestProject",
        )
        archive_path = exporter.export_archive(
            tmp_path / "output", project_dir,
        )

        assert archive_path.endswith(".zip")
        assert Path(archive_path).exists()

    def test_archive_contains_metadata(self, populated_db, tmp_path):
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "project.db").write_bytes(b"fake db")

        exporter = ProjectExporter(populated_db, project_name="TestProject")
        archive_path = exporter.export_archive(
            tmp_path / "output", project_dir,
        )

        # 解压验证
        import zipfile
        with zipfile.ZipFile(archive_path) as zf:
            names = zf.namelist()
            assert "metadata.json" in names
            metadata = json.loads(zf.read("metadata.json"))
            assert metadata["project_name"] == "TestProject"
            assert "h2ometa_version" in metadata


# ── 工具摘要测试 ──────────────────────────────────────────


class TestToolsSummary:
    """测试内部辅助方法"""

    def test_tools_summary(self, populated_db):
        exporter = ProjectExporter(populated_db)
        summary = exporter._get_tools_summary()
        tool_ids = {t["tool_id"] for t in summary}
        assert "fastp" in tool_ids
        assert "kraken2" in tool_ids
        # hostile 是 failed，不在 completed 中
        assert "hostile" not in tool_ids

    def test_samples_count(self, populated_db):
        exporter = ProjectExporter(populated_db)
        assert exporter._get_samples_count() == 1

    def test_executions_count(self, populated_db):
        exporter = ProjectExporter(populated_db)
        assert exporter._get_executions_count() == 3  # 包括 failed
