"""项目管理器 — 管理项目生命周期、SQLite 数据库初始化和项目索引。

每个项目存储在 ~/.h2ometa/projects/{project_id}/ 目录下，
包含一个 project.db SQLite 数据库文件。
项目索引保存在 ~/.h2ometa/projects.json 中。
"""

import json
import logging
import shutil
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# 默认项目根目录
DEFAULT_PROJECTS_ROOT = Path.home() / ".h2ometa" / "projects"
DEFAULT_INDEX_PATH = Path.home() / ".h2ometa" / "projects.json"
DEFAULT_LAST_PROJECT_PATH = Path.home() / ".h2ometa" / "last_project.txt"

# SQLite Schema — 严格按照 CLAUDE.md 定义的四张表
_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS samples (
    sample_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT,
    metadata TEXT  -- JSON
);

CREATE TABLE IF NOT EXISTS executions (
    execution_id TEXT PRIMARY KEY,
    sample_id TEXT REFERENCES samples(sample_id),
    tool_id TEXT NOT NULL,
    tool_version TEXT,
    parameters TEXT NOT NULL,  -- JSON
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','retrying')),
    triggered_by TEXT,
    created_at REAL NOT NULL,
    completed_at REAL,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    retry_of TEXT REFERENCES executions(execution_id),
    remote_job_id TEXT,
    is_final_version INTEGER DEFAULT 0,  -- 标记为最终版本（用于导出和论文）
    archived_at REAL  -- 文件已清理的时间戳（数据库记录保留）
);

CREATE TABLE IF NOT EXISTS data_items (
    data_id TEXT PRIMARY KEY,
    sample_id TEXT REFERENCES samples(sample_id),
    file_path TEXT NOT NULL,
    data_type TEXT NOT NULL,  -- 文件格式: fastq, fasta, kreport, tsv, gff...
    tier TEXT NOT NULL CHECK(tier IN ('raw','intermediate','result')),
    produced_by TEXT REFERENCES executions(execution_id),
    created_at REAL NOT NULL,
    metadata TEXT  -- JSON
);

CREATE TABLE IF NOT EXISTS execution_io (
    execution_id TEXT REFERENCES executions(execution_id),
    data_id TEXT REFERENCES data_items(data_id),
    direction TEXT CHECK(direction IN ('input','output')),
    PRIMARY KEY (execution_id, data_id, direction)
);
"""


@dataclass
class ProjectInfo:
    """项目信息数据类"""

    project_id: str
    name: str
    description: str
    created_at: float
    status: str = "active"  # active / archived
    remote_base: str = ""   # ~/h2ometa/projects/{project_id}

    def to_dict(self) -> dict:
        """序列化为字典（用于 JSON 存储）"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectInfo":
        """从字典反序列化"""
        return cls(
            project_id=data["project_id"],
            name=data["name"],
            description=data.get("description", ""),
            created_at=data.get("created_at", 0.0),
            status=data.get("status", "active"),
            remote_base=data.get("remote_base", ""),
        )


