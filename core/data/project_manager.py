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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from core.qt_compat import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# 默认项目根目录
DEFAULT_PROJECTS_ROOT = Path.home() / ".h2ometa" / "projects"
DEFAULT_INDEX_PATH = Path.home() / ".h2ometa" / "projects.json"
DEFAULT_LAST_PROJECT_PATH = Path.home() / ".h2ometa" / "last_project.txt"
DEFAULT_LAST_PROJECT_PATH_APPDATA = (
    Path(os.getenv("APPDATA", "")).expanduser() / "H2OMeta" / "last_project.txt"
    if os.getenv("APPDATA")
    else None
)
DEFAULT_DB_CONNECT_TIMEOUT_SEC = 20.0
DEFAULT_DB_BUSY_TIMEOUT_MS = 20_000
DEFAULT_DB_JOURNAL_MODE = "delete"

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
    task_id TEXT REFERENCES tasks(task_id),
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

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('pending','queued','in_progress','completed','failed','cancelled')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_activity_at REAL NOT NULL,
    latest_execution_id TEXT REFERENCES executions(execution_id),
    summary TEXT NOT NULL DEFAULT '',
    result_snapshot TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS workflow_snapshots (
    workflow_snapshot_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    workflow_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '0.1.0',
    workflow_definition_json TEXT NOT NULL,
    params_schema_json TEXT NOT NULL DEFAULT '{}',
    workflow_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(task_id)
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    workflow_snapshot_id TEXT NOT NULL REFERENCES workflow_snapshots(workflow_snapshot_id),
    execution_id TEXT NOT NULL UNIQUE REFERENCES executions(execution_id),
    workflow_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','cancelled')),
    snapshot_hash TEXT NOT NULL,
    snapshot_payload_json TEXT NOT NULL,
    bundle_id TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    result_path TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    error_text TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS workflow_results (
    workflow_result_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(run_id),
    result_kind TEXT NOT NULL DEFAULT 'artifacts',
    summary_json TEXT NOT NULL DEFAULT '{}',
    result_path TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(workflow_run_id, result_kind)
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
    last_opened_at: float = 0.0  # 最后打开时间戳

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
            last_opened_at=data.get("last_opened_at", 0.0),
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
        self._last_project_paths = [self._last_project_path]
        if (
            DEFAULT_LAST_PROJECT_PATH_APPDATA is not None
            and DEFAULT_LAST_PROJECT_PATH_APPDATA not in self._last_project_paths
        ):
            self._last_project_paths.append(DEFAULT_LAST_PROJECT_PATH_APPDATA)
        self._current_project: Optional[ProjectInfo] = None
        self._db_conn: Optional[sqlite3.Connection] = None
        self._db_read_only: bool = False

        # 确保根目录存在
        self._projects_root.mkdir(parents=True, exist_ok=True)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        for path in self._last_project_paths:
            path.parent.mkdir(parents=True, exist_ok=True)

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
        self._current_project = project

        # 建立新连接
        try:
            runtime = self._resolve_db_runtime_options()
            aggressive_checkpoint = runtime["journal_mode"] == "delete"
            self._try_checkpoint_wal(db_path, aggressive_cleanup=aggressive_checkpoint)
            self._db_conn = self._open_project_db(db_path)
            self._db_read_only = False
        except sqlite3.OperationalError as exc:
            # Auto-heal for transient/stale sqlite sidecar files.
            if self._is_sqlite_disk_io_error(exc):
                logger.warning(
                    "Open project DB hit disk I/O error, retrying after sidecar cleanup: %s",
                    db_path,
                )
                self._close_db()
                self._cleanup_sqlite_sidecars(db_path)
                try:
                    self._db_conn = self._open_project_db(db_path)
                    self._db_read_only = False
                except sqlite3.OperationalError as exc_retry:
                    if self._is_sqlite_disk_io_error(exc_retry):
                        logger.warning(
                            "Retry still hit disk I/O error, attempting backup restore: %s",
                            db_path,
                        )
                        self._close_db()
                        if self._restore_project_db_from_latest_backup(project_id, db_path):
                            self._cleanup_sqlite_sidecars(db_path)
                            try:
                                self._db_conn = self._open_project_db(db_path)
                                self._db_read_only = False
                            except Exception:
                                logger.exception("Failed to open restored project database: %s", db_path)
                                self._close_db()
                                # Final fallback: open project in readonly immutable mode.
                                self._db_conn = self._open_project_db_readonly(db_path)
                                self._db_read_only = True
                        else:
                            logger.exception("Failed to open project database: %s", db_path)
                            self._close_db()
                            # Final fallback: open project in readonly immutable mode.
                            self._db_conn = self._open_project_db_readonly(db_path)
                            self._db_read_only = True
                    else:
                        logger.exception("Failed to open project database: %s", db_path)
                        self._close_db()
                        raise
                except Exception:
                    logger.exception("Failed to open project database: %s", db_path)
                    self._close_db()
                    raise
            else:
                logger.exception("Failed to open project database: %s", db_path)
                self._close_db()
                raise
        except Exception:
            logger.exception("Failed to open project database: %s", db_path)
            self._close_db()
            self._current_project = None
            raise

        self._current_project = project
        self._index[project_id]["last_opened_at"] = time.time()
        try:
            self._save_index()
        except OSError:
            # 打开项目的主路径是“可读 DB + 建立连接”；
            # 索引落盘失败不应阻断项目打开（常见于权限/只读目录）。
            logger.warning("保存项目索引失败，但项目已打开: %s", project_id, exc_info=True)
        try:
            self._save_last_opened_project(project_id)
        except OSError:
            logger.warning("写入 last_project 失败，但项目已打开: %s", project_id, exc_info=True)

        if self._db_read_only:
            logger.warning("项目以只读模式打开: %s (%s)", project.name, project_id)
        else:
            logger.info("项目已打开: %s (%s)", project.name, project_id)
        self.project_opened.emit(project_id)
        return project

    def _open_project_db(self, db_path: Path) -> sqlite3.Connection:
        runtime = self._resolve_db_runtime_options()
        conn = sqlite3.connect(
            str(db_path),
            timeout=runtime["connect_timeout_sec"],
        )
        try:
            self._apply_sqlite_runtime(conn, runtime)
            conn.row_factory = sqlite3.Row
            self._migrate_database(conn)
        except Exception:
            conn.close()
            raise
        return conn

    def _open_project_db_readonly(self, db_path: Path) -> sqlite3.Connection:
        # immutable=1 avoids locking side effects when wal/shm are held by another process.
        uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
        runtime = self._resolve_db_runtime_options()
        conn = sqlite3.connect(
            uri,
            uri=True,
            timeout=runtime["connect_timeout_sec"],
        )
        conn.execute(f"PRAGMA busy_timeout={runtime['busy_timeout_ms']}")
        conn.row_factory = sqlite3.Row
        return conn

    def _cleanup_sqlite_sidecars(self, db_path: Path) -> None:
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{db_path}{suffix}")
            try:
                if sidecar.exists():
                    sidecar.unlink()
            except PermissionError:
                logger.warning("SQLite sidecar is in use and cannot be removed now: %s", sidecar)
            except OSError:
                logger.warning("Failed to cleanup sqlite sidecar: %s", sidecar, exc_info=True)

    def _find_latest_backup_db(self, project_id: str) -> Optional[Path]:
        backup_roots = [
            self._projects_root / "_backups" / project_id,
            self._projects_root / project_id / "_backups",
        ]
        candidates: list[tuple[float, Path]] = []
        for root in backup_roots:
            if not root.exists():
                continue
            try:
                for d in root.iterdir():
                    if not d.is_dir():
                        continue
                    db = d / "project.db"
                    if not db.exists():
                        continue
                    try:
                        ts = float(d.stat().st_mtime)
                    except OSError:
                        ts = 0.0
                    candidates.append((ts, db))
            except OSError:
                logger.warning("Failed to scan backup root: %s", root, exc_info=True)
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _restore_project_db_from_latest_backup(self, project_id: str, db_path: Path) -> bool:
        backup_db = self._find_latest_backup_db(project_id)
        if backup_db is None:
            logger.warning("No backup DB found for project restore: %s", project_id)
            return False
        try:
            if db_path.exists():
                ts = time.strftime("%Y%m%d_%H%M%S")
                broken_copy = db_path.with_name(f"project.db.ioerror.{ts}.bak")
                shutil.copy2(db_path, broken_copy)
                logger.warning("Current project DB copied before restore: %s", broken_copy)
            shutil.copy2(backup_db, db_path)
            logger.info("Project DB restored from backup: %s -> %s", backup_db, db_path)
            return True
        except OSError:
            logger.exception("Failed restoring project DB from backup: %s", backup_db)
            return False

    def list_projects(self, sort_by: str = "created_at") -> list[ProjectInfo]:
        """列出所有项目

        Args:
            sort_by: 排序方式，"created_at" 或 "last_opened"

        Returns:
            项目信息列表，按指定方式倒序排列
        """
        projects = [ProjectInfo.from_dict(data) for data in self._index.values()]
        if sort_by == "last_opened":
            projects.sort(key=lambda p: p.last_opened_at, reverse=True)
        else:
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

    def restore_project(self, project_id: str) -> ProjectInfo:
        """将归档项目恢复为活跃项目。"""
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        project_data = dict(self._index[project_id])
        project_data["status"] = "active"
        self._index[project_id] = project_data
        self._save_index()

        project = ProjectInfo.from_dict(project_data)
        self._save_project_metadata(project)
        if self._current_project and self._current_project.project_id == project_id:
            self._current_project = project

        logger.info("项目已恢复: %s", project_id)
        return project

    def update_project(self, project_id: str, *, name: str | None = None, description: str | None = None) -> ProjectInfo:
        """更新项目名称或描述。"""
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        project_data = dict(self._index[project_id])
        next_name = project_data.get("name", "")
        next_description = project_data.get("description", "")

        if name is not None:
            normalized_name = str(name).strip()
            if not normalized_name:
                raise ValueError("项目名称不能为空")
            next_name = normalized_name

        if description is not None:
            next_description = str(description).strip()

        project_data["name"] = next_name
        project_data["description"] = next_description
        self._index[project_id] = project_data
        self._save_index()

        project = ProjectInfo.from_dict(project_data)
        self._save_project_metadata(project)
        if self._current_project and self._current_project.project_id == project_id:
            self._current_project = project

        logger.info("项目已更新: %s (%s)", next_name, project_id)
        return project

    def delete_project(self, project_id: str) -> None:
        """删除项目（包括文件和索引记录）

        Args:
            project_id: 要删除的项目 ID

        Raises:
            KeyError: 项目不存在
        """
        if project_id not in self._index:
            raise KeyError(f"项目不存在: {project_id}")

        if self._current_project and self._current_project.project_id == project_id:
            self._close_db()
            self._current_project = None

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

    @property
    def db_read_only(self) -> bool:
        return bool(self._db_read_only)

    def get_project_dir(self, project_id: str) -> Path:
        """返回指定项目的本地目录。"""
        if not project_id:
            raise ValueError("project_id 不能为空")
        return self._projects_root / project_id

    def close(self) -> None:
        """关闭管理器，释放资源"""
        if self._current_project is not None:
            self._save_last_opened_project(self._current_project.project_id)
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

    def _resolve_db_runtime_options(self) -> dict[str, float | int | str]:
        runtime_cfg: dict[str, object] = {}
        try:
            from config import get_config

            cfg = get_config()
            runtime = cfg.get("runtime", {}) if isinstance(cfg, dict) else {}
            if isinstance(runtime, dict):
                runtime_cfg = runtime
        except Exception:
            logger.debug("加载数据库运行时配置失败，使用默认值", exc_info=True)

        connect_timeout = self._safe_float(
            runtime_cfg.get("db_connect_timeout_sec"),
            DEFAULT_DB_CONNECT_TIMEOUT_SEC,
            min_value=1.0,
            max_value=120.0,
        )
        busy_timeout = self._safe_int(
            runtime_cfg.get("db_busy_timeout_ms"),
            DEFAULT_DB_BUSY_TIMEOUT_MS,
            min_value=1000,
            max_value=120000,
        )
        journal_mode = self._normalize_journal_mode(
            runtime_cfg.get("db_journal_mode"),
            DEFAULT_DB_JOURNAL_MODE,
        )
        return {
            "connect_timeout_sec": connect_timeout,
            "busy_timeout_ms": busy_timeout,
            "journal_mode": journal_mode,
        }

    @staticmethod
    def _safe_float(value: object, default: float, *, min_value: float, max_value: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, parsed))

    @staticmethod
    def _safe_int(value: object, default: int, *, min_value: int, max_value: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(min_value, min(max_value, parsed))

    @staticmethod
    def _normalize_journal_mode(value: object, default: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"delete", "wal", "auto"}:
            return default
        return normalized

    def _apply_sqlite_runtime(self, conn: sqlite3.Connection, runtime: dict[str, float | int | str]) -> None:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={int(runtime['busy_timeout_ms'])}")
        self._apply_journal_mode(conn, str(runtime["journal_mode"]))

    @staticmethod
    def _apply_journal_mode(conn: sqlite3.Connection, mode: str) -> None:
        normalized = str(mode or "delete").lower()
        if normalized == "wal":
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            return
        if normalized == "auto":
            row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            result = str(row[0]).lower() if row else ""
            if result != "wal":
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("PRAGMA synchronous=FULL")
            else:
                conn.execute("PRAGMA synchronous=NORMAL")
            return
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")

    def _init_database(self, db_path: Path) -> None:
        """初始化项目数据库，创建所有表"""
        runtime = self._resolve_db_runtime_options()
        conn = sqlite3.connect(
            str(db_path),
            timeout=runtime["connect_timeout_sec"],
        )
        try:
            self._apply_sqlite_runtime(conn, runtime)
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
        - executions.task_id: 任务归属
        - tasks: 长时程任务表
        """
        cursor = conn.cursor()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('pending','queued','in_progress','completed','failed','cancelled')),
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_activity_at REAL NOT NULL,
                latest_execution_id TEXT REFERENCES executions(execution_id),
                summary TEXT NOT NULL DEFAULT '',
                result_snapshot TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_snapshots (
                workflow_snapshot_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                workflow_id TEXT NOT NULL,
                name TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '0.1.0',
                workflow_definition_json TEXT NOT NULL,
                params_schema_json TEXT NOT NULL DEFAULT '{}',
                workflow_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(task_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                workflow_snapshot_id TEXT NOT NULL REFERENCES workflow_snapshots(workflow_snapshot_id),
                execution_id TEXT NOT NULL UNIQUE REFERENCES executions(execution_id),
                workflow_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','cancelled')),
                snapshot_hash TEXT NOT NULL,
                snapshot_payload_json TEXT NOT NULL,
                bundle_id TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                result_path TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                error_text TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_results (
                workflow_result_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(run_id),
                result_kind TEXT NOT NULL DEFAULT 'artifacts',
                summary_json TEXT NOT NULL DEFAULT '{}',
                result_path TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(workflow_run_id, result_kind)
            )
            """
        )

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

        if "task_id" not in columns:
            logger.info("迁移数据库：添加 task_id 字段")
            conn.execute(
                "ALTER TABLE executions ADD COLUMN task_id TEXT REFERENCES tasks(task_id)"
            )

        self._migrate_orphan_executions_into_legacy_task(conn)

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_exec_active_created
            ON executions(created_at)
            WHERE archived_at IS NULL
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_exec_task_created
            ON executions(task_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_exec_sample_tool_created
            ON executions(sample_id, tool_id, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_exec_status_tool_completed
            ON executions(status, tool_id, completed_at, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_data_sample_type_tier_created
            ON data_items(sample_id, data_type, tier, created_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_eio_exec_dir
            ON execution_io(execution_id, direction)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_project_activity
            ON tasks(project_id, last_activity_at DESC, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_snapshots_task
            ON workflow_snapshots(task_id, updated_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_project_created
            ON workflow_runs(project_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_task_created
            ON workflow_runs(task_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_execution
            ON workflow_runs(execution_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_results_run_created
            ON workflow_results(workflow_run_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_results_task_created
            ON workflow_results(task_id, created_at DESC)
            """
        )

        conn.commit()

    def _migrate_orphan_executions_into_legacy_task(self, conn: sqlite3.Connection) -> None:
        current_project = self._current_project
        if current_project is None:
            return

        orphan_row = conn.execute(
            "SELECT COUNT(*) FROM executions WHERE task_id IS NULL"
        ).fetchone()
        orphan_count = int(orphan_row[0]) if orphan_row else 0
        if orphan_count <= 0:
            return

        legacy_task_row = conn.execute(
            """
            SELECT task_id
            FROM tasks
            WHERE project_id = ? AND title = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (current_project.project_id, "Imported history"),
        ).fetchone()
        if legacy_task_row is not None:
            legacy_task_id = str(legacy_task_row[0])
        else:
            now = time.time()
            legacy_task_id = f"task_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, project_id, title, description, status,
                    created_at, updated_at, last_activity_at,
                    latest_execution_id, summary, result_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    legacy_task_id,
                    current_project.project_id,
                    "Imported history",
                    "Auto-created during task migration for executions that predate the task model.",
                    "completed",
                    now,
                    now,
                    now,
                    None,
                    "Legacy executions imported during workspace migration.",
                    "{}",
                ),
            )

        conn.execute(
            "UPDATE executions SET task_id = ? WHERE task_id IS NULL",
            (legacy_task_id,),
        )

        latest_execution_row = conn.execute(
            """
            SELECT execution_id, created_at, status, error
            FROM executions
            WHERE task_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (legacy_task_id,),
        ).fetchone()
        if latest_execution_row is None:
            return

        latest_created_at = float(latest_execution_row["created_at"] or time.time())
        latest_status = str(latest_execution_row["status"] or "completed")
        mapped_status = {
            "pending": "queued",
            "running": "in_progress",
            "retrying": "in_progress",
            "completed": "completed",
            "failed": "failed",
        }.get(latest_status, "completed")
        conn.execute(
            """
            UPDATE tasks
            SET latest_execution_id = ?, updated_at = ?, last_activity_at = ?, status = ?, summary = ?
            WHERE task_id = ?
            """,
            (
                str(latest_execution_row["execution_id"]),
                latest_created_at,
                latest_created_at,
                mapped_status,
                "Imported legacy executions",
                legacy_task_id,
            ),
        )

    def _close_db(self) -> None:
        """安全关闭当前数据库连接"""
        if self._db_conn is not None:
            try:
                self._db_conn.close()
            except Exception:
                logger.exception("关闭数据库连接时出错")
            self._db_conn = None
        self._db_read_only = False

    @staticmethod
    def _try_checkpoint_wal(db_path: Path, *, aggressive_cleanup: bool = True) -> None:
        """尝试 checkpoint 残留 WAL 文件，防止 disk I/O error。"""
        shm = db_path.with_suffix(".db-shm")
        wal = db_path.with_suffix(".db-wal")
        if not shm.exists() and not wal.exists():
            return
        tmp = None
        try:
            tmp = sqlite3.connect(str(db_path))
            tmp.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("已 checkpoint 残留 WAL: %s", db_path)
        except Exception:
            logger.warning("WAL checkpoint 失败，尝试删除残留文件: %s", db_path)
        finally:
            if tmp is not None:
                try:
                    tmp.close()
                except Exception:
                    pass
        # Delete sidecars AFTER connection is closed (DELETE mode compatibility).
        if aggressive_cleanup and (shm.exists() or wal.exists()):
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
        candidates = self._load_last_opened_project_candidates()
        if candidates:
            return candidates[0][0]
        return ''

    def _load_last_opened_project_candidates(self) -> list[tuple[str, Path, float]]:
        """Load all non-empty last_project markers, newest first.

        Returns tuples of (project_id, marker_path, mtime).
        """
        candidates: list[tuple[str, Path, float]] = []
        for path in self._last_project_paths:
            try:
                if not path.exists():
                    continue
                value = path.read_text(encoding='utf-8').strip()
                if not value:
                    continue
                try:
                    mtime = float(path.stat().st_mtime)
                except OSError:
                    mtime = 0.0
                candidates.append((value, path, mtime))
            except OSError:
                logger.warning("Failed to read last_project marker: %s", path, exc_info=True)
        candidates.sort(key=lambda item: item[2], reverse=True)
        return candidates

    def _save_last_opened_project(self, project_id: str) -> None:
        normalized = str(project_id or '').strip()
        if not normalized:
            return
        for path in self._last_project_paths:
            try:
                path.write_text(normalized, encoding='utf-8')
            except OSError:
                logger.warning("Failed to write last_project marker: %s", path, exc_info=True)

    def _clear_last_opened_project(self) -> None:
        for path in self._last_project_paths:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                logger.warning("Failed to clear last_project marker: %s", path, exc_info=True)

    def _clear_last_opened_project_path(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning("Failed to clear last_project marker: %s", path, exc_info=True)

    @staticmethod
    def _is_sqlite_disk_io_error(exc: Exception) -> bool:
        try:
            return isinstance(exc, sqlite3.OperationalError) and "disk i/o error" in str(exc).lower()
        except Exception:
            return False

    def _restore_last_opened_project(self) -> None:
        restored = False
        candidates = self._load_last_opened_project_candidates()
        logger.info(
            "Last project marker loaded: %s",
            candidates[0][0] if candidates else "<empty>",
        )
        tried_project_ids: set[str] = set()
        for project_id, marker_path, _mtime in candidates:
            normalized_id = str(project_id or "").strip()
            if not normalized_id or normalized_id in tried_project_ids:
                continue
            tried_project_ids.add(normalized_id)
            project_raw = self._index.get(project_id)
            if not isinstance(project_raw, dict):
                self._clear_last_opened_project_path(marker_path)
                continue
            if str(project_raw.get("status", "active")) != "active":
                self._clear_last_opened_project_path(marker_path)
                continue
            try:
                self.open_project(project_id)
                logger.info("Restored last opened project: %s", project_id)
                restored = True
                break
            except Exception as exc:
                logger.warning("Failed to restore last opened project: %s", project_id, exc_info=True)
                # Disk I/O error usually means transient storage/locking issue.
                # Keep marker and do not fallback to another project, otherwise
                # user may observe "closed on A but reopened on B".
                if self._is_sqlite_disk_io_error(exc):
                    return
                # For non-I/O errors, clear broken marker and try older markers.
                self._clear_last_opened_project_path(marker_path)
                continue

        if restored or self._current_project is not None:
            return

        fallback = self._select_most_recent_active_project_id()
        if not fallback:
            return
        try:
            self.open_project(fallback)
            logger.info("Opened fallback most-recent active project: %s", fallback)
        except Exception:
            logger.warning("Failed to open fallback project: %s", fallback, exc_info=True)

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
