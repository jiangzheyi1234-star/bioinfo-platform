from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.tool_prepare_claims import (
    ToolPrepareAttemptProof,
    ToolPrepareWorkerIdentity,
    release_tool_prepare_worker_claim,
)
from apps.remote_runner.tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    claim_next_tool_prepare_job,
    create_tool_prepare_job,
    fail_tool_prepare_job,
    fetch_tool_prepare_job,
    list_latest_tool_prepare_jobs_by_tool_id,
    list_tool_prepare_jobs,
    mark_tool_prepare_job_waiting_resource,
)
from apps.remote_runner.tool_prepare_publication import publish_validated_tool_for_attempt


def test_list_tool_prepare_jobs_returns_filtered_page_and_status_counts(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    jobs = [
        create_tool_prepare_job(
            cfg,
            {
                "id": f"bioconda::tool-{index}",
                "name": f"tool-{index}",
                "packageSpec": f"bioconda::tool-{index}=1.0",
                "source": "bioconda",
            },
        )
        for index in range(6)
    ]
    jobs_by_id = {job["jobId"]: job for job in jobs}
    identity = ToolPrepareWorkerIdentity.create("worker-a")

    claimed = _claim_next(cfg, identity, now="2099-06-07T10:00:00Z")
    _publish_and_release(
        cfg,
        claimed,
        jobs_by_id[claimed.job_id],
        {
            "id": jobs_by_id[claimed.job_id]["toolId"],
            "toolContract": {"state": "WorkflowReady", "workflowReady": True},
        },
    )
    running = _claim_next(cfg, identity, now="2099-06-07T10:01:00Z")
    succeeded = _claim_next(cfg, identity, now="2099-06-07T10:02:00Z")
    _publish_and_release(
        cfg,
        succeeded,
        jobs_by_id[succeeded.job_id],
        {
            "id": jobs_by_id[succeeded.job_id]["toolId"],
            "toolContract": {"state": "WorkflowReady", "workflowReady": True},
        },
    )
    failed = _claim_next(cfg, identity, now="2099-06-07T10:03:00Z")
    fail_tool_prepare_job(
        cfg,
        failed,
        code="SNAKEMAKE_DRY_RUN_FAILED",
        message="dry-run failed",
    )
    assert release_tool_prepare_worker_claim(cfg, proof=failed) is True
    waiting = _claim_next(cfg, identity, now="2099-06-07T10:04:00Z")
    mark_tool_prepare_job_waiting_resource(
        cfg,
        waiting,
        code="RESOURCE_BINDING_MISSING",
        message="database missing",
    )
    assert release_tool_prepare_worker_claim(cfg, proof=waiting) is True
    claimed_job_ids = {
        claimed.job_id,
        running.job_id,
        succeeded.job_id,
        failed.job_id,
        waiting.job_id,
    }
    cancelled = next(job for job in jobs if job["jobId"] not in claimed_job_ids)
    cancel_tool_prepare_job(cfg, cancelled["jobId"])

    page = list_tool_prepare_jobs(cfg, status="succeeded", limit=10, offset=0)
    all_jobs = list_tool_prepare_jobs(cfg, limit=3, offset=0)

    assert page["total"] == 2
    assert {item["jobId"] for item in page["items"]} == {
        claimed.job_id,
        succeeded.job_id,
    }
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
    job = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::fastqc",
            "name": "fastqc",
            "packageSpec": "bioconda::fastqc=1.0",
            "source": "bioconda",
        },
    )
    identity = ToolPrepareWorkerIdentity.create("worker-evidence")
    proof = _claim_next(cfg, identity)

    _publish_and_release(
        cfg,
        proof,
        job,
        {
            "id": "bioconda::fastqc",
            "toolRevisionId": "bioconda::fastqc@1",
            "toolContract": {"state": "WorkflowReady", "workflowReady": True},
        },
    )
    completed = fetch_tool_prepare_job(cfg, job["jobId"])
    fetched = fetch_tool_prepare_job(cfg, job["jobId"])
    latest = list_latest_tool_prepare_jobs_by_tool_id(cfg, ["bioconda::fastqc"])["bioconda::fastqc"]

    assert completed is not None
    assert fetched is not None
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

    assert "operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_QUEUE_READ].operation_id" in remote_route
    assert "list_tool_prepare_job_queue_from_request" in remote_route
    assert "def list_tool_prepare_job_queue_from_request(" in remote_service
    assert "list_tool_prepare_jobs" in remote_service
    assert "operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_QUEUE_READ].operation_id" in local_route
    assert "list_tool_prepare_job_queue_from_request" in local_route
    assert "def list_tool_prepare_job_queue_from_request(" in local_service
    assert "def list_tool_prepare_job_queue" not in proxy
    assert 'client.get_json(f"/api/v1/tools/prepare-jobs/queue' not in proxy
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


def _claim_next(
    cfg: RemoteRunnerConfig,
    identity: ToolPrepareWorkerIdentity,
    *,
    now: str | None = None,
) -> ToolPrepareAttemptProof:
    proof = claim_next_tool_prepare_job(cfg, identity=identity, now=now)
    assert proof is not None
    return proof


def _publish_and_release(
    cfg: RemoteRunnerConfig,
    proof: ToolPrepareAttemptProof,
    job: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    request = job.get("request")
    assert isinstance(request, dict)
    published = publish_validated_tool_for_attempt(
        cfg,
        proof=proof,
        validated_tool={**request, **result},
    )
    assert release_tool_prepare_worker_claim(cfg, proof=proof) is True
    return published
