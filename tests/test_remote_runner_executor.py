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

def test_executor_invokes_snakemake_cli_with_use_conda(tmp_path: Path, monkeypatch) -> None:
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(snakemake_command),
    )
    ensure_runtime_layout(cfg)
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))

    calls: list[list[str]] = []

    class Result:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda cfg, run_id, result_dir: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    from apps.remote_runner.storage import persist_upload

    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )

    run_snakemake_execution(
        cfg,
        run_id="run_phase2",
        request_id="req_phase2",
        run_spec={
            "pipelineId": "file-summary-v1",
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "reads"}],
        },
    )

    assert len(calls) == 2
    assert calls[0][0] == str(snakemake_command)
    assert "--use-conda" in calls[0]
    assert "-n" in calls[0]
    assert "--use-conda" in calls[1]
    run_config = json.loads((Path(cfg.work_dir) / "run_phase2" / "run-config.json").read_text(encoding="utf-8"))
    assert run_config["pipeline_id"] == "file-summary-v1"
    assert run_config["inputs"][0]["path"] == upload["path"]
    assert run_config["inputs"][0]["sha256"] == upload["sha256"]

def test_executor_fails_when_upload_input_is_missing(tmp_path: Path, monkeypatch) -> None:
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(tmp_path / "snakemake"),
    )
    ensure_runtime_layout(cfg)
    _write_file_summary_pipeline(Path(cfg.release_dir))
    from apps.remote_runner.storage import create_run_record, fetch_run

    create_run_record(
        cfg,
        server_id="srv_demo",
        request_id="req_missing_input",
        run_spec={
            "runId": "run_missing_input",
            "projectId": "proj_demo",
            "pipelineId": "file-summary-v1",
            "inputs": [{"uploadId": "upl_missing", "filename": "missing.fastq", "role": "reads"}],
        },
        idempotency_key="idem_missing_input",
        payload_hash="h" * 64,
    )

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *args, **kwargs: None)
    run_snakemake_execution(
        cfg,
        run_id="run_missing_input",
        request_id="req_missing_input",
        run_spec={
            "projectId": "proj_demo",
            "pipelineId": "file-summary-v1",
            "inputs": [{"uploadId": "upl_missing", "filename": "missing.fastq", "role": "reads"}],
        },
    )

    run = fetch_run(cfg, "run_missing_input")
    assert run["status"] == "failed"
    assert run["stage"] == "validate"
    assert run["lastError"]["code"] == "INPUT_NOT_FOUND"

def test_executor_exports_managed_conda_runtime_when_configured(tmp_path: Path, monkeypatch) -> None:
    managed_conda_command = tmp_path / "tooling" / "bin" / "micromamba"
    managed_conda_root_prefix = tmp_path / "tooling" / "micromamba-root"
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        managed_conda_command=str(managed_conda_command),
        managed_conda_root_prefix=str(managed_conda_root_prefix),
        snakemake_command=str(snakemake_command),
    )
    ensure_runtime_layout(cfg)
    managed_conda_command.parent.mkdir(parents=True, exist_ok=True)
    managed_conda_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))

    calls: list[dict[str, object]] = []

    class Result:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "env": kwargs.get("env")})
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda cfg, run_id, result_dir: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    from apps.remote_runner.storage import persist_upload

    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )

    run_snakemake_execution(
        cfg,
        run_id="run_phase2_managed_conda",
        request_id="req_phase2_managed_conda",
        run_spec={
            "pipelineId": "file-summary-v1",
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "reads"}],
        },
    )

    assert len(calls) == 2
    for call in calls:
        env = call["env"]
        assert isinstance(env, dict)
        assert env["H2OMETA_MANAGED_CONDA_COMMAND"] == str(managed_conda_command)
        assert env["MAMBA_ROOT_PREFIX"] == str(managed_conda_root_prefix)
        path_entries = env["PATH"].split(os.pathsep)
        assert path_entries[0] == str(snakemake_command.parent)
        assert path_entries[1] == str(managed_conda_command.parent)