class ProjectManager(QObject):
    """项目生命周期管理器

    负责创建、打开、列出、归档项目，以及管理 SQLite 数据库连接。
    继承 QObject 以便使用 pyqtSignal 通知 UI 层。
    """

    # 信号定义
    project_created = pyqtSignal(str)   # project_id
    project_opened = pyqtSignal(str)    # project_id
    project_archived = pyqtSignal(str)  # project_id
    project_deleted = pyqtSignal(str)   # project_id

    def __init__(
        self,
        projects_root: Optional[Path] = None,
        index_path: Optional[Path] = None,
        last_project_path: Optional[Path] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._projects_root = projects_root or DEFAULT_PROJECTS_ROOT
        self._index_path = index_path or DEFAULT_INDEX_PATH
        self._last_project_path = last_project_path or DEFAULT_LAST_PROJECT_PATH
        self._current_project: Optional[ProjectInfo] = None
        self._db_conn: Optional[sqlite3.Connection] = None

        # 确保根目录存在
        self._projects_root.mkdir(parents=True, exist_ok=True)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_project_path.parent.mkdir(parents=True, exist_ok=True)

        # 加载项目索引
        self._index: dict[str, dict] = self._load_index()
        self._restore_last_opened_project()

    def reload_index(self) -> None:
        """重新从磁盘加载项目索引，同步外部变更。"""
        self._index = self._load_index()
        # 如果当前打开的项目已被外部删除，清除引用
        if self._current_project and self._current_project.project_id not in self._index:
            logger.warning("当前项目 %s 已被外部删除，自动关闭", self._current_project.project_id)
            self._close_db()
            self._current_project = None

    # ── 公开 API ──────────────────────────────────────────────

    def create_project(self, name: str, description: str = "") -> str:
        """创建新项目，返回 project_id

        Args:
            name: 项目名称
            description: 项目描述

        Returns:
            新项目的 project_id

        Raises:
            ValueError: 项目名称为空
        """
        if not name or not name.strip():
            raise ValueError("项目名称不能为空")

        project_id = f"proj_{uuid.uuid4().hex[:12]}"
        project = ProjectInfo(
            project_id=project_id,
            name=name.strip(),
            description=description.strip(),
            created_at=time.time(),
            status="active",
            remote_base=f"~/.h2ometa/projects/{project_id}",
        )

        # 创建项目目录
        project_dir = self._projects_root / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # 初始化 SQLite 数据库
        db_path = project_dir / "project.db"
        self._init_database(db_path)
        self._save_project_metadata(project)

        # 写入索引
        self._index[project_id] = project.to_dict()
        self._save_index()
        self._save_project_metadata(ProjectInfo.from_dict(self._index[project_id]))

        logger.info("项目已创建: %s (%s)", name, project_id)
        self.project_created.emit(project_id)
        return project_id

    def open_project(self, project_id: str) -> ProjectInfo:
        """打开项目，连接 SQLite 数据库

        Args:
            project_id: 要打开的项目 ID

        Returns:
            打开的项目信息

        Raises:
            KeyError: 项目不存在
            FileNotFoundError: 项目数据库文件不存在
        """
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        project_data = self._index[project_id]
        project = ProjectInfo.from_dict(project_data)

        if project.status == "archived":
            raise ValueError(f"项目已归档，无法打开: {project_id}")

        db_path = self._projects_root / project_id / "project.db"
        if not db_path.exists():
            raise FileNotFoundError(f"项目数据库不存在: {db_path}")

        # 关闭旧连接
        self._close_db()

        # 建立新连接
        try:
            self._db_conn = sqlite3.connect(str(db_path))
            self._db_conn.execute("PRAGMA foreign_keys=ON")
            self._db_conn.row_factory = sqlite3.Row

            # 运行数据库迁移
            self._migrate_database(self._db_conn)
        except Exception:
            logger.exception("Failed to open project database: %s", db_path)
            self._close_db()
            raise

        self._current_project = project
        self._save_last_opened_project(project_id)

        logger.info("项目已打开: %s (%s)", project.name, project_id)
        self.project_opened.emit(project_id)
        return project

    def list_projects(self) -> list[ProjectInfo]:
        """列出所有项目

        Returns:
            项目信息列表，按创建时间倒序排列
        """
        projects = [ProjectInfo.from_dict(data) for data in self._index.values()]
        projects.sort(key=lambda p: p.created_at, reverse=True)
        return projects

    def archive_project(self, project_id: str) -> None:
        """归档项目

        Args:
            project_id: 要归档的项目 ID

        Raises:
            KeyError: 项目不存在
        """
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        self._index[project_id]["status"] = "archived"
        self._save_index()
        self._save_project_metadata(ProjectInfo.from_dict(self._index[project_id]))

        # 如果归档的是当前项目，关闭连接
        if self._current_project and self._current_project.project_id == project_id:
            self._close_db()
            self._current_project = None
        if self._load_last_opened_project() == project_id:
            self._clear_last_opened_project()

        logger.info("项目已归档: %s", project_id)
        self.project_archived.emit(project_id)

    def delete_project(self, project_id: str) -> None:
        """删除项目（包括文件和索引记录）

        Args:
            project_id: 要删除的项目 ID

        Raises:
            KeyError: 项目不存在
            RuntimeError: 无法删除当前打开的项目
        """
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        # 不能删除当前打开的项目
        if self._current_project and self._current_project.project_id == project_id:
            raise RuntimeError("无法删除当前打开的项目，请先关闭或切换到其他项目")

        # 删除项目目录
        project_dir = self._projects_root / project_id
        if project_dir.exists():
            import shutil
            shutil.rmtree(project_dir)
            logger.info("已删除项目目录: %s", project_dir)

        # 从索引中移除
        del self._index[project_id]
        self._save_index()
        if self._load_last_opened_project() == project_id:
            self._clear_last_opened_project()

        logger.info("项目已删除: %s", project_id)
        self.project_deleted.emit(project_id)

    @property
    def current_project(self) -> Optional[ProjectInfo]:
        """当前打开的项目"""
        return self._current_project

    @property
    def current_project_dir(self) -> Optional[Path]:
        """当前打开项目的本地目录。"""
        if self._current_project is None:
            return None
        return self._projects_root / self._current_project.project_id

    @property
    def db(self) -> sqlite3.Connection:
        """当前项目的数据库连接

        Raises:
            RuntimeError: 没有打开的项目
        """
        if self._db_conn is None:
            raise RuntimeError("没有打开的项目，请先调用 open_project()")
        return self._db_conn

    def get_project_dir(self, project_id: str) -> Path:
        """返回指定项目的本地目录。"""
        if not project_id:
            raise ValueError("project_id 不能为空")
        return self._projects_root / project_id

    def close(self) -> None:
        """关闭管理器，释放资源"""
        self._close_db()
        self._current_project = None

    def backup_current_project(self, reason: str = "manual") -> Path:
        """备份当前项目数据库和项目索引。"""
        if self._current_project is None:
            raise RuntimeError("没有打开的项目")

        project_id = self._current_project.project_id
        project_dir = self._projects_root / project_id
        db_path = project_dir / "project.db"
        if not db_path.exists():
            raise FileNotFoundError(f"项目数据库不存在: {db_path}")

        backups_root = self._projects_root / "_backups" / project_id
        try:
            backups_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            backups_root = project_dir / "_backups"
            backups_root.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_dir = backups_root / f"{timestamp}_{reason}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        backup_db = backup_dir / "project.db"
        if self._db_conn is not None:
            dest = sqlite3.connect(str(backup_db))
            try:
                self._db_conn.backup(dest)
            finally:
                dest.close()
        else:
            shutil.copy2(db_path, backup_db)

        for candidate in (project_dir / "project.db-wal", project_dir / "project.db-shm"):
            if candidate.exists():
                try:
                    shutil.copy2(candidate, backup_dir / candidate.name)
                except OSError:
                    logger.warning("Failed to copy SQLite sidecar during backup: %s", candidate)

        if self._index_path.exists():
            shutil.copy2(self._index_path, backup_dir / "projects.json")

        logger.info("已备份当前项目: %s -> %s", project_id, backup_dir)
        return backup_dir

    # ── 内部方法 ──────────────────────────────────────────────

    def _init_database(self, db_path: Path) -> None:
        """初始化项目数据库，创建所有表"""
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
            logger.debug("数据库已初始化: %s", db_path)
        finally:
            conn.close()

    def _migrate_database(self, conn: sqlite3.Connection) -> None:
        """迁移数据库 schema 到最新版本

        添加新字段：
        - executions.is_final_version: 标记为最终版本
        - executions.archived_at: 文件清理时间戳
        """
        cursor = conn.cursor()

        # 检查 is_final_version 字段是否存在
        cursor.execute("PRAGMA table_info(executions)")
        columns = [row[1] for row in cursor.fetchall()]

        if "is_final_version" not in columns:
            logger.info("迁移数据库：添加 is_final_version 字段")
            conn.execute(
                "ALTER TABLE executions ADD COLUMN is_final_version INTEGER DEFAULT 0"
            )

        if "archived_at" not in columns:
            logger.info("迁移数据库：添加 archived_at 字段")
            conn.execute(
                "ALTER TABLE executions ADD COLUMN archived_at REAL"
            )

        conn.commit()

    def _close_db(self) -> None:
        """安全关闭当前数据库连接"""
        if self._db_conn is not None:
            try:
                self._db_conn.close()
            except Exception:
                logger.exception("关闭数据库连接时出错")
            self._db_conn = None

    @staticmethod
    def _try_checkpoint_wal(db_path: Path) -> None:
        """尝试 checkpoint 残留 WAL 文件，防止 disk I/O error。"""
        shm = db_path.with_suffix(".db-shm")
        wal = db_path.with_suffix(".db-wal")
        if not shm.exists() and not wal.exists():
            return
        try:
            tmp = sqlite3.connect(str(db_path))
            tmp.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            tmp.close()
            logger.info("已 checkpoint 残留 WAL: %s", db_path)
        except Exception:
            logger.warning("WAL checkpoint 失败，尝试删除残留文件: %s", db_path)
            for f in (shm, wal):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_index(self) -> dict[str, dict]:
        """从 projects.json 加载项目索引"""
        if not self._index_path.exists():
            rebuilt = self._rebuild_index_from_projects({})
            if rebuilt:
                try:
                    self._index = rebuilt
                    self._save_index()
                except OSError:
                    logger.exception("重建缺失的项目索引后保存失败")
            return rebuilt
        try:
            text = self._index_path.read_text(encoding="utf-8")
            data = json.loads(text)
            if not isinstance(data, dict):
                logger.warning("项目索引格式异常，已重置")
                rebuilt = self._rebuild_index_from_projects({})
                if rebuilt:
                    try:
                        self._index = rebuilt
                        self._save_index()
                    except OSError:
                        logger.exception("重建异常格式的项目索引后保存失败")
                return rebuilt
            cleaned: dict[str, dict] = {}
            removed: list[str] = []
            for project_id, raw in data.items():
                if not isinstance(raw, dict):
                    removed.append(str(project_id))
                    continue
                db_path = self._projects_root / str(project_id) / "project.db"
                if not db_path.exists():
                    removed.append(str(project_id))
                    continue
                cleaned[str(project_id)] = raw

            rebuilt = self._rebuild_index_from_projects(cleaned)
            if removed or rebuilt != cleaned:
                logger.warning("项目索引中移除了 %d 个无效条目: %s", len(removed), ", ".join(removed))
                try:
                    self._index = rebuilt
                    self._save_index()
                except OSError:
                    logger.exception("清理无效项目索引条目后保存失败")
            return rebuilt
        except (json.JSONDecodeError, OSError) as e:
            logger.error("加载项目索引失败: %s", e)
            rebuilt = self._rebuild_index_from_projects({})
            if rebuilt:
                try:
                    self._index = rebuilt
                    self._save_index()
                except OSError:
                    logger.exception("重建损坏的项目索引后保存失败")
            return rebuilt

    def _rebuild_index_from_projects(self, index: dict[str, dict]) -> dict[str, dict]:
        """从现有项目目录重建索引，避免索引丢失后界面空白。"""
        rebuilt = dict(index)
        changed = False

        if self._projects_root.exists():
            for project_dir in self._projects_root.iterdir():
                if not project_dir.is_dir() or project_dir.name.startswith("_"):
                    continue
                db_path = project_dir / "project.db"
                if not db_path.exists():
                    continue
                project_id = project_dir.name
                if project_id in rebuilt:
                    continue
                rebuilt[project_id] = self._restore_project_record(project_id, db_path)
                changed = True

        if changed:
            logger.warning("项目索引缺失，已从磁盘恢复 %d 个项目", len(rebuilt) - len(index))
        return rebuilt

    def _restore_project_record(self, project_id: str, db_path: Path) -> dict:
        """优先从备份索引恢复项目元数据，失败时退化为最小可用记录。"""
        metadata_path = db_path.parent / "project.json"
        if metadata_path.exists():
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("读取项目元数据失败: %s", metadata_path, exc_info=True)
            else:
                if isinstance(payload, dict):
                    restored = dict(payload)
                    restored.setdefault("project_id", project_id)
                    restored.setdefault("description", "")
                    restored.setdefault("created_at", db_path.stat().st_mtime)
                    restored.setdefault("status", "active")
                    restored.setdefault("remote_base", f"~/.h2ometa/projects/{project_id}")
                    return restored

        backup_record = self._load_project_record_from_backups(project_id)
        if backup_record is not None:
            return backup_record

        created_at = db_path.stat().st_mtime
        return ProjectInfo(
            project_id=project_id,
            name=project_id,
            description="",
            created_at=created_at,
            status="active",
            remote_base=f"~/.h2ometa/projects/{project_id}",
        ).to_dict()

    def _load_project_record_from_backups(self, project_id: str) -> Optional[dict]:
        """读取最近一次备份里的 projects.json，恢复项目名等元数据。"""
        backup_roots = [
            self._projects_root / "_backups" / project_id,
            self._projects_root / project_id / "_backups",
        ]
        for backups_root in backup_roots:
            if not backups_root.exists():
                continue
            candidates = sorted(
                (path / "projects.json" for path in backups_root.iterdir() if path.is_dir()),
                reverse=True,
            )
            for candidate in candidates:
                if not candidate.exists():
                    continue
                try:
                    payload = json.loads(candidate.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    logger.warning("读取项目备份索引失败: %s", candidate, exc_info=True)
                    continue
                raw = payload.get(project_id)
                if isinstance(raw, dict):
                    restored = dict(raw)
                    restored.setdefault("project_id", project_id)
                    restored.setdefault("description", "")
                    restored.setdefault("created_at", candidate.stat().st_mtime)
                    restored.setdefault("status", "active")
                    restored.setdefault("remote_base", f"~/.h2ometa/projects/{project_id}")
                    return restored
        return None

    def _save_project_metadata(self, project: ProjectInfo) -> None:
        """为每个项目写入独立元数据，避免主索引丢失后项目名丢失。"""
        metadata_path = self._projects_root / project.project_id / "project.json"
        try:
            metadata_path.write_text(
                json.dumps(project.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("保存项目元数据失败: %s", metadata_path)

    def _save_index(self) -> None:
        """保存项目索引到 projects.json"""
        try:
            text = json.dumps(self._index, ensure_ascii=False, indent=2)
            self._index_path.write_text(text, encoding="utf-8")
        except OSError as e:
            logger.error("保存项目索引失败: %s", e)
            raise

    def _load_last_opened_project(self) -> str:
        if not self._last_project_path.exists():
            return ""
        try:
            return self._last_project_path.read_text(encoding="utf-8").strip()
        except OSError:
            logger.warning("读取上次打开项目记录失败: %s", self._last_project_path, exc_info=True)
            return ""

    def _save_last_opened_project(self, project_id: str) -> None:
        normalized = str(project_id or "").strip()
        if not normalized:
            return
        try:
            self._last_project_path.write_text(normalized, encoding="utf-8")
        except OSError:
            logger.warning("保存上次打开项目记录失败: %s", self._last_project_path, exc_info=True)

    def _clear_last_opened_project(self) -> None:
        try:
            if self._last_project_path.exists():
                self._last_project_path.unlink()
        except OSError:
            logger.warning("清理上次打开项目记录失败: %s", self._last_project_path, exc_info=True)

    def _restore_last_opened_project(self) -> None:
        restored = False
        last_project_id = self._load_last_opened_project()
        if last_project_id:
            project_raw = self._index.get(last_project_id)
            if not isinstance(project_raw, dict):
                self._clear_last_opened_project()
            elif str(project_raw.get("status", "active")) != "active":
                self._clear_last_opened_project()
            else:
                try:
                    self.open_project(last_project_id)
                    logger.info("?????????: %s", last_project_id)
                    restored = True
                except Exception:
                    logger.warning("??????????: %s", last_project_id, exc_info=True)

        if restored or self._current_project is not None:
            return

        fallback = self._select_most_recent_active_project_id()
        if not fallback:
            return
        try:
            self.open_project(fallback)
            logger.info("?????????????: %s", fallback)
        except Exception:
            logger.warning("????????: %s", fallback, exc_info=True)

    def _select_most_recent_active_project_id(self) -> str:
        active: list[tuple[str, float]] = []
        for project_id, payload in self._index.items():
            if not isinstance(payload, dict):
                continue
            if str(payload.get("status", "active")) != "active":
                continue
            created_at = payload.get("created_at", 0.0)
            try:
                ts = float(created_at)
            except (TypeError, ValueError):
                ts = 0.0
            active.append((str(project_id), ts))

        if not active:
            return ""
        active.sort(key=lambda item: item[1], reverse=True)
        return active[0][0]

