from __future__ import annotations

from pathlib import Path
import sqlite3

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.sqlite_migrations import initialize_or_migrate_runtime_db
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_job_storage import (
    claim_next_tool_prepare_job,
    create_tool_prepare_job,
    fetch_tool_prepare_job,
    heartbeat_tool_prepare_job,
    mark_tool_prepare_job_worker_failure,
)


def test_claim_tool_prepare_job_sets_lease_and_attempt(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})

    claimed = claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )

    assert claimed is not None
    assert claimed["status"] == "running"
    assert claimed["stage"] == "claimed"
    assert claimed["lease"] == {
        "claimedBy": "worker-a",
        "claimedUntil": "2099-06-07T10:00:30Z",
        "heartbeatAt": "2099-06-07T10:00:00Z",
        "attempts": 1,
        "maxAttempts": 3,
        "nextAttemptAt": None,
        "exhaustedAt": None,
    }


def test_expired_running_tool_prepare_job_can_be_reclaimed(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    first = claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert first is not None

    assert claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-b",
        now="2099-06-07T10:00:05Z",
        lease_seconds=10,
    ) is None
    reclaimed = claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-b",
        now="2099-06-07T10:00:11Z",
        lease_seconds=10,
    )

    assert reclaimed is not None
    assert reclaimed["jobId"] == first["jobId"]
    assert reclaimed["lease"]["claimedBy"] == "worker-b"
    assert reclaimed["lease"]["claimedUntil"] == "2099-06-07T10:00:21Z"
    assert reclaimed["lease"]["attempts"] == 2
    assert [event["stage"] for event in reclaimed["events"]] == ["queued", "claimed", "reclaimed"]


def test_legacy_running_tool_prepare_job_without_lease_can_be_reclaimed(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET status = 'running', stage = 'dry_run', message = 'Legacy worker is running.'
            WHERE job_id = ?
            """,
            (job["jobId"],),
        )
        connection.commit()

    reclaimed = claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-b",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )

    assert reclaimed is not None
    assert reclaimed["jobId"] == job["jobId"]
    assert reclaimed["lease"]["claimedBy"] == "worker-b"
    assert reclaimed["lease"]["attempts"] == 1
    assert [event["stage"] for event in reclaimed["events"]] == ["queued", "reclaimed"]


def test_tool_prepare_job_heartbeat_extends_current_lease(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    claimed = claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert claimed is not None

    accepted = heartbeat_tool_prepare_job(
        cfg,
        claimed["jobId"],
        worker_id="worker-a",
        now="2099-06-07T10:00:05Z",
        lease_seconds=10,
    )
    rejected = heartbeat_tool_prepare_job(
        cfg,
        claimed["jobId"],
        worker_id="worker-b",
        now="2099-06-07T10:00:06Z",
        lease_seconds=10,
    )

    assert accepted == {"accepted": True, "claimedUntil": "2099-06-07T10:00:15Z"}
    assert rejected == {"accepted": False, "reason": "not_current_worker"}
    refreshed = fetch_tool_prepare_job(cfg, claimed["jobId"])
    assert refreshed is not None
    assert refreshed["lease"]["heartbeatAt"] == "2099-06-07T10:00:05Z"
    assert refreshed["lease"]["claimedUntil"] == "2099-06-07T10:00:15Z"


def test_tool_prepare_worker_failure_retries_then_exhausts(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    job = create_tool_prepare_job(
        cfg,
        {"id": "bioconda::fastqc", "name": "fastqc", "maxAttempts": 2},
    )
    first = claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-a",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    assert first is not None

    retry = mark_tool_prepare_job_worker_failure(
        cfg,
        job["jobId"],
        code="TOOL_PREPARE_WORKER_CRASHED",
        message="worker crashed",
        now="2099-06-07T10:00:01Z",
        retry_delay_seconds=30,
    )
    assert retry["status"] == "queued"
    assert retry["stage"] == "retry_wait"
    assert retry["lease"]["attempts"] == 1
    assert retry["lease"]["nextAttemptAt"] == "2099-06-07T10:00:31Z"
    assert claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-b",
        now="2099-06-07T10:00:30Z",
        lease_seconds=10,
    ) is None

    second = claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-b",
        now="2099-06-07T10:00:31Z",
        lease_seconds=10,
    )
    assert second is not None
    exhausted = mark_tool_prepare_job_worker_failure(
        cfg,
        job["jobId"],
        code="TOOL_PREPARE_WORKER_CRASHED",
        message="worker crashed again",
        now="2099-06-07T10:00:32Z",
        retry_delay_seconds=30,
    )

    assert exhausted["status"] == "exhausted"
    assert exhausted["stage"] == "exhausted"
    assert exhausted["errorCode"] == "TOOL_PREPARE_WORKER_CRASHED"
    assert exhausted["lease"]["attempts"] == 2
    assert exhausted["lease"]["exhaustedAt"] == "2099-06-07T10:00:32Z"
    assert claim_next_tool_prepare_job(
        cfg,
        worker_id="worker-c",
        now="2099-06-07T10:01:32Z",
        lease_seconds=10,
    ) is None


def test_tool_prepare_job_migrates_lease_columns_for_legacy_database(tmp_path: Path) -> None:
    cfg = _config(tmp_path, initialize=False)
    db_path = Path(cfg.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as connection:
        connection.execute(
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
        connection.commit()

    initialize_or_migrate_runtime_db(cfg.db_path)
    job = create_tool_prepare_job(
        cfg,
        {"id": "bioconda::multiqc", "name": "multiqc", "maxAttempts": 4},
    )

    with get_connection(cfg) as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(tool_prepare_jobs)").fetchall()}

    assert {
        "claimed_by",
        "claimed_until",
        "heartbeat_at",
        "attempts",
        "max_attempts",
        "next_attempt_at",
        "exhausted_at",
        "backoff_seconds",
        "last_worker_error_json",
    } <= columns
    assert job["lease"]["maxAttempts"] == 4


def _config(tmp_path: Path, *, initialize: bool = True) -> RemoteRunnerConfig:
    (tmp_path / "release" / "snakemake_wrappers").mkdir(parents=True)
    cfg = RemoteRunnerConfig(
        token="prepare-lease-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
    )
    if initialize:
        ensure_runtime_layout(cfg)
    return cfg
