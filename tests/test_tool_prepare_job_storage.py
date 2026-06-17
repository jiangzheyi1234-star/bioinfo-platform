from __future__ import annotations

from pathlib import Path
import sqlite3

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_job_storage import (
    complete_tool_prepare_job,
    create_tool_prepare_job,
    fail_tool_prepare_job,
    list_latest_tool_prepare_jobs_by_tool_id,
)
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

    older = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    complete_tool_prepare_job(
        cfg,
        older["jobId"],
        {
            "id": "bioconda::fastqc",
            "toolContract": {"state": "WorkflowReady", "workflowReady": True},
            "message": "Tool revision published.",
        },
    )
    latest = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    fail_tool_prepare_job(
        cfg,
        latest["jobId"],
        code="SNAKEMAKE_DRY_RUN_FAILED",
        message="Snakemake dry-run failed.",
    )
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
        "startedAt": None,
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
