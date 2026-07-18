from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.contracts.runner_protocol import RUNNER_PROTOCOL_VERSION
from core.contracts.runner_protocol_runtime import (
    CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
    build_runner_protocol_runtime_self_attestation,
    require_current_runner_protocol_expectation,
)
from core.env_bool import parse_strict_env_bool

from .api_token_config import apply_api_token_env_overrides, normalize_api_token_roles
from .config_snapshot import (
    bind_remote_runner_config_snapshot,
    bind_remote_runner_startup_binding,
    get_process_bound_remote_runner_config,
    require_explicit_loaded_runner_protocol,
)
from .database_backend_config import apply_database_backend_env_overrides, assert_supported_database_backend
from .runtime_state import get_runtime_state_path, write_runtime_state
from .worker_resource_config import apply_run_worker_env_overrides
from .sqlite_migrations import initialize_or_migrate_runtime_db
from .workflow_runtime_config import (
    DEFAULT_CONDA_PREFIX_DIRNAME,
    DEFAULT_SNAKEMAKE_WRAPPER_PREFIX,
    DEFAULT_WORKFLOW_PROFILE_NAME,
    build_workflow_profile_content,
    build_workflow_runtime_environment,
    get_workflow_profile_dir,
    get_workflow_profile_name,
    get_workflow_profile_path,
    inspect_workflow_profile,
    inspect_workflow_runtime,
    resolve_default_conda_prefix,
    resolve_default_workflow_profile_dir,
    resolve_default_wrapper_prefix,
)

__all__ = [
    "DEFAULT_CONDA_PREFIX_DIRNAME",
    "DEFAULT_SNAKEMAKE_WRAPPER_PREFIX",
    "DEFAULT_WORKFLOW_PROFILE_NAME",
    "bind_remote_runner_config_snapshot",
    "bind_remote_runner_startup_binding",
    "build_workflow_runtime_environment",
    "get_runtime_state_path",
    "get_workflow_profile_path",
    "inspect_workflow_profile",
    "inspect_workflow_runtime",
    "require_explicit_loaded_runner_protocol",
    "write_runtime_state",
]

DEFAULT_REMOTE_ROOT_RELATIVE = Path(".h2ometa") / "runner"
DEFAULT_REMOTE_ROOT = Path.home() / DEFAULT_REMOTE_ROOT_RELATIVE
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
    api_token_actor: str = "remote-runner-api"
    api_token_roles: tuple[str, ...] = ()
    database_backend: str = "sqlite"
    database_url: str = ""
    runner_protocol_version: str = RUNNER_PROTOCOL_VERSION
    runner_protocol_fingerprint: str = CURRENT_RUNNER_PROTOCOL_FINGERPRINT
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
    workflow_profile_dir: str = ""
    workflow_profile_name: str = ""
    run_worker_slot_count: int = 1
    run_worker_total_cpu: int = 1
    run_worker_total_memory_mb: int = 0
    run_worker_total_disk_mb: int = 0
    run_worker_total_gpu: int = 0
    run_worker_attempt_cpu: int = 1
    run_worker_attempt_memory_mb: int = 0
    run_worker_attempt_disk_mb: int = 0
    run_worker_attempt_gpu: int = 0
    artifact_storage_backend: str = "local"
    artifact_s3_endpoint: str = ""
    artifact_s3_bucket: str = ""
    artifact_s3_region: str = ""
    artifact_s3_access_key: str = ""
    artifact_s3_secret_key: str = ""
    artifact_s3_secure: bool = True
    artifact_s3_prefix: str = "h2ometa"


def get_config_path() -> Path:
    raw = str(os.environ.get("H2OMETA_REMOTE_CONFIG", "") or "").strip()
    return Path(raw) if raw else DEFAULT_CONFIG_PATH


def load_remote_runner_config() -> RemoteRunnerConfig:
    bound = get_process_bound_remote_runner_config()
    if bound is not None:
        return bound
    path = get_config_path()
    raw: dict[str, Any] = {}
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    return remote_runner_config_from_payload(raw)


def remote_runner_config_from_payload(
    payload: Mapping[str, Any],
) -> RemoteRunnerConfig:
    """Build config from one already-read snapshot without reopening the file."""

    raw = dict(payload)
    cfg = RemoteRunnerConfig(**{key: value for key, value in raw.items() if key in RemoteRunnerConfig.__dataclass_fields__})
    cfg._runner_protocol_expectation_explicit = all(
        key in raw
        for key in ("runner_protocol_version", "runner_protocol_fingerprint")
    )
    cfg.api_token_actor = str(cfg.api_token_actor or "remote-runner-api").strip() or "remote-runner-api"
    cfg.api_token_roles = normalize_api_token_roles(cfg.api_token_roles)
    apply_run_worker_env_overrides(cfg)
    apply_artifact_storage_env_overrides(cfg)
    apply_api_token_env_overrides(cfg)
    apply_database_backend_env_overrides(cfg)
    return cfg


