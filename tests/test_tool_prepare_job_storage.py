from __future__ import annotations

from pathlib import Path
import sqlite3

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.sqlite_migrations import initialize_or_migrate_runtime_db
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_claims import (
    ToolPrepareWorkerIdentity,
    claim_next_tool_prepare_job,
    release_tool_prepare_worker_claim,
)
from apps.remote_runner.tool_prepare_job_storage import (
    create_tool_prepare_job,
    fail_tool_prepare_job,
    list_latest_tool_prepare_jobs_by_tool_id,
)
from apps.remote_runner.tool_prepare_publication import publish_validated_tool_for_attempt
from tests.test_tool_contract_pipeline import _cfg


def test_prepare_job_storage_migrates_reservation_columns_for_legacy_database(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy = sqlite3.connect(str(db_path))
    legacy.execute(
        """
        CREATE TABLE tool_prepare_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            message TEXT NOT NULL,
            tool_id TEXT NOT NULL,
            request_json TEXT NOT NULL,
            result_json TEXT,
            error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            cancelled_at TEXT
        )
        """
    )
    legacy.close()

    initialize_or_migrate_runtime_db(cfg.db_path)
    job = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::multiqc",
            "name": "MultiQC",
            "packageSpec": "bioconda::multiqc=1.25",
            "validationTarget": "workflow-ready",
        },
    )

    with get_connection(cfg) as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(tool_prepare_jobs)").fetchall()
        }
        row = connection.execute(
            """
            SELECT reservation_key, reservation_package_spec, reservation_validation_target
            FROM tool_prepare_jobs
            WHERE job_id = ?
            """,
            (job["jobId"],),
        ).fetchone()

    assert {
        "reservation_key",
        "reservation_package_spec",
        "reservation_validation_target",
    } <= columns
    assert row["reservation_key"] == "workflow-ready\x1fbioconda::multiqc=1.25"


def test_latest_prepare_jobs_by_tool_id_returns_safe_status_summary(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    fastqc = {
        "id": "bioconda::fastqc",
        "name": "fastqc",
        "packageSpec": "bioconda::fastqc=1.0",
        "source": "bioconda",
    }
    older = create_tool_prepare_job(cfg, fastqc)
    identity = ToolPrepareWorkerIdentity.create("worker-safe-summary")
    older_proof = claim_next_tool_prepare_job(cfg, identity=identity)
    assert older_proof is not None
    publish_validated_tool_for_attempt(
        cfg,
        proof=older_proof,
        validated_tool={
            **older["request"],
            "id": "bioconda::fastqc",
            "toolContract": {"state": "WorkflowReady", "workflowReady": True},
            "message": "Tool revision published.",
        },
    )
    assert release_tool_prepare_worker_claim(cfg, proof=older_proof) is True
    latest = create_tool_prepare_job(cfg, fastqc)
    latest_proof = claim_next_tool_prepare_job(cfg, identity=identity)
    assert latest_proof is not None
    assert latest_proof.job_id == latest["jobId"]
    fail_tool_prepare_job(
        cfg,
        latest_proof,
        code="SNAKEMAKE_DRY_RUN_FAILED",
        message="Snakemake dry-run failed.",
    )
    assert release_tool_prepare_worker_claim(cfg, proof=latest_proof) is True
    other = create_tool_prepare_job(cfg, {"id": "bioconda::multiqc", "name": "multiqc"})

    summaries = list_latest_tool_prepare_jobs_by_tool_id(
        cfg,
        ["bioconda::fastqc", "bioconda::multiqc", "missing", ""],
    )

    assert set(summaries) == {"bioconda::fastqc", "bioconda::multiqc"}
    assert summaries["bioconda::fastqc"] == {
        "jobId": latest["jobId"],
        "toolId": "bioconda::fastqc",
        "status": "failed",
        "stage": "failed",
        "message": "Snakemake dry-run failed.",
        "errorCode": "SNAKEMAKE_DRY_RUN_FAILED",
        "createdAt": summaries["bioconda::fastqc"]["createdAt"],
        "updatedAt": summaries["bioconda::fastqc"]["updatedAt"],
        "startedAt": summaries["bioconda::fastqc"]["startedAt"],
        "finishedAt": summaries["bioconda::fastqc"]["finishedAt"],
        "cancelledAt": None,
        "resultState": "",
        "workflowReady": False,
        "productionEnabled": False,
        "validationResultId": "",
        "evidenceId": "",
    }
    assert summaries["bioconda::multiqc"]["jobId"] == other["jobId"]
    assert summaries["bioconda::multiqc"]["status"] == "queued"
    assert "request" not in summaries["bioconda::fastqc"]
    assert "result" not in summaries["bioconda::fastqc"]
    assert "events" not in summaries["bioconda::fastqc"]
