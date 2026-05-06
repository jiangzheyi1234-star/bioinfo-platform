from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from apps.remote_runner.config import (
    ensure_runtime_layout,
    get_runtime_state_path,
    inspect_workflow_runtime,
    load_remote_runner_config,
    write_runtime_state,
)
from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.main import (
    RunCreateRequest,
    UploadCreateRequest,
    create_run,
    create_upload,
    get_pipeline_api,
    get_pipelines,
    get_result_api,
    get_result_preview_api,
    get_run as get_run_api,
    get_run_events_api,
    get_run_logs_api,
    get_run_results_api,
    get_runs as list_runs_api,
    health_live,
    health_ready,
    health_startup,
    list_results_api,
)
from config import get_app_cache_dir
from core.remote_runner.artifact import RemoteRunnerArtifactError
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION, RemoteRunnerBundleBuilder
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.manager import RemoteRunnerManager, RemoteRunnerManagerError
from tests.helpers.remote_runner_control_plane import (
    _ORIGINAL_ENSURE_WORKFLOW_RUNTIME,
    _default_workflow_runtime,
    _fake_runtime_dir,
    _fake_workflow_artifact,
    _runtime_state_json,
    _write_file_summary_pipeline,
)

def test_get_app_cache_dir_prefers_platform_cache_locations(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("config.os.name", "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-appdata"))
    assert get_app_cache_dir() == tmp_path / "local-appdata" / "H2OMeta" / "Cache"

def test_remote_runner_config_defaults_to_dynamic_loopback_port() -> None:
    cfg = RemoteRunnerConfig()

    assert cfg.bind_host == "127.0.0.1"
    assert cfg.bind_port == 0
    assert Path(cfg.runtime_state_path).parts[-2:] == ("runtime", "runner-state.json")

def test_write_runtime_state_records_assigned_port(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        version="test-version",
        data_root=str(tmp_path / "shared"),
        runtime_state_path=str(tmp_path / "shared" / "runtime" / "runner-state.json"),
    )

    state = write_runtime_state(cfg, bind_host="127.0.0.1", bind_port=43127, pid=123)
    payload = json.loads(get_runtime_state_path(cfg).read_text(encoding="utf-8"))

    assert state["bindPort"] == 43127
    assert payload["service"] == "h2ometa-remote"
    assert payload["version"] == "test-version"
    assert payload["bindHost"] == "127.0.0.1"
    assert payload["bindPort"] == 43127
    assert payload["pid"] == 123

def test_remote_runner_bundle_contains_expected_phase1_files(tmp_path: Path) -> None:
    builder = RemoteRunnerBundleBuilder()
    bundle = builder.build(version=REMOTE_RUNNER_VERSION, platform="linux-64", runtime_dir=_fake_runtime_dir(tmp_path))

    assert (bundle.bundle_dir / "remote_runner" / "main.py").exists()
    assert (bundle.bundle_dir / "remote_runner" / "run.py").exists()
    assert (bundle.bundle_dir / "remote_runner" / "requirements.txt").exists()
    assert (bundle.bundle_dir / "remote_runner" / "pipelines" / "file-summary-v1" / "pipeline.json").exists()
    assert (bundle.bundle_dir / "remote_runner" / "pipelines" / "file-summary-v1" / "Snakefile").exists()
    assert (bundle.bundle_dir / "remote_runner" / "pipelines" / "file-summary-v1" / "envs" / "base.yaml").exists()
    assert (
        bundle.bundle_dir
        / "remote_runner"
        / "pipelines"
        / "file-summary-v1"
        / "scripts"
        / "generate_outputs.py"
    ).exists()
    assert (bundle.bundle_dir / "runtime" / "bin" / "python").exists()
    assert (bundle.bundle_dir / "h2ometa-remote.service").exists()
    assert (bundle.bundle_dir / "start_service.sh").exists()
    assert (bundle.bundle_dir / "stop_service.sh").exists()
    assert (bundle.bundle_dir / "launch_remote_runner.sh").exists()
    assert (bundle.bundle_dir / "check_service.sh").exists()
    assert (bundle.bundle_dir / "run_workflow.sh").exists()
    assert "launch_remote_runner.sh" in (bundle.bundle_dir / "start_service.sh").read_text(encoding="utf-8")
    assert "launch_remote_runner.sh" in (bundle.bundle_dir / "h2ometa-remote.service").read_text(encoding="utf-8")
    launch_script_path = bundle.bundle_dir / "launch_remote_runner.sh"
    launch_script = launch_script_path.read_text(encoding="utf-8")
    assert "RUNNER_PYTHON" in launch_script
    assert 'runtime/bin/python' in launch_script
    assert "conda-unpack" in launch_script
    assert 'cd "$RUN_DIR"' in launch_script
    assert b"\r\n" not in launch_script_path.read_bytes()
    assert bundle.archive_path.exists()
    assert bundle.platform == "linux-64"
    requirements = (bundle.bundle_dir / "remote_runner" / "requirements.txt").read_text(encoding="utf-8")
    assert "snakemake" not in requirements

def test_load_remote_runner_config_preserves_workflow_runtime_metadata(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    managed_conda_command = tmp_path / "tooling" / "bin" / "micromamba"
    managed_conda_root_prefix = tmp_path / "tooling" / "micromamba-root"
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase2-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
                "managed_conda_command": str(managed_conda_command),
                "managed_conda_root_prefix": str(managed_conda_root_prefix),
                "workflow_runtime_provider": "micromamba",
                "workflow_runtime_source": "managed",
                "snakemake_command": str(snakemake_command),
                "snakemake_version": "9.1.0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    cfg = load_remote_runner_config()

    assert cfg.managed_conda_command == str(managed_conda_command)
    assert cfg.managed_conda_root_prefix == str(managed_conda_root_prefix)
    assert cfg.workflow_runtime_provider == "micromamba"
    assert cfg.workflow_runtime_source == "managed"
    assert cfg.snakemake_command == str(snakemake_command)
    assert cfg.snakemake_version == "9.1.0"

def test_inspect_workflow_runtime_runs_snakemake_with_workflow_bin_on_path(tmp_path: Path, monkeypatch) -> None:
    managed_conda_command = tmp_path / "tooling" / "workflow-env" / "bin" / "conda"
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    managed_conda_command.parent.mkdir(parents=True, exist_ok=True)
    managed_conda_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    managed_conda_command.chmod(0o755)
    snakemake_command.write_text("#!/usr/bin/env python3.12\n", encoding="utf-8")
    snakemake_command.chmod(0o755)
    cfg = RemoteRunnerConfig(
        managed_conda_command=str(managed_conda_command),
        snakemake_command=str(snakemake_command),
    )
    ensure_runtime_layout(cfg)
    calls: list[dict[str, object]] = []

    class Result:
        returncode = 0
        stdout = "9.19.0\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "env": kwargs.get("env")})
        return Result()

    monkeypatch.setattr("apps.remote_runner.config.subprocess.run", fake_run)

    result = inspect_workflow_runtime(cfg)

    assert result["ok"] is True
    assert calls[0]["cmd"] == [str(snakemake_command), "--version"]
    env = calls[0]["env"]
    assert isinstance(env, dict)
    assert env["PATH"].split(os.pathsep)[0] == str(snakemake_command.parent)
