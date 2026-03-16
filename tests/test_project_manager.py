"""ProjectManager 单元测试"""

import json
import sqlite3
from pathlib import Path

import pytest
from PyQt6.QtCore import QObject

from core.data.project_manager import ProjectInfo, ProjectManager, _SCHEMA_SQL


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture()
def pm(tmp_path: Path) -> ProjectManager:
    """创建使用临时目录的 ProjectManager 实例"""
    projects_root = tmp_path / "projects"
    index_path = tmp_path / "projects.json"
    manager = ProjectManager(projects_root=projects_root, index_path=index_path)
    yield manager
    manager.close()


# ── ProjectInfo 数据类 ────────────────────────────────────


class TestProjectInfo:
    """ProjectInfo 序列化/反序列化测试"""

    def test_to_dict_round_trip(self) -> None:
        info = ProjectInfo(
            project_id="proj_abc123",
            name="测试项目",
            description="这是一个测试",
            created_at=1000.0,
            status="active",
            remote_base="/h2ometa/projects/proj_abc123",
        )
        data = info.to_dict()
        restored = ProjectInfo.from_dict(data)
        assert restored.project_id == info.project_id
        assert restored.name == info.name
        assert restored.description == info.description
        assert restored.created_at == info.created_at
        assert restored.status == info.status
        assert restored.remote_base == info.remote_base

    def test_from_dict_with_defaults(self) -> None:
        data = {"project_id": "proj_x", "name": "最小数据"}
        info = ProjectInfo.from_dict(data)
        assert info.description == ""
        assert info.status == "active"
        assert info.created_at == 0.0


# ── ProjectManager.create_project ─────────────────────────


