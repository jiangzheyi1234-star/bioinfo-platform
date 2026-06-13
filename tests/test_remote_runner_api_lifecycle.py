from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from apps.remote_runner.config import (
    ensure_runtime_layout,
    load_remote_runner_config,
)
from apps.remote_runner.errors import RemoteRunnerAuthError
from core.contracts.pipeline_manifest import PipelineRegistryError
from apps.remote_runner.api_models import RunCreateRequest, UploadCreateRequest
from apps.remote_runner.execution_query_routes import (
    cancel_run_api,
    get_result_api,
    get_result_preview_api,
    get_run as get_run_api,
    get_run_events_api,
    get_run_logs_api,
    get_run_results_api,
    get_runs as list_runs_api,
    list_results_api,
)
from apps.remote_runner.health_routes import health_live, health_ready, health_startup, health_workers
from apps.remote_runner.pipeline_routes import get_pipeline_api, get_pipelines
from apps.remote_runner.run_worker_storage import register_run_worker
from apps.remote_runner.submission_routes import create_run, create_upload
from apps.remote_runner.workflow_run_storage import create_run_record
from tests.helpers.remote_runner_control_plane import (
    _write_file_summary_pipeline,
)

def test_remote_runner_health_endpoints_require_auth_and_do_not_mutate_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase1-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    with pytest.raises(RemoteRunnerAuthError, match="runner authentication failed"):
        asyncio.run(health_startup(authorization=None))

    cfg = load_remote_runner_config()
    ensure_runtime_layout(cfg)
    startup = asyncio.run(health_startup(authorization="Bearer phase1-token"))
    live = asyncio.run(health_live(authorization="Bearer phase1-token"))
    ready = asyncio.run(health_ready(authorization="Bearer phase1-token"))

    assert startup["status"] == "ok"
    assert live["status"] == "ok"
    assert ready["status"] == "failed"
    assert ready["checks"]["workflow_runtime"] is False
    assert ready["workflowRuntime"]["ok"] is False
    assert Path(tmp_path / "shared" / "data" / "runner.db").exists()

