from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.tool_prepare_job_storage import create_tool_prepare_job, fetch_tool_prepare_job


def test_run_worker_supervisor_polls_until_stopped(monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    calls: list[dict[str, Any]] = []
    heartbeats: list[dict[str, Any]] = []
    registrations: list[dict[str, Any]] = []
    stopped: list[dict[str, Any]] = []

    def fake_process_next_run_job(
        cfg,
        *,
        worker_id: str,
        heartbeat_interval_seconds: float,
        on_attempt_claimed,
        on_attempt_finished,
    ):
        calls.append(
            {
                "cfg": cfg,
                "workerId": worker_id,
                "heartbeatIntervalSeconds": heartbeat_interval_seconds,
                "hasAttemptClaimedCallback": callable(on_attempt_claimed),
                "hasAttemptFinishedCallback": callable(on_attempt_finished),
            }
        )
        return {"claimed": False}

    monkeypatch.setattr(worker_supervisor, "register_run_worker", lambda _cfg, **kwargs: registrations.append(kwargs))
    monkeypatch.setattr(worker_supervisor, "heartbeat_run_worker", lambda _cfg, **kwargs: heartbeats.append(kwargs))
    monkeypatch.setattr(worker_supervisor, "mark_run_worker_stopped", lambda _cfg, **kwargs: stopped.append(kwargs))
    monkeypatch.setattr(worker_supervisor, "run_worker_is_draining", lambda _cfg, _worker_id: False)
    monkeypatch.setattr(worker_supervisor, "process_next_run_job", fake_process_next_run_job)

    cfg = SimpleNamespace(service_name="test-runner")
    supervisor = worker_supervisor.start_run_worker_supervisor(
        cfg,
        worker_id="worker_test",
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=0.02,
    )
    deadline = time.monotonic() + 1
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)

    supervisor.stop(timeout_seconds=1)

    assert calls
    assert calls[0] == {
        "cfg": cfg,
        "workerId": "worker_test",
        "heartbeatIntervalSeconds": 0.02,
        "hasAttemptClaimedCallback": True,
        "hasAttemptFinishedCallback": True,
    }
    assert registrations[0]["worker_id"] == "worker_test"
    assert heartbeats[0]["state"] == "idle"
    assert stopped[0]["worker_id"] == "worker_test"


def test_run_worker_supervisor_drain_skips_new_claims(monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    heartbeats: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(worker_supervisor, "register_run_worker", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "heartbeat_run_worker", lambda _cfg, **kwargs: heartbeats.append(kwargs))
    monkeypatch.setattr(worker_supervisor, "mark_run_worker_stopped", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "run_worker_is_draining", lambda _cfg, _worker_id: True)
    monkeypatch.setattr(worker_supervisor, "process_next_run_job", lambda *_args, **kwargs: calls.append(kwargs))

    supervisor = worker_supervisor.start_run_worker_supervisor(
        SimpleNamespace(service_name="test-runner"),
        worker_id="worker_draining",
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=0.02,
    )
    deadline = time.monotonic() + 1
    while not heartbeats and time.monotonic() < deadline:
        time.sleep(0.01)

    supervisor.stop(timeout_seconds=1)

    assert calls == []
    assert heartbeats[0]["state"] == "draining"


def test_tool_prepare_worker_supervisor_polls_until_stopped(monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    calls: list[dict[str, Any]] = []

    def fake_process_next_tool_prepare_job(cfg, *, worker_id: str, heartbeat_interval_seconds: float):
        calls.append({"cfg": cfg, "workerId": worker_id, "heartbeatIntervalSeconds": heartbeat_interval_seconds})
        return {"claimed": False}

    monkeypatch.setattr(worker_supervisor, "process_next_tool_prepare_job", fake_process_next_tool_prepare_job)

    cfg = SimpleNamespace(service_name="test-runner")
    supervisor = worker_supervisor.start_tool_prepare_worker_supervisor(
        cfg,
        worker_id="tool-prepare-test",
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=0.02,
    )
    deadline = time.monotonic() + 1
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)

    supervisor.stop(timeout_seconds=1)

    assert calls == [{"cfg": cfg, "workerId": "tool-prepare-test", "heartbeatIntervalSeconds": 0.02}]


def test_process_next_tool_prepare_job_runs_one_queued_job(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    cfg = _config(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    calls: list[str] = []
    monkeypatch.setattr(worker_supervisor, "run_tool_prepare_job", lambda _cfg, job_id: calls.append(job_id))

    result = worker_supervisor.process_next_tool_prepare_job(cfg)

    assert result == {"claimed": True, "jobId": job["jobId"]}
    assert calls == [job["jobId"]]


def test_process_next_tool_prepare_job_requeues_unexpected_worker_error(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    cfg = _config(tmp_path)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})

    def crash(_cfg, _job_id: str) -> None:
        raise RuntimeError("prepare worker crashed")

    monkeypatch.setattr(worker_supervisor, "run_tool_prepare_job", crash)

    result = worker_supervisor.process_next_tool_prepare_job(
        cfg,
        worker_id="prepare-worker-test",
        heartbeat_interval_seconds=0,
        retry_delay_seconds=0,
    )

    assert result == {
        "claimed": True,
        "jobId": job["jobId"],
        "workerError": "prepare worker crashed",
        "retryStatus": "queued",
    }
    refreshed = fetch_tool_prepare_job(cfg, job["jobId"])
    assert refreshed is not None
    assert refreshed["status"] == "queued"
    assert refreshed["stage"] == "retry_wait"
    assert refreshed["lease"]["claimedBy"] == ""
    assert refreshed["lease"]["attempts"] == 1


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
