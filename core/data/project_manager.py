"""项目管理器 — 管理项目生命周期、SQLite 数据库初始化和项目索引。"""

import json
import logging
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

SCHEMA_SQL = """\
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
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS data_items (
    data_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    data_type TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


@dataclass
class ProjectInfo:
    project_id: str
    name: str
    description: str
    created_at: float
    status: str = "active"

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
        )


class ProjectManager:
    def __init__(
        self, projects_root: Optional[Path] = None, index_path: Optional[Path] = None
    ):
        self._root = projects_root or DEFAULT_PROJECTS_ROOT
        self._index_path = index_path or DEFAULT_INDEX_PATH
        self._current: Optional[ProjectInfo] = None
        self._db: Optional[sqlite3.Connection] = None
        self._index: dict = {}

        self._root.mkdir(parents=True, exist_ok=True)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_index()

    def create_project(self, name: str, description: str = "") -> str:
        if not name.strip():
            raise ValueError("项目名称不能为空")

        pid = f"proj_{uuid.uuid4().hex[:12]}"
        project = ProjectInfo(pid, name.strip(), description.strip(), time.time())

        (self._root / pid).mkdir(parents=True)
        self._init_db(self._root / pid / "project.db")

        self._index[pid] = project.to_dict()
        self._save_index()
        logger.info("项目已创建: %s", name)
        return pid

    def open_project(self, project_id: str) -> ProjectInfo:
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        p = ProjectInfo.from_dict(self._index[project_id])
        if p.status == "archived":
            raise ValueError("项目已归档")

        self._close_db()
        self._db = sqlite3.connect(str(self._root / project_id / "project.db"))
        self._db.row_factory = sqlite3.Row
        self._current = p
        logger.info("项目已打开: %s", p.name)
        return p

    def list_projects(self) -> list[ProjectInfo]:
        return sorted(
            [ProjectInfo.from_dict(d) for d in self._index.values()],
            key=lambda p: -p.created_at,
        )

    def update_project(
        self, project_id: str, name: str = None, description: str = None
    ) -> ProjectInfo:
        if project_id not in self._index:
            raise KeyError(f"项目不存在")

        d = self._index[project_id]
        if name:
            d["name"] = name.strip()
        if description:
            d["description"] = description.strip()
        self._save_index()
        return ProjectInfo.from_dict(d)

    def archive_project(self, project_id: str):
        self._index[project_id]["status"] = "archived"
        self._save_index()
        if self._current and self._current.project_id == project_id:
            self._close_db()
            self._current = None

    def delete_project(self, project_id: str):
        if self._current and self._current.project_id == project_id:
            self._close_db()
        pdir = self._root / project_id
        if pdir.exists():
            shutil.rmtree(pdir)
        del self._index[project_id]
        self._save_index()

    @property
    def current_project(self):
        return self._current

    @property
    def db(self):
        if not self._db:
            raise RuntimeError("没有打开的项目")
        return self._db

    def close(self):
        self._close_db()
        self._current = None

    def _load_index(self):
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text())
            except Exception:
                self._index = {}

    def _save_index(self):
        self._index_path.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2)
        )

    def _init_db(self, path: Path):
        c = sqlite3.connect(str(path))
        c.executescript(SCHEMA_SQL)
        c.commit()
        c.close()

    def _close_db(self):
        if self._db:
            self._db.close()
            self._db = None
