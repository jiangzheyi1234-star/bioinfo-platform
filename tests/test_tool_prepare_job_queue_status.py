from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    claim_next_tool_prepare_job,
    complete_tool_prepare_job,
    create_tool_prepare_job,
    fail_tool_prepare_job,
    fetch_tool_prepare_job,
    list_latest_tool_prepare_jobs_by_tool_id,
    list_tool_prepare_jobs,
    mark_tool_prepare_job_waiting_resource,
)


def test_list_tool_prepare_jobs_returns_filtered_page_and_status_counts(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    jobs = [
        create_tool_prepare_job(cfg, {"id": f"bioconda::tool-{index}", "name": f"tool-{index}"})
        for index in range(6)
    ]
    jobs_by_id = {job["jobId"]: job for job in jobs}

    claimed = claim_next_tool_prepare_job(cfg, worker_id="worker-a", now="2099-06-07T10:00:00Z")
    assert claimed is not None
    complete_tool_prepare_job(
        cfg,
        claimed["jobId"],
        {"id": jobs_by_id[claimed["jobId"]]["toolId"], "toolContract": {"state": "WorkflowReady", "workflowReady": True}},
    )
    running = claim_next_tool_prepare_job(cfg, worker_id="worker-a", now="2099-06-07T10:01:00Z")
    assert running is not None
    remaining_jobs = [job for job in jobs if job["jobId"] not in {claimed["jobId"], running["jobId"]}]
    succeeded, failed, waiting, cancelled = remaining_jobs
    complete_tool_prepare_job(
        cfg,
        succeeded["jobId"],
        {"id": succeeded["toolId"], "toolContract": {"state": "WorkflowReady", "workflowReady": True}},
    )
    fail_tool_prepare_job(cfg, failed["jobId"], code="SNAKEMAKE_DRY_RUN_FAILED", message="dry-run failed")
    mark_tool_prepare_job_waiting_resource(
        cfg,
        waiting["jobId"],
        code="RESOURCE_BINDING_MISSING",
        message="database missing",
    )
    cancel_tool_prepare_job(cfg, cancelled["jobId"])

    page = list_tool_prepare_jobs(cfg, status="succeeded", limit=10, offset=0)
    all_jobs = list_tool_prepare_jobs(cfg, limit=3, offset=0)

    assert page["total"] == 2
    assert {item["jobId"] for item in page["items"]} == {claimed["jobId"], succeeded["jobId"]}
    assert page["statusCounts"] == {
        "cancelled": 1,
        "failed": 1,
        "queued": 0,
        "running": 1,
        "succeeded": 2,
        "waiting_resource": 1,
        "exhausted": 0,
    }
    assert all_jobs["total"] == 6
    assert all_jobs["limit"] == 3
    assert all_jobs["offset"] == 0
    assert len(all_jobs["items"]) == 3


def test_completed_prepare_job_exposes_validation_evidence_ids(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})

    completed = complete_tool_prepare_job(
        cfg,
        job["jobId"],
        {
            "id": "bioconda::fastqc",
            "toolRevisionId": "bioconda::fastqc@1",
            "toolContract": {"state": "WorkflowReady", "workflowReady": True},
        },
    )
    fetched = fetch_tool_prepare_job(cfg, job["jobId"])
    latest = list_latest_tool_prepare_jobs_by_tool_id(cfg, ["bioconda::fastqc"])["bioconda::fastqc"]

    assert completed["result"]["validationResultId"].startswith("toolval_")
    assert completed["result"]["evidenceId"].startswith("evid_")
    assert completed["validationResultId"] == completed["result"]["validationResultId"]
    assert completed["evidenceId"] == completed["result"]["evidenceId"]
    assert fetched["result"]["validationResultId"] == completed["result"]["validationResultId"]
    assert fetched["result"]["evidenceId"] == completed["result"]["evidenceId"]
    assert fetched["validationResultId"] == completed["result"]["validationResultId"]
    assert fetched["evidenceId"] == completed["result"]["evidenceId"]
    assert latest["validationResultId"] == completed["result"]["validationResultId"]
    assert latest["evidenceId"] == completed["result"]["evidenceId"]


def test_prepare_job_queue_api_layers_are_exposed() -> None:
    root = Path(__file__).resolve().parents[1]
    remote_route = (root / "apps" / "remote_runner" / "tool_routes.py").read_text(encoding="utf-8")
    remote_service = (root / "apps" / "remote_runner" / "tool_service.py").read_text(encoding="utf-8")
    local_route = (root / "apps" / "api" / "tool_routes.py").read_text(encoding="utf-8")
    local_service = (root / "apps" / "api" / "tool_service.py").read_text(encoding="utf-8")
    proxy = (root / "core" / "remote_runner" / "proxy.py").read_text(encoding="utf-8")
    manager = (root / "core" / "app_runtime" / "managers" / "tool.py").read_text(encoding="utf-8")

    assert '@router.get("/api/v1/tools/prepare-jobs/queue")' in remote_route
    assert "list_tool_prepare_job_queue_from_request" in remote_route
    assert "def list_tool_prepare_job_queue_from_request(" in remote_service
    assert "list_tool_prepare_jobs" in remote_service
    assert '@router.get("/api/v1/tools/prepare-jobs/queue")' in local_route
    assert "list_tool_prepare_job_queue_from_request" in local_route
    assert "def list_tool_prepare_job_queue_from_request(" in local_service
    assert "def list_tool_prepare_job_queue" in proxy
    assert "def list_tool_prepare_job_queue" in manager


def _config(tmp_path: Path) -> RemoteRunnerConfig:
    (tmp_path / "release" / "snakemake_wrappers").mkdir(parents=True)
    cfg = RemoteRunnerConfig(
        token="prepare-queue-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
    )
    ensure_runtime_layout(cfg)
    return cfg
