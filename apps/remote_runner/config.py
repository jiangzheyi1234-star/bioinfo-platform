from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_REMOTE_ROOT = Path.home() / ".h2ometa" / "runner"
DEFAULT_CONFIG_PATH = DEFAULT_REMOTE_ROOT / "shared" / "config" / "runner.json"
DEFAULT_DATA_ROOT = DEFAULT_REMOTE_ROOT / "shared"
DEFAULT_DB_PATH = DEFAULT_DATA_ROOT / "data" / "runner.db"
DEFAULT_RUNTIME_STATE_PATH = DEFAULT_DATA_ROOT / "runtime" / "runner-state.json"


@dataclass
class RemoteRunnerConfig:
    service_name: str = "h2ometa-remote"
    version: str = "0.1.1-control-plane"
    mode: str = "background_process"
    bind_host: str = "127.0.0.1"
    bind_port: int = 0
    token: str = ""
    data_root: str = str(DEFAULT_DATA_ROOT)
    db_path: str = str(DEFAULT_DB_PATH)
    runtime_state_path: str = str(DEFAULT_RUNTIME_STATE_PATH)
    uploads_dir: str = str(DEFAULT_DATA_ROOT / "uploads")
    results_dir: str = str(DEFAULT_DATA_ROOT / "results")
    work_dir: str = str(DEFAULT_DATA_ROOT / "work")
    logs_dir: str = str(DEFAULT_DATA_ROOT / "logs")
    release_dir: str = ""
    runner_python: str = ""
    managed_conda_command: str = ""
    managed_conda_root_prefix: str = ""
    workflow_runtime_provider: str = ""
    workflow_runtime_source: str = ""
    workflow_runtime_version: str = ""
    snakemake_command: str = ""
    snakemake_version: str = ""


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


def get_runtime_state_path(cfg: RemoteRunnerConfig) -> Path:
    return Path(cfg.runtime_state_path)


def write_runtime_state(
    cfg: RemoteRunnerConfig,
    *,
    bind_host: str,
    bind_port: int,
    pid: int | None = None,
) -> dict[str, Any]:
    state = {
        "service": cfg.service_name,
        "version": cfg.version,
        "pid": int(pid or os.getpid()),
        "bindHost": bind_host,
        "bindPort": int(bind_port),
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = get_runtime_state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    try:
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        directory_fd = None
    if directory_fd is not None:
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return state


def ensure_runtime_layout(cfg: RemoteRunnerConfig) -> dict[str, bool]:
    data_root = Path(cfg.data_root)
    db_path = Path(cfg.db_path)
    uploads_dir = Path(cfg.uploads_dir)
    results_dir = Path(cfg.results_dir)
    work_dir = Path(cfg.work_dir)
    logs_dir = Path(cfg.logs_dir)
    runtime_state_path = get_runtime_state_path(cfg)

    for directory in (data_root, db_path.parent, runtime_state_path.parent, uploads_dir, results_dir, work_dir, logs_dir):
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
    runtime_state_path = get_runtime_state_path(cfg)
    return {
        "config": bool(cfg.token),
        "sqlite": db_path.exists(),
        "directories": all(path.exists() for path in (runtime_state_path.parent, uploads_dir, results_dir, work_dir, logs_dir)),
    }


def build_workflow_runtime_environment(cfg: RemoteRunnerConfig) -> dict[str, str]:
    env = dict(os.environ)
    path_entries: list[str] = []
    snakemake_command = str(cfg.snakemake_command or "").strip()
    if snakemake_command:
        path_entries.append(str(Path(snakemake_command).parent))
    managed_conda_command = str(cfg.managed_conda_command or "").strip()
    if managed_conda_command:
        path_entries.append(str(Path(managed_conda_command).parent))
        env["CONDA_EXE"] = managed_conda_command
        env["H2OMETA_MANAGED_CONDA_COMMAND"] = managed_conda_command
    current_path = env.get("PATH", "")
    seen: set[str] = set()
    merged_path = []
    for entry in [*path_entries, *current_path.split(os.pathsep)]:
        if entry and entry not in seen:
            seen.add(entry)
            merged_path.append(entry)
    env["PATH"] = os.pathsep.join(merged_path)
    managed_conda_root_prefix = str(cfg.managed_conda_root_prefix or "").strip()
    if managed_conda_root_prefix:
        env["MAMBA_ROOT_PREFIX"] = managed_conda_root_prefix
    return env


def inspect_workflow_runtime(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    snakemake_command = str(cfg.snakemake_command or "").strip()
    managed_conda_command = str(cfg.managed_conda_command or "").strip()
    if not snakemake_command:
        return {"ok": False, "message": "Snakemake command is not configured.", "snakemakeVersion": ""}
    if not managed_conda_command:
        return {"ok": False, "message": "Conda command is not configured for Snakemake --use-conda.", "snakemakeVersion": ""}
    conda_path = Path(managed_conda_command)
    if not conda_path.exists():
        return {"ok": False, "message": f"Conda command does not exist: {managed_conda_command}", "snakemakeVersion": ""}
    if not os.access(conda_path, os.X_OK):
        return {"ok": False, "message": f"Conda command is not executable: {managed_conda_command}", "snakemakeVersion": ""}
    path = Path(snakemake_command)
    if not path.exists():
        return {"ok": False, "message": f"Snakemake command does not exist: {snakemake_command}", "snakemakeVersion": ""}
    if not os.access(path, os.X_OK):
        return {"ok": False, "message": f"Snakemake command is not executable: {snakemake_command}", "snakemakeVersion": ""}
    try:
        result = subprocess.run(
            [snakemake_command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            env=build_workflow_runtime_environment(cfg),
        )
    except Exception as exc:
        return {"ok": False, "message": f"Snakemake version check failed: {exc}", "snakemakeVersion": ""}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return {"ok": False, "message": detail or "Snakemake version check failed.", "snakemakeVersion": ""}
    version = (result.stdout or result.stderr or "").strip().splitlines()[0] if (result.stdout or result.stderr).strip() else ""
    return {"ok": True, "message": "Workflow runtime is ready.", "snakemakeVersion": version}


def dump_public_config(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    data = asdict(cfg)
    data.pop("token", None)
    return data