class TestCreateProject:
    """create_project 方法测试"""

    def test_create_project_basic(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("我的项目", "测试描述")
        assert project_id.startswith("proj_")
        assert len(project_id) == 17  # "proj_" + 12 hex chars

    def test_create_project_uses_hidden_remote_root(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("remote base test")
        assert pm._index[project_id]["remote_base"] == f"~/.h2ometa/projects/{project_id}"

    def test_create_project_creates_directory(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("目录测试")
        project_dir = pm._projects_root / project_id
        assert project_dir.exists()
        assert (project_dir / "project.db").exists()

    def test_create_project_initializes_schema(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("Schema 测试")
        db_path = pm._projects_root / project_id / "project.db"
        conn = sqlite3.connect(str(db_path))
        # 检查四张表都存在
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(t[0] for t in tables)
        assert "data_items" in table_names
        assert "execution_io" in table_names
        assert "executions" in table_names
        assert "samples" in table_names
        conn.close()

    def test_create_project_saves_index(self, pm: ProjectManager) -> None:
        pm.create_project("索引测试")
        assert pm._index_path.exists()
        data = json.loads(pm._index_path.read_text(encoding="utf-8"))
        assert len(data) == 1

    def test_create_project_emits_signal(self, pm: ProjectManager) -> None:
        received: list[str] = []
        pm.project_created.connect(received.append)
        project_id = pm.create_project("信号测试")
        assert received == [project_id]

    def test_create_project_empty_name_raises(self, pm: ProjectManager) -> None:
        with pytest.raises(ValueError, match="项目名称不能为空"):
            pm.create_project("")
        with pytest.raises(ValueError, match="项目名称不能为空"):
            pm.create_project("   ")

    def test_create_multiple_projects(self, pm: ProjectManager) -> None:
        id1 = pm.create_project("项目一")
        id2 = pm.create_project("项目二")
        assert id1 != id2
        assert len(pm._index) == 2


# ── ProjectManager.open_project ───────────────────────────


class TestOpenProject:
    """open_project 方法测试"""

    def test_open_project_basic(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("打开测试")
        project = pm.open_project(project_id)
        assert project.name == "打开测试"
        assert pm.current_project is not None
        assert pm.current_project.project_id == project_id

    def test_open_project_db_connection(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("连接测试")
        pm.open_project(project_id)
        # db 属性应返回有效连接
        conn = pm.db
        assert conn is not None
        # 可以正常执行查询
        result = conn.execute("SELECT count(*) FROM samples").fetchone()
        assert result[0] == 0

    def test_open_project_emits_signal(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("信号测试")
        received: list[str] = []
        pm.project_opened.connect(received.append)
        pm.open_project(project_id)
        assert received == [project_id]

    def test_open_nonexistent_raises(self, pm: ProjectManager) -> None:
        with pytest.raises(KeyError, match="项目不存在"):
            pm.open_project("proj_nonexistent")

    def test_open_archived_raises(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("归档项目")
        pm.archive_project(project_id)
        with pytest.raises(ValueError, match="项目已归档"):
            pm.open_project(project_id)

    def test_open_switches_connection(self, pm: ProjectManager) -> None:
        id1 = pm.create_project("项目A")
        id2 = pm.create_project("项目B")
        pm.open_project(id1)
        conn1 = pm.db
        pm.open_project(id2)
        conn2 = pm.db
        # 切换后 current_project 应更新
        assert pm.current_project.project_id == id2


# ── ProjectManager.list_projects ──────────────────────────


class TestListProjects:
    """list_projects 方法测试"""

    def test_list_empty(self, pm: ProjectManager) -> None:
        assert pm.list_projects() == []

    def test_list_multiple(self, pm: ProjectManager) -> None:
        pm.create_project("项目A")
        pm.create_project("项目B")
        projects = pm.list_projects()
        assert len(projects) == 2

    def test_list_order_by_time(self, pm: ProjectManager) -> None:
        pm.create_project("先创建")
        pm.create_project("后创建")
        projects = pm.list_projects()
        # 倒序排列，最新的在前
        assert projects[0].name == "后创建"
        assert projects[1].name == "先创建"


# ── ProjectManager.archive_project ────────────────────────


class TestArchiveProject:
    """archive_project 方法测试"""

    def test_archive_basic(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("待归档")
        pm.archive_project(project_id)
        projects = pm.list_projects()
        assert projects[0].status == "archived"

    def test_archive_emits_signal(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("信号测试")
        received: list[str] = []
        pm.project_archived.connect(received.append)
        pm.archive_project(project_id)
        assert received == [project_id]

    def test_archive_current_project_clears_state(self, pm: ProjectManager) -> None:
        project_id = pm.create_project("当前项目")
        pm.open_project(project_id)
        assert pm.current_project is not None
        pm.archive_project(project_id)
        assert pm.current_project is None

    def test_archive_nonexistent_raises(self, pm: ProjectManager) -> None:
        with pytest.raises(KeyError, match="项目不存在"):
            pm.archive_project("proj_nonexistent")


# ── ProjectManager.db 属性 ────────────────────────────────


class TestDbProperty:
    """db 属性测试"""

    def test_db_without_project_raises(self, pm: ProjectManager) -> None:
        with pytest.raises(RuntimeError, match="没有打开的项目"):
            _ = pm.db


# ── ProjectManager 索引持久化 ─────────────────────────────


class TestIndexPersistence:
    """项目索引持久化测试"""

    def test_index_survives_reload(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        index_path = tmp_path / "projects.json"

        # 第一个实例创建项目
        pm1 = ProjectManager(projects_root=projects_root, index_path=index_path)
        project_id = pm1.create_project("持久化测试")
        pm1.close()

        # 第二个实例应能加载索引
        pm2 = ProjectManager(projects_root=projects_root, index_path=index_path)
        projects = pm2.list_projects()
        assert len(projects) == 1
        assert projects[0].project_id == project_id
        assert projects[0].name == "持久化测试"
        pm2.close()

    def test_corrupted_index_recovers(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        index_path = tmp_path / "projects.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("not valid json!!!", encoding="utf-8")

        # 损坏的索引不应导致崩溃
        pm = ProjectManager(projects_root=projects_root, index_path=index_path)
        assert pm.list_projects() == []
        pm.close()

    def test_missing_index_rebuilds_from_existing_project_dirs(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        index_path = tmp_path / "projects.json"

        pm1 = ProjectManager(projects_root=projects_root, index_path=index_path)
        project_id = pm1.create_project("恢复项目")
        pm1.close()

        index_path.unlink()

        pm2 = ProjectManager(projects_root=projects_root, index_path=index_path)
        projects = pm2.list_projects()
        assert len(projects) == 1
        assert projects[0].project_id == project_id
        assert projects[0].name == "恢复项目"
        assert json.loads(index_path.read_text(encoding="utf-8"))[project_id]["name"] == "恢复项目"
        pm2.close()

    def test_empty_index_recovers_project_from_backup_metadata(self, tmp_path: Path) -> None:
        projects_root = tmp_path / "projects"
        index_path = tmp_path / "projects.json"

        pm1 = ProjectManager(projects_root=projects_root, index_path=index_path)
        project_id = pm1.create_project("备份恢复项目")
        pm1.open_project(project_id)
        backup_dir = pm1.backup_current_project(reason="before_run")
        pm1.close()

        index_path.write_text("{}", encoding="utf-8")

        pm2 = ProjectManager(projects_root=projects_root, index_path=index_path)
        projects = pm2.list_projects()
        assert len(projects) == 1
        assert projects[0].project_id == project_id
        assert projects[0].name == "备份恢复项目"
        assert backup_dir.exists()
        pm2.close()


# ── SQLite Schema 校验 ────────────────────────────────────


class TestSchema:
    """Schema 完整性测试"""

    def test_schema_creates_all_tables(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(_SCHEMA_SQL)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert sorted(table_names) == ["data_items", "execution_io", "executions", "samples"]
        conn.close()

    def test_schema_status_check_constraint(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA_SQL)

        # 有效 status
        conn.execute(
            "INSERT INTO executions "
            "(execution_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("exec_1", "fastp", "{}", "pending", 1000.0),
        )
        conn.commit()

        # 无效 status 应失败
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO executions "
                "(execution_id, tool_id, parameters, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("exec_2", "fastp", "{}", "invalid_status", 1000.0),
            )
        conn.close()

    def test_schema_tier_check_constraint(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA_SQL)

        # 有效 tier
        conn.execute(
            "INSERT INTO data_items "
            "(data_id, file_path, data_type, tier, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("dat_1", "/path/file.fq", "fastq", "raw", 1000.0),
        )
        conn.commit()

        # 无效 tier 应失败
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO data_items "
                "(data_id, file_path, data_type, tier, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("dat_2", "/path/file.fq", "fastq", "invalid_tier", 1000.0),
            )
        conn.close()

    def test_schema_direction_check_constraint(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA_SQL)

        # 插入父表记录以满足外键约束
        conn.execute(
            "INSERT INTO executions "
            "(execution_id, tool_id, parameters, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("exec_1", "fastp", "{}", "pending", 1000.0),
        )
        conn.execute(
            "INSERT INTO data_items "
            "(data_id, file_path, data_type, tier, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("dat_1", "/path/file.fq", "fastq", "raw", 1000.0),
        )
        conn.commit()

        # 有效 direction
        conn.execute(
            "INSERT INTO execution_io (execution_id, data_id, direction) "
            "VALUES (?, ?, ?)",
            ("exec_1", "dat_1", "input"),
        )
        conn.commit()

        # 无效 direction 应失败
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO execution_io (execution_id, data_id, direction) "
                "VALUES (?, ?, ?)",
                ("exec_1", "dat_1", "invalid"),
            )
        conn.close()

    def test_schema_idempotent(self) -> None:
        """CREATE TABLE IF NOT EXISTS 应可重复执行"""
        conn = sqlite3.connect(":memory:")
        conn.executescript(_SCHEMA_SQL)
        conn.executescript(_SCHEMA_SQL)  # 再次执行不应报错
        conn.close()