def apply_artifact_storage_env_overrides(cfg: RemoteRunnerConfig) -> None:
    overrides = {
        "artifact_storage_backend": os.environ.get("H2OMETA_ARTIFACT_STORAGE_BACKEND"),
        "artifact_s3_endpoint": os.environ.get("H2OMETA_ARTIFACT_S3_ENDPOINT"),
        "artifact_s3_bucket": os.environ.get("H2OMETA_ARTIFACT_S3_BUCKET"),
        "artifact_s3_region": os.environ.get("H2OMETA_ARTIFACT_S3_REGION"),
        "artifact_s3_access_key": os.environ.get("H2OMETA_ARTIFACT_S3_ACCESS_KEY"),
        "artifact_s3_secret_key": os.environ.get("H2OMETA_ARTIFACT_S3_SECRET_KEY"),
        "artifact_s3_prefix": os.environ.get("H2OMETA_ARTIFACT_S3_PREFIX"),
    }
    for field_name, value in overrides.items():
        if str(value or "").strip():
            setattr(cfg, field_name, str(value or "").strip())
    secure = os.environ.get("H2OMETA_ARTIFACT_S3_SECURE")
    if str(secure or "").strip():
        cfg.artifact_s3_secure = bool(
            parse_strict_env_bool(secure, name="H2OMETA_ARTIFACT_S3_SECURE")
        )


def ensure_runtime_layout(cfg: RemoteRunnerConfig) -> dict[str, bool]:
    require_current_runner_protocol_expectation(
        cfg.runner_protocol_version,
        cfg.runner_protocol_fingerprint,
    )
    assert_supported_database_backend(cfg)
    data_root = Path(cfg.data_root)
    db_path = Path(cfg.db_path)
    uploads_dir = Path(cfg.uploads_dir)
    results_dir = Path(cfg.results_dir)
    work_dir = Path(cfg.work_dir)
    logs_dir = Path(cfg.logs_dir)
    runtime_state_path = get_runtime_state_path(cfg)
    workflow_profile_dir = get_workflow_profile_dir(cfg) or resolve_default_workflow_profile_dir(cfg)
    cfg.workflow_profile_dir = str(workflow_profile_dir)
    cfg.workflow_profile_name = get_workflow_profile_name(cfg)
    workflow_profile_path = workflow_profile_dir / cfg.workflow_profile_name
    conda_prefix_dir = resolve_default_conda_prefix(cfg)
    managed_conda_root_prefix = str(cfg.managed_conda_root_prefix or "").strip()

    for directory in (
        data_root,
        db_path.parent,
        runtime_state_path.parent,
        uploads_dir,
        results_dir,
        work_dir,
        logs_dir,
        workflow_profile_dir,
        conda_prefix_dir,
        *([Path(managed_conda_root_prefix)] if managed_conda_root_prefix else []),
    ):
        directory.mkdir(parents=True, exist_ok=True)

    initialize_or_migrate_runtime_db(db_path)

    profile_content = workflow_profile_path.read_text(encoding="utf-8") if workflow_profile_path.exists() else ""
    wrapper_prefix = resolve_default_wrapper_prefix(cfg)
    if "conda-prefix:" not in profile_content or f"wrapper-prefix: {wrapper_prefix}" not in profile_content:
        workflow_profile_path.write_text(
            build_workflow_profile_content(conda_prefix=conda_prefix_dir, wrapper_prefix=wrapper_prefix),
            encoding="utf-8",
            newline="\n",
        )

    return {
        "config": bool(cfg.token),
        "sqlite": db_path.exists(),
        "directories": all(
            path.exists()
            for path in (uploads_dir, results_dir, work_dir, logs_dir, workflow_profile_dir, conda_prefix_dir)
        ),
    }


def inspect_runtime_layout(cfg: RemoteRunnerConfig) -> dict[str, bool]:
    assert_supported_database_backend(cfg)
    db_path = Path(cfg.db_path)
    uploads_dir = Path(cfg.uploads_dir)
    results_dir = Path(cfg.results_dir)
    work_dir = Path(cfg.work_dir)
    logs_dir = Path(cfg.logs_dir)
    runtime_state_path = get_runtime_state_path(cfg)
    workflow_profile_dir = get_workflow_profile_dir(cfg) or resolve_default_workflow_profile_dir(cfg)
    cfg.workflow_profile_dir = str(workflow_profile_dir)
    cfg.workflow_profile_name = get_workflow_profile_name(cfg)
    return {
        "config": bool(cfg.token),
        "sqlite": db_path.exists(),
        "directories": all(
            path.exists()
            for path in (runtime_state_path.parent, uploads_dir, results_dir, work_dir, logs_dir, workflow_profile_dir)
        ),
    }


def dump_public_config(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    data = asdict(cfg)
    data.pop("token", None)
    data.pop("api_token_actor", None)
    data.pop("api_token_roles", None)
    data.pop("database_url", None)
    data.pop("artifact_s3_access_key", None)
    data.pop("artifact_s3_secret_key", None)
    data["runnerProtocol"] = build_runner_protocol_runtime_self_attestation()
    return data
