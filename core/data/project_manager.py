"""项目管理器 — 管理项目生命周期、SQLite 数据库初始化和项目索引。

每个项目存储在 ~/.h2ometa/projects/{project_id}/ 目录下，
包含一个 project.db SQLite 数据库文件。
项目索引保存在 ~/.h2ometa/projects.json 中。
"""

import json
import logging
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PROJECTS_ROOT = Path.home() / ".h2ometa" / "projects"
DEFAULT_INDEX_PATH = Path.home() / ".h2ometa" / "projects.json"
DEFAULT_LAST_PROJECT_PATH = Path.home() / ".h2ometa" / "last_project.txt"

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS samples (
    sample_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    sample_id TEXT REFERENCES samples(sample_id),
    tool_id TEXT NOT NULL,
    parameters TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    completed_at REAL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS data_items (
    data_id TEXT PRIMARY KEY,
    sample_id TEXT REFERENCES samples(sample_id),
    file_path TEXT NOT NULL,
    data_type TEXT NOT NULL,
    tier TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_io (
    execution_id TEXT REFERENCES executions(execution_id),
    data_id TEXT REFERENCES data_items(data_id),
    direction TEXT,
    PRIMARY KEY (execution_id, data_id, direction)
);
"""


@dataclass
class ProjectInfo:
    project_id: str
    name: str
    description: str
    created_at: float
    status: str = "active"
    remote_base: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectInfo":
        return cls(
            project_id=data["project_id"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=data.get("created_at", 0.0),
            status=data.get("status", "active"),
            remote_base=data.get("remote_base", ""),
        )


class ProjectManager:
    """项目生命周期管理器"""

    def __init__(
        self,
        projects_root: Optional[Path] = None,
        index_path: Optional[Path] = None,
    ) -> None:
        self._projects_root = projects_root or DEFAULT_PROJECTS_ROOT
        self._index_path = index_path or DEFAULT_INDEX_PATH
        self._current_project: Optional[ProjectInfo] = None
        self._db_conn: Optional[sqlite3.Connection] = None

        self._projects_root.mkdir(parents=True, exist_ok=True)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, dict] = self._load_index()

    def create_project(self, name: str, description: str = "") -> str:
        if not name or not name.strip():
            raise ValueError("项目名称不能为空")

        project_id = f"proj_{uuid.uuid4().hex[:12]}"
        project = ProjectInfo(
            project_id=project_id,
            name=name.strip(),
            description=description.strip(),
            created_at=time.time(),
            remote_base=f"~/.h2ometa/projects/{project_id}",
        )

        project_dir = self._projects_root / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        db_path = project_dir / "project.db"
        self._init_database(db_path)

        self._index[project_id] = project.to_dict()
        self._save_index()

        logger.info("项目已创建: %s (%s)", name, project_id)
        return project_id

    def open_project(self, project_id: str) -> ProjectInfo:
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        project = ProjectInfo.from_dict(self._index[project_id])
        if project.status == "archived":
            raise ValueError(f"项目已归档: {project_id}")

        db_path = self._projects_root / project_id / "project.db"
        if not db_path.exists():
            raise FileNotFoundError(f"项目数据库不存在: {db_path}")

        self._close_db()
        self._db_conn = sqlite3.connect(str(db_path))
        self._db_conn.row_factory = sqlite3.Row
        self._current_project = project

        logger.info("项目已打开: %s (%s)", project.name, project_id)
        return project

    def list_projects(self) -> list[ProjectInfo]:
        projects = [ProjectInfo.from_dict(data) for data in self._index.values()]
        projects.sort(key=lambda p: p.created_at, reverse=True)
        return projects

    def update_project(
        self, project_id: str, name: str | None = None, description: str | None = None
    ) -> ProjectInfo:
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        data = dict(self._index[project_id])
        if name is not None:
            if not name.strip():
                raise ValueError("项目名称不能为空")
            data["name"] = name.strip()
        if description is not None:
            data["description"] = description.strip()

        self._index[project_id] = data
        self._save_index()

        project = ProjectInfo.from_dict(data)
        if self._current_project and self._current_project.project_id == project_id:
            self._current_project = project

        logger.info("项目已更新: %s", project_id)
        return project

    def archive_project(self, project_id: str) -> None:
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        self._index[project_id]["status"] = "archived"
        self._save_index()

        if self._current_project and self._current_project.project_id == project_id:
            self._close_db()
            self._current_project = None

        logger.info("项目已归档: %s", project_id)

    def delete_project(self, project_id: str) -> None:
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        if self._current_project and self._current_project.project_id == project_id:
            self._close_db()
            self._current_project = None

        project_dir = self._projects_root / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)

        del self._index[project_id]
        self._save_index()
        logger.info("项目已删除: %s", project_id)

    @property
    def current_project(self) -> Optional[ProjectInfo]:
        return self._current_project

    @property
    def db(self) -> sqlite3.Connection:
        if self._db_conn is None:
            raise RuntimeError("没有打开的项目")
        return self._db_conn

    def close(self) -> None:
        self._close_db()
        self._current_project = None

    def _init_database(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
        conn.close()

    def _close_db(self) -> None:
        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None

    def _load_index(self) -> dict[str, dict]:
        if not self._index_path.exists():
            return {}
        try:
            text = self._index_path.read_text(encoding="utf-8")
            return json.loads(text)
        except (json.JSONDecodeError, OSError):
            logger.warning("加载项目索引失败，使用空索引")
            return {}

    def _save_index(self) -> None:
        text = json.dumps(self._index, ensure_ascii=False, indent=2)
        self._index_path.write_text(text, encoding="utf-8")
