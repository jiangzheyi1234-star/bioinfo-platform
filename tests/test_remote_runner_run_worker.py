from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.reconciler import run_active_reconciler_once
from apps.remote_runner.run_execution_storage import claim_next_run_job, request_run_cancel
from apps.remote_runner.run_worker import process_next_run_job
from apps.remote_runner.storage import create_run_record, fetch_run, update_run_state
from apps.remote_runner.storage_core import get_connection


class FakeClock:
    def __init__(self) -> None:
        self.tick = 0

    def __call__(self) -> str:
        self.tick += 1
        return f"2099-06-07T10:00:{self.tick:02d}Z"


def _config(tmp_path: Path) -> RemoteRunnerConfig:
    (tmp_path / "release" / "snakemake_wrappers").mkdir(parents=True)
    return RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        managed_conda_command="python",
        snakemake_command="snakemake",
    )


def _create_queued_run(cfg: RemoteRunnerConfig, run_id: str = "run_worker") -> str:
    created = create_run_record(
        cfg,
        server_id="srv_worker",
        request_id="req_worker",
        run_spec={
            "runId": run_id,
            "projectId": "proj_worker",
            "pipelineId": "pipeline_worker",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"payload_{run_id}",
    )
    return created.run["runId"]


def test_run_worker_claims_job_and_completes_current_attempt(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    run_id = _create_queued_run(cfg)
    seen: list[dict[str, Any]] = []
    clock = FakeClock()

    def fake_execute(
        cfg: RemoteRunnerConfig,
        *,
        run_id: str,
        request_id: str,
        run_spec: dict[str, Any],
        **_attempt_context: Any,
    ) -> None:
        seen.append({"runId": run_id, "requestId": request_id, "runSpec": run_spec})
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Fake worker execution completed.",
            request_id=request_id,
        )

    result = process_next_run_job(
        cfg,
        worker_id="worker_test",
        execute_run=fake_execute,
        lease_seconds=30,
        heartbeat_interval_seconds=0.01,
        now_factory=clock,
    )

    assert result["claimed"] is True
    assert result["runId"] == run_id
    assert result["attemptCompletion"]["accepted"] is True
    assert result["attemptCompletion"]["state"] == "succeeded"
    assert seen == [
        {
            "runId": run_id,
            "requestId": "req_worker",
            "runSpec": {
                "runId": run_id,
                "projectId": "proj_worker",
                "pipelineId": "pipeline_worker",
                "pipelineVersion": "0.1.0",
            },
        }
    ]

    run = fetch_run(cfg, run_id)
    assert run is not None
    assert run["status"] == "completed"
    with get_connection(cfg) as connection:
        job = connection.execute("SELECT state FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        attempt = connection.execute("SELECT state FROM run_attempts WHERE run_id = ?", (run_id,)).fetchone()
        lease = connection.execute("SELECT state FROM run_leases WHERE run_id = ?", (run_id,)).fetchone()
    assert job["state"] == "completed"
    assert attempt["state"] == "succeeded"
    assert lease["state"] == "completed"


def test_run_worker_passes_attempt_context_to_executor(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    run_id = _create_queued_run(cfg, "run_worker_attempt_context")
    seen: list[dict[str, Any]] = []
    clock = FakeClock()

    def fake_execute(
        cfg: RemoteRunnerConfig,
        *,
        run_id: str,
        request_id: str,
        run_spec: dict[str, Any],
        attempt_id: str,
        lease_generation: int,
        attempt_work_dir: str,
    ) -> None:
        seen.append(
            {
                "runId": run_id,
                "requestId": request_id,
                "runSpec": run_spec,
                "attemptId": attempt_id,
                "leaseGeneration": lease_generation,
                "attemptWorkDir": attempt_work_dir,
            }
        )
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Fake worker execution completed.",
            request_id=request_id,
        )

    result = process_next_run_job(
        cfg,
        worker_id="worker_context",
        execute_run=fake_execute,
        lease_seconds=30,
        heartbeat_interval_seconds=0,
        now_factory=clock,
    )

    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT work_dir FROM run_attempts WHERE attempt_id = ?",
            (result["attemptId"],),
        ).fetchone()

    assert result["claimed"] is True
    assert attempt is not None
    assert seen == [
        {
            "runId": run_id,
            "requestId": "req_worker",
            "runSpec": {
                "runId": run_id,
                "projectId": "proj_worker",
                "pipelineId": "pipeline_worker",
                "pipelineVersion": "0.1.0",
            },
            "attemptId": result["attemptId"],
            "leaseGeneration": result["leaseGeneration"],
            "attemptWorkDir": attempt["work_dir"],
        }
    ]
    assert Path(seen[0]["attemptWorkDir"]).parent == Path(cfg.work_dir) / "attempts"


def test_run_worker_heartbeats_while_fake_executor_runs(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    _create_queued_run(cfg, "run_worker_heartbeat")
    heartbeat_seen = False
    initial_heartbeat = ""
    clock = FakeClock()

    def fake_execute(
        cfg: RemoteRunnerConfig,
        *,
        run_id: str,
        request_id: str,
        run_spec: dict[str, Any],
        **_attempt_context: Any,
    ) -> None:
        nonlocal heartbeat_seen, initial_heartbeat
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with get_connection(cfg) as connection:
                lease = connection.execute(
                    "SELECT heartbeat_at FROM run_leases WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            if lease is not None:
                if not initial_heartbeat:
                    initial_heartbeat = str(lease["heartbeat_at"])
                elif lease["heartbeat_at"] != initial_heartbeat:
                    heartbeat_seen = True
                    break
            time.sleep(0.01)
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Fake worker execution completed.",
            request_id=request_id,
        )

    result = process_next_run_job(
        cfg,
        worker_id="worker_heartbeat",
        execute_run=fake_execute,
        lease_seconds=30,
        heartbeat_interval_seconds=0.01,
        now_factory=clock,
    )

    assert result["claimed"] is True
    assert heartbeat_seen is True


def test_run_worker_does_not_publish_failure_for_stale_attempt(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    _create_queued_run(cfg, "run_worker_stale_attempt")
    clock = FakeClock()

    def fake_execute(
        cfg: RemoteRunnerConfig,
        *,
        run_id: str,
        request_id: str,
        run_spec: dict[str, Any],
        attempt_id: str,
        lease_generation: int,
        attempt_work_dir: str,
    ) -> None:
        run_active_reconciler_once(
            cfg,
            now="2099-06-07T10:05:00Z",
            retry_delay_seconds=0,
        )
        reclaimed = claim_next_run_job(
            cfg,
            worker_id="worker_reclaim",
            now="2099-06-07T10:05:00Z",
            lease_seconds=30,
        )
        assert reclaimed is not None
        assert reclaimed["leaseGeneration"] == lease_generation + 1
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Stale attempt should not publish.",
            request_id=request_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )

    result = process_next_run_job(
        cfg,
        worker_id="worker_stale",
        execute_run=fake_execute,
        lease_seconds=1,
        heartbeat_interval_seconds=0,
        now_factory=clock,
    )

    assert result["claimed"] is True
    assert result["executionError"] == "RUN_ATTEMPT_STALE"
    assert result["attemptCompletion"]["accepted"] is False
    assert result["attemptCompletion"]["reason"] == "stale_generation"
    run = fetch_run(cfg, "run_worker_stale_attempt")
    assert run is not None
    assert run["status"] == "queued"


def test_run_worker_passes_stale_lease_cancellation_callback_to_executor(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import run_worker

    cfg = _config(tmp_path)
    _create_queued_run(cfg, "run_worker_stale_cancellation")
    clock = FakeClock()
    cancel_seen = False

    def fake_executor(
        cfg: RemoteRunnerConfig,
        *,
        run_id: str,
        request_id: str,
        run_spec: dict[str, Any],
        attempt_id: str,
        lease_generation: int,
        attempt_work_dir: str,
        should_cancel_attempt,
    ) -> None:
        nonlocal cancel_seen
        run_active_reconciler_once(
            cfg,
            now="2099-06-07T10:05:00Z",
            retry_delay_seconds=0,
        )
        reclaimed = claim_next_run_job(
            cfg,
            worker_id="worker_reclaim_cancellation",
            now="2099-06-07T10:05:00Z",
            lease_seconds=30,
        )
        assert reclaimed is not None
        assert reclaimed["leaseGeneration"] == lease_generation + 1
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if should_cancel_attempt():
                cancel_seen = True
                return
            time.sleep(0.01)

    monkeypatch.setattr(run_worker, "run_snakemake_execution", fake_executor)

    result = process_next_run_job(
        cfg,
        worker_id="worker_stale_cancellation",
        lease_seconds=1,
        heartbeat_interval_seconds=0.01,
        now_factory=clock,
    )

    assert result["claimed"] is True
    assert cancel_seen is True


def test_run_worker_cancellation_callback_observes_cancel_command(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import run_worker

    cfg = _config(tmp_path)
    _create_queued_run(cfg, "run_worker_command_cancel")
    clock = FakeClock()
    cancel_seen = False

    def fake_executor(
        cfg: RemoteRunnerConfig,
        *,
        run_id: str,
        request_id: str,
        run_spec: dict[str, Any],
        attempt_id: str,
        lease_generation: int,
        attempt_work_dir: str,
        should_cancel_attempt,
    ) -> None:
        nonlocal cancel_seen
        assert should_cancel_attempt() is False
        request_run_cancel(
            cfg,
            run_id,
            actor="worker-test",
            command_id="cmd_worker_cancel",
            now="2099-06-07T10:00:05Z",
        )
        cancel_seen = bool(should_cancel_attempt())

    monkeypatch.setattr(run_worker, "run_snakemake_execution", fake_executor)

    result = process_next_run_job(
        cfg,
        worker_id="worker_command_cancel",
        lease_seconds=30,
        heartbeat_interval_seconds=0,
        now_factory=clock,
    )

    assert result["claimed"] is True
    assert cancel_seen is True