def test_remote_runner_health_does_not_create_runtime_layout(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase1-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    startup = asyncio.run(health_startup(authorization="Bearer phase1-token"))
    ready = asyncio.run(health_ready(authorization="Bearer phase1-token"))

    assert startup["status"] == "failed"
    assert ready["status"] == "failed"
    assert not Path(tmp_path / "shared" / "data" / "runner.db").exists()


def test_remote_runner_worker_health_endpoint_reports_worker_sessions(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase-worker-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    cfg = load_remote_runner_config()
    ensure_runtime_layout(cfg)
    register_run_worker(
        cfg,
        worker_id="worker-api",
        session_id="session-api",
        pid=789,
        hostname="host-api",
        now="2099-06-07T10:00:00Z",
    )

    response = asyncio.run(health_workers(authorization="Bearer phase-worker-token"))

    assert response["data"]["queueDepth"] == 0
    assert response["data"]["claimedJobs"] == 0
    assert response["data"]["workers"][0]["workerId"] == "worker-api"
    assert response["data"]["workers"][0]["sessionId"] == "session-api"


def test_remote_runner_cancel_run_endpoint_records_cancel_command(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "phase-cancel-token",
                "data_root": str(tmp_path / "shared"),
                "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    cfg = load_remote_runner_config()
    ensure_runtime_layout(cfg)
    create_run_record(
        cfg,
        server_id="srv_cancel_api",
        request_id="req_cancel_api",
        run_spec={
            "runId": "run_cancel_api",
            "projectId": "proj_cancel_api",
            "pipelineId": "pipeline_cancel_api",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key="idem_cancel_api",
        payload_hash="hash_cancel_api",
    )

    response = asyncio.run(cancel_run_api("run_cancel_api", authorization="Bearer phase-cancel-token"))
    run = asyncio.run(get_run_api("run_cancel_api", authorization="Bearer phase-cancel-token"))

    assert response["data"]["runId"] == "run_cancel_api"
    assert response["data"]["status"] == "canceling"
    assert response["data"]["commandId"].startswith("cmd_")
    assert run["data"]["status"] == "canceling"


def test_remote_runner_upload_persists_file_and_metadata(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
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
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    ensure_runtime_layout(load_remote_runner_config())

    payload = UploadCreateRequest(
        filename="reads.fastq",
        contentBase64="QEdPQgo=",
        mimeType="text/plain",
    )
    response = asyncio.run(create_upload(payload, authorization="Bearer phase2-token"))

    assert response["data"]["uploadId"].startswith("upl_")
    assert response["data"]["sha256"]
    assert Path(response["data"]["path"]).exists()

def test_remote_runner_pipeline_api_lists_registered_pipelines(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
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
                "release_dir": str(tmp_path / "release"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    (tmp_path / "release" / "snakemake_wrappers").mkdir(parents=True)
    ensure_runtime_layout(load_remote_runner_config())
    _write_file_summary_pipeline(tmp_path / "release")

    items = asyncio.run(get_pipelines(authorization="Bearer phase2-token"))["data"]["items"]
    detail = asyncio.run(get_pipeline_api("file-summary-v1", authorization="Bearer phase2-token"))["data"]

    assert items[0]["pipelineId"] == "file-summary-v1"
    assert items[0]["category"] == "Sequence Utilities"
    assert items[0]["status"] == "installed"
    assert items[0]["enabled"] is True
    assert detail["pipelineId"] == "file-summary-v1"
    assert detail["paramsSchema"]["type"] == "object"
    assert detail["uiSchema"]["inputs"]["widget"] == "file-upload"


def test_remote_runner_health_ready_surfaces_invalid_pipeline_manifest(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
    release_dir = tmp_path / "release"
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
                "release_dir": str(release_dir),
            }
        ),
        encoding="utf-8",
    )
    pipeline_dir = release_dir / "pipelines" / "broken-v1"
    pipeline_dir.mkdir(parents=True)
    (pipeline_dir / "pipeline.json").write_text("{", encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    with pytest.raises(PipelineRegistryError) as exc_info:
        asyncio.run(health_ready(authorization="Bearer phase2-token"))

    assert str(exc_info.value) == "PIPELINE_MANIFEST_INVALID_JSON"


def test_remote_runner_create_run_rejects_unknown_pipeline(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
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
                "release_dir": str(tmp_path / "release"),
                "managed_conda_command": sys.executable,
                "snakemake_command": sys.executable,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    (tmp_path / "release" / "snakemake_wrappers").mkdir(parents=True)
    ensure_runtime_layout(load_remote_runner_config())
    _write_file_summary_pipeline(tmp_path / "release")

    with pytest.raises(PipelineRegistryError) as exc_info:
        asyncio.run(
            create_run(
                RunCreateRequest(
                    serverId="srv_demo",
                    requestId="req_unknown_pipeline",
                    runSpec={"projectId": "proj_demo", "pipelineId": "unknown-v1", "inputs": []},
                ),
                authorization="Bearer phase2-token",
                idempotency_key="idem-unknown-pipeline",
                x_request_id="req_unknown_pipeline",
            )
        )

    assert str(exc_info.value) == "PIPELINE_NOT_FOUND"

def test_remote_runner_create_run_rejects_invalid_pipeline_params(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
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
                "release_dir": str(tmp_path / "release"),
                "managed_conda_command": sys.executable,
                "snakemake_command": sys.executable,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    (tmp_path / "release" / "snakemake_wrappers").mkdir(parents=True)
    ensure_runtime_layout(load_remote_runner_config())
    _write_file_summary_pipeline(tmp_path / "release")

    with pytest.raises(PipelineRegistryError) as exc_info:
        asyncio.run(
            create_run(
                RunCreateRequest(
                    serverId="srv_demo",
                    requestId="req_bad_params",
                    runSpec={
                        "projectId": "proj_demo",
                        "pipelineId": "file-summary-v1",
                        "inputs": [{"uploadId": "upl_demo"}],
                        "params": {"threads": 0},
                    },
                ),
                authorization="Bearer phase2-token",
                idempotency_key="idem-bad-params",
                x_request_id="req_bad_params",
            )
        )

    assert str(exc_info.value) == "PARAM_SCHEMA_INVALID"

def test_remote_runner_run_lifecycle_produces_events_logs_and_results(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
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
                "release_dir": str(tmp_path / "release"),
                "managed_conda_command": sys.executable,
                "snakemake_command": sys.executable,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    (tmp_path / "release" / "snakemake_wrappers").mkdir(parents=True)
    ensure_runtime_layout(load_remote_runner_config())
    _write_file_summary_pipeline(tmp_path / "release")

    submit = asyncio.run(
        create_run(
            RunCreateRequest(
                serverId="srv_demo",
                requestId="req_phase2",
                runSpec={
                    "projectId": "proj_demo",
                    "pipelineId": "file-summary-v1",
                    "inputs": [{"uploadId": "upl_demo"}],
                },
            ),
            authorization="Bearer phase2-token",
            idempotency_key="idem-phase2",
            x_request_id="req_phase2",
        )
    )
    run_id = submit["data"]["runId"]

    cfg = load_remote_runner_config()
    result_dir = Path(cfg.results_dir) / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "run-report.html").write_text("<h1>done</h1>", encoding="utf-8")
    (result_dir / "summary.tsv").write_text("sample\tabundance\ttaxonomy\nsample_alpha\t0.42\tBacteroides\n", encoding="utf-8")
    (result_dir / "raw-log.txt").write_text("done\n", encoding="utf-8")
    from apps.remote_runner.storage import append_log_lines, persist_artifact, update_run_state
    append_log_lines(cfg, run_id, "stdout", ["snakemake completed"])
    persist_artifact(cfg, run_id=run_id, kind="report", path=result_dir / "run-report.html", mime_type="text/html")
    persist_artifact(cfg, run_id=run_id, kind="table", path=result_dir / "summary.tsv", mime_type="text/tab-separated-values")
    persist_artifact(cfg, run_id=run_id, kind="log", path=result_dir / "raw-log.txt", mime_type="text/plain")
    update_run_state(
        cfg,
        run_id=run_id,
        status="completed",
        stage="finalize",
        message="Execution completed.",
        request_id="req_phase2",
        result_dir=str(result_dir),
    )

    final_run = None
    for _ in range(40):
        current = asyncio.run(get_run_api(run_id, authorization="Bearer phase2-token"))["data"]
        if current["status"] in {"completed", "failed"}:
            final_run = current
            break
        asyncio.run(asyncio.sleep(0.05))

    assert final_run is not None
    assert final_run["status"] == "completed"

    runs = asyncio.run(list_runs_api(authorization="Bearer phase2-token"))["data"]["items"]
    assert any(item["runId"] == run_id for item in runs)

    events = asyncio.run(get_run_events_api(run_id, authorization="Bearer phase2-token"))["data"]["items"]
    assert len(events) >= 2

    logs = asyncio.run(get_run_logs_api(run_id, authorization="Bearer phase2-token"))["data"]
    assert any("completed" in line for line in logs["lines"])

    results = asyncio.run(get_run_results_api(run_id, authorization="Bearer phase2-token"))["data"]
    assert results["artifacts"]

    result_list = asyncio.run(list_results_api(authorization="Bearer phase2-token"))["data"]["items"]
    result_id = next(item["resultId"] for item in result_list if item["runId"] == run_id)
    result_detail = asyncio.run(get_result_api(result_id, authorization="Bearer phase2-token"))["data"]
    assert result_detail["artifactCount"] >= 1

    preview = asyncio.run(get_result_preview_api(result_id, authorization="Bearer phase2-token"))["data"]
    assert preview["artifactId"]

def test_remote_runner_upload_rejects_oversized_payload(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
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
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setattr("apps.remote_runner.upload_storage.MAX_UPLOAD_BYTES", 8)
    payload = UploadCreateRequest(
        filename="reads.fastq",
        contentBase64="QUJDREVGR0hJSg==",
        mimeType="text/plain",
    )

    try:
        asyncio.run(create_upload(payload, authorization="Bearer phase2-token"))
    except ValueError as exc:
        assert str(exc) == "UPLOAD_TOO_LARGE"
    else:
        raise AssertionError("oversized upload should be rejected")

def test_result_preview_truncates_large_text_payload(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "runner.json"
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
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    ensure_runtime_layout(load_remote_runner_config())

    cfg = load_remote_runner_config()
    run_id = "run_preview_large"
    result_dir = Path(cfg.results_dir) / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    large_text = "x" * (300 * 1024)
    artifact_path = result_dir / "raw-log.txt"
    artifact_path.write_text(large_text, encoding="utf-8")

    from apps.remote_runner.storage import (
        fetch_result,
        get_connection,
        persist_artifact,
        update_run_state,
    )

    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO runs (
                run_id, server_id, project_id, pipeline_id, pipeline_version, run_spec_version,
                status, stage, state_version, message, started_at, finished_at, result_dir,
                last_error_json, last_updated_at, request_id, submitted_at, run_spec_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "srv_demo",
                "proj_demo",
                "taxonomy-v1",
                "0.1.0",
                "2026-04-21",
                "running",
                "submitted",
                1,
                "Run accepted",
                None,
                None,
                "",
                None,
                "2026-04-21T12:00:00Z",
                "req_preview_large",
                "2026-04-21T12:00:00Z",
                "{}",
            ),
        )
        connection.commit()

    update_run_state(
        cfg,
        run_id=run_id,
        status="completed",
        stage="finalize",
        message="done",
        request_id="req_preview_large",
        result_dir=str(result_dir),
    )
    artifact = persist_artifact(
        cfg,
        run_id=run_id,
        kind="log",
        path=artifact_path,
        mime_type="text/plain",
    )
    result_id = fetch_result(cfg, f"res_{run_id}")["resultId"]

    preview = asyncio.run(
        get_result_preview_api(
            result_id,
            artifact_id=artifact["artifactId"],
            authorization="Bearer phase2-token",
        )
    )["data"]["preview"]

    assert preview["kind"] == "text"
    assert preview["truncated"] is True
    assert len(preview["content"]) <= 256 * 1024
