from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_REMOTE_ROOT = Path.home() / ".h2ometa" / "runner"
DEFAULT_CONFIG_PATH = DEFAULT_REMOTE_ROOT / "shared" / "config" / "runner.json"
DEFAULT_DATA_ROOT = DEFAULT_REMOTE_ROOT / "shared"
DEFAULT_DB_PATH = DEFAULT_DATA_ROOT / "data" / "runner.db"


@dataclass
class RemoteRunnerConfig:
    service_name: str = "h2ometa-remote"
    version: str = "0.1.0-control-plane"
    mode: str = "background_process"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8876
    token: str = ""
    data_root: str = str(DEFAULT_DATA_ROOT)
    db_path: str = str(DEFAULT_DB_PATH)
    uploads_dir: str = str(DEFAULT_DATA_ROOT / "uploads")
    results_dir: str = str(DEFAULT_DATA_ROOT / "results")
    work_dir: str = str(DEFAULT_DATA_ROOT / "work")
    logs_dir: str = str(DEFAULT_DATA_ROOT / "logs")
    release_dir: str = ""
    managed_conda_command: str = ""
    managed_conda_root_prefix: str = ""


def get_config_path() -> Path:
    raw = str(os.environ.get("H2OMETA_REMOTE_CONFIG", "") or "").strip()
    return Path(raw) if raw else DEFAULT_CONFIG_PATH


def load_remote_runner_config() -> RemoteRunnerConfig:
    path = get_config_path()
    raw: dict[str, Any] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    cfg = RemoteRunnerConfig(**{key: value for key, value in raw.items() if key in RemoteRunnerConfig.__dataclass_fields__})
    return cfg


def ensure_runtime_layout(cfg: RemoteRunnerConfig) -> dict[str, bool]:
    data_root = Path(cfg.data_root)
    db_path = Path(cfg.db_path)
    uploads_dir = Path(cfg.uploads_dir)
    results_dir = Path(cfg.results_dir)
    work_dir = Path(cfg.work_dir)
    logs_dir = Path(cfg.logs_dir)

    for directory in (data_root, db_path.parent, uploads_dir, results_dir, work_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS service_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.commit()

    return {
        "config": bool(cfg.token),
        "sqlite": db_path.exists(),
        "directories": all(path.exists() for path in (uploads_dir, results_dir, work_dir, logs_dir)),
    }


def inspect_runtime_layout(cfg: RemoteRunnerConfig) -> dict[str, bool]:
    db_path = Path(cfg.db_path)
    uploads_dir = Path(cfg.uploads_dir)
    results_dir = Path(cfg.results_dir)
    work_dir = Path(cfg.work_dir)
    logs_dir = Path(cfg.logs_dir)
    return {
        "config": bool(cfg.token),
        "sqlite": db_path.exists(),
        "directories": all(path.exists() for path in (uploads_dir, results_dir, work_dir, logs_dir)),
    }


def dump_public_config(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    data = asdict(cfg)
    data.pop("token", None)
    return data
