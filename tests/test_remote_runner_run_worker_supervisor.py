from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.resource_pool import ResourceRequest
from apps.remote_runner.run_execution_storage import claim_next_run_job, request_run_cancel
from apps.remote_runner.run_worker_storage import build_run_worker_health
from apps.remote_runner.storage import create_run_record, fetch_run, update_run_state
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.tool_prepare_job_storage import create_tool_prepare_job, fetch_tool_prepare_job


def test_run_worker_supervisor_polls_until_stopped(monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    calls: list[dict[str, Any]] = []
    reconciliations: list[Any] = []
    heartbeats: list[dict[str, Any]] = []
    registrations: list[dict[str, Any]] = []
    stopped: list[dict[str, Any]] = []

    def fake_process_next_run_job(
        cfg,
        *,
        worker_id: str,
        session_id: str,
        slot_id: str,
        queue_name: str,
        resource_request,
        resource_capacity,
        max_active_slots: int,
        resource_pool,
        heartbeat_interval_seconds: float,
        on_attempt_claimed,
        on_attempt_finished,
    ):
        calls.append(
            {
                "cfg": cfg,
                "workerId": worker_id,
                "sessionId": session_id,
                "slotId": slot_id,
                "queueName": queue_name,
                "resourceRequest": resource_request,
                "resourceCapacity": resource_capacity,
                "maxActiveSlots": max_active_slots,
                "resourcePool": resource_pool,
                "heartbeatIntervalSeconds": heartbeat_interval_seconds,
                "hasAttemptClaimedCallback": callable(on_attempt_claimed),
                "hasAttemptFinishedCallback": callable(on_attempt_finished),
            }
        )
        return {"claimed": False}

    monkeypatch.setattr(worker_supervisor, "register_run_worker", lambda _cfg, **kwargs: registrations.append(kwargs))
    monkeypatch.setattr(worker_supervisor, "register_run_worker_slot", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "heartbeat_run_worker", lambda _cfg, **kwargs: heartbeats.append(kwargs))
    monkeypatch.setattr(worker_supervisor, "mark_run_worker_stopped", lambda _cfg, **kwargs: stopped.append(kwargs))
    monkeypatch.setattr(worker_supervisor, "run_worker_is_draining", lambda _cfg, _worker_id: False)
    monkeypatch.setattr(
        worker_supervisor,
        "run_active_reconciler_once",
        lambda cfg: reconciliations.append(cfg),
    )
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
    assert reconciliations
    assert reconciliations[0] is cfg
    assert calls[0] == {
        "cfg": cfg,
        "workerId": "worker_test",
        "sessionId": registrations[0]["session_id"],
        "slotId": "slot-0",
        "queueName": "default",
        "resourceRequest": calls[0]["resourceRequest"],
        "resourceCapacity": calls[0]["resourceCapacity"],
        "maxActiveSlots": 1,
        "resourcePool": calls[0]["resourcePool"],
        "heartbeatIntervalSeconds": 0.02,
        "hasAttemptClaimedCallback": True,
        "hasAttemptFinishedCallback": True,
    }
    assert calls[0]["resourceRequest"].cpu == 1
    assert calls[0]["resourceCapacity"].cpu == 1
    assert calls[0]["resourcePool"].snapshot()["maxConcurrentTasks"] == 1
    assert registrations[0]["worker_id"] == "worker_test"
    assert heartbeats[0]["state"] == "idle"
    assert stopped[0]["worker_id"] == "worker_test"


def test_run_worker_supervisor_requires_gate_for_two_slots(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    monkeypatch.delenv("H2OMETA_REMOTE_ENABLE_MULTI_SLOT", raising=False)

    with pytest.raises(ValueError, match="P0_3B_MULTI_SLOT_GATE_REQUIRED"):
        worker_supervisor.RunWorkerSupervisor(
            _config(tmp_path, run_worker_slot_count=2, run_worker_total_cpu=2),
            worker_id="worker_gate",
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=0,
            error_backoff_seconds=0.01,
        )


def test_run_worker_supervisor_rejects_more_than_two_slots(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    monkeypatch.setenv("H2OMETA_REMOTE_ENABLE_MULTI_SLOT", "1")

    with pytest.raises(ValueError, match="P0_3B_MAX_TWO_SLOTS"):
        worker_supervisor.RunWorkerSupervisor(
            _config(tmp_path, run_worker_slot_count=3, run_worker_total_cpu=3),
            worker_id="worker_too_many",
            poll_interval_seconds=0.01,
            heartbeat_interval_seconds=0,
            error_backoff_seconds=0.01,
        )


def test_two_slot_supervisor_uses_shared_capacity_plan(monkeypatch, tmp_path: Path) -> None:
    from apps.remote_runner import worker_supervisor

    calls: list[dict[str, Any]] = []
    registrations: list[dict[str, Any]] = []

    def fake_process_next_run_job(_cfg, **kwargs):
        calls.append(kwargs)
        return {"claimed": False}

    monkeypatch.setenv("H2OMETA_REMOTE_ENABLE_MULTI_SLOT", "1")
    monkeypatch.setattr(worker_supervisor, "register_run_worker", lambda _cfg, **kwargs: registrations.append(kwargs))
    monkeypatch.setattr(worker_supervisor, "register_run_worker_slot", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "heartbeat_run_worker", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "heartbeat_run_worker_slot", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "mark_run_worker_stopped", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "run_worker_is_draining", lambda _cfg, _worker_id: False)
    monkeypatch.setattr(worker_supervisor, "run_active_reconciler_once", lambda _cfg: None)
    monkeypatch.setattr(worker_supervisor, "process_next_run_job", fake_process_next_run_job)

    cfg = _config(tmp_path, run_worker_slot_count=2, run_worker_total_cpu=2)
    supervisor = worker_supervisor.start_run_worker_supervisor(
        cfg,
        worker_id="worker_two_slot_plan",
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=0,
    )
    deadline = time.monotonic() + 1
    while {call["slot_id"] for call in calls} != {"slot-0", "slot-1"} and time.monotonic() < deadline:
        time.sleep(0.01)

    supervisor.stop(timeout_seconds=1)

    assert registrations[0]["concurrency_limit"] == 2
    assert {call["slot_id"] for call in calls} == {"slot-0", "slot-1"}
    resource_pools = {id(call["resource_pool"]) for call in calls}
    assert len(resource_pools) == 1
    for call in calls:
        assert call["max_active_slots"] == 2
        assert call["resource_request"].cpu == 1
        assert call["resource_capacity"].cpu == 2
        assert call["resource_pool"].snapshot()["maxConcurrentTasks"] == 2


def test_two_slot_supervisor_runs_two_attempts_and_leaves_third_waiting(monkeypatch, tmp_path: Path) -> None:
    from apps.remote_runner import executor, worker_supervisor

    cfg = _config(tmp_path, run_worker_slot_count=2, run_worker_total_cpu=2)
    run_ids = [_create_queued_run(cfg, f"run_two_slot_{index}") for index in range(3)]
    started: dict[str, dict[str, Any]] = {}
    started_lock = threading.Lock()
    both_started = threading.Event()
    release_attempts = threading.Event()

    def fake_workflow(
        cfg: RemoteRunnerConfig,
        *,
        run_id: str,
        request_id: str,
        attempt_id: str,
        lease_generation: int,
        **_kwargs: Any,
    ) -> None:
        with started_lock:
            started[run_id] = {"attemptId": attempt_id, "leaseGeneration": lease_generation}
            if len(started) == 2:
                both_started.set()
        assert release_attempts.wait(timeout=2)
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Fake concurrent workflow completed.",
            request_id=request_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )

    monkeypatch.setenv("H2OMETA_REMOTE_ENABLE_MULTI_SLOT", "1")
    monkeypatch.setattr(executor, "_execute_snakemake_workflow", fake_workflow)

    supervisor = worker_supervisor.start_run_worker_supervisor(
        cfg,
        worker_id="worker_two_slot",
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=0,
    )
    try:
        assert both_started.wait(timeout=2)
        running_ids = set(started)
        waiting_id = next(run_id for run_id in run_ids if run_id not in running_ids)
        blocked = claim_next_run_job(
            cfg,
            worker_id="worker_probe",
            session_id="session_probe",
            slot_id="slot-probe",
            resource_request=ResourceRequest(cpu=1),
            resource_capacity=ResourceRequest(cpu=2),
            max_active_slots=2,
            now="2099-06-07T10:00:00Z",
            lease_seconds=30,
        )
        health = build_run_worker_health(cfg)
        with get_connection(cfg) as connection:
            waiting_job = connection.execute(
                "SELECT wait_reason_json FROM run_jobs WHERE run_id = ?",
                (waiting_id,),
            ).fetchone()
            active_allocations = connection.execute(
                "SELECT COUNT(*) AS count FROM run_resource_allocations WHERE state = 'allocated'",
            ).fetchone()["count"]

        assert blocked is None
        assert health["summary"]["runningSlots"] == 2
        assert active_allocations == 2
        assert waiting_job is not None
        assert "ADMISSION_SLOT_UNAVAILABLE" in waiting_job["wait_reason_json"]
    finally:
        supervisor._stop_event.set()
        release_attempts.set()
        supervisor.stop(timeout_seconds=2)

    completed = [fetch_run(cfg, run_id)["status"] for run_id in running_ids]
    assert completed == ["completed", "completed"]


def test_two_slot_supervisor_cancel_isolation(monkeypatch, tmp_path: Path) -> None:
    from apps.remote_runner import executor, worker_supervisor

    cfg = _config(tmp_path, run_worker_slot_count=2, run_worker_total_cpu=2)
    run_ids = [_create_queued_run(cfg, f"run_cancel_isolation_{index}") for index in range(2)]
    started_order: list[str] = []
    started_lock = threading.Lock()
    both_started = threading.Event()
    cancel_issued = threading.Event()
    target_cancel_seen = threading.Event()
    other_completed = threading.Event()
    cancel_target = {"runId": ""}

    def fake_workflow(
        cfg: RemoteRunnerConfig,
        *,
        run_id: str,
        request_id: str,
        attempt_id: str,
        lease_generation: int,
        should_cancel_attempt,
        **_kwargs: Any,
    ) -> None:
        with started_lock:
            started_order.append(run_id)
            if len(started_order) == 2:
                both_started.set()
        assert cancel_issued.wait(timeout=2)
        if run_id == cancel_target["runId"]:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if should_cancel_attempt():
                    target_cancel_seen.set()
                    return
                time.sleep(0.01)
            raise AssertionError("target attempt did not observe cancellation")
        assert should_cancel_attempt() is False
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Fake sibling workflow completed.",
            request_id=request_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )
        other_completed.set()

    monkeypatch.setenv("H2OMETA_REMOTE_ENABLE_MULTI_SLOT", "1")
    monkeypatch.setattr(executor, "_execute_snakemake_workflow", fake_workflow)

    supervisor = worker_supervisor.start_run_worker_supervisor(
        cfg,
        worker_id="worker_cancel_isolation",
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=0,
    )
    try:
        assert both_started.wait(timeout=2)
        cancel_target["runId"] = started_order[0]
        other_run_id = next(run_id for run_id in run_ids if run_id != cancel_target["runId"])
        cancel = request_run_cancel(
            cfg,
            cancel_target["runId"],
            actor="worker-supervisor-test",
            command_id="cmd_cancel_isolation",
            now="2099-06-07T10:00:05Z",
        )
        cancel_issued.set()
        assert cancel["attemptId"]
        assert target_cancel_seen.wait(timeout=2)
        assert other_completed.wait(timeout=2)
    finally:
        supervisor._stop_event.set()
        cancel_issued.set()
        supervisor.stop(timeout_seconds=2)

    with get_connection(cfg) as connection:
        attempts = {
            row["run_id"]: row["cancel_requested_at"]
            for row in connection.execute(
                "SELECT run_id, cancel_requested_at FROM run_attempts WHERE run_id IN (?, ?)",
                tuple(run_ids),
            ).fetchall()
        }
        active_allocations = connection.execute(
            "SELECT COUNT(*) AS count FROM run_resource_allocations WHERE state = 'allocated'",
        ).fetchone()["count"]

    assert attempts[cancel_target["runId"]] == "2099-06-07T10:00:05Z"
    assert attempts[other_run_id] is None
    assert fetch_run(cfg, other_run_id)["status"] == "completed"
    assert active_allocations == 0


def test_run_worker_supervisor_drain_skips_new_claims(monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    heartbeats: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    reconciliations: list[Any] = []

    monkeypatch.setattr(worker_supervisor, "register_run_worker", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "register_run_worker_slot", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "heartbeat_run_worker", lambda _cfg, **kwargs: heartbeats.append(kwargs))
    monkeypatch.setattr(worker_supervisor, "mark_run_worker_stopped", lambda _cfg, **_kwargs: {})
    monkeypatch.setattr(worker_supervisor, "run_worker_is_draining", lambda _cfg, _worker_id: True)
    monkeypatch.setattr(
        worker_supervisor,
        "run_active_reconciler_once",
        lambda cfg: reconciliations.append(cfg),
    )
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
    assert reconciliations
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


def _create_queued_run(cfg: RemoteRunnerConfig, run_id: str) -> str:
    created = create_run_record(
        cfg,
        server_id="srv_worker_supervisor",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_worker_supervisor",
            "pipelineId": "pipeline_worker_supervisor",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"payload_{run_id}",
    )
    return created.run["runId"]


def _config(tmp_path: Path, **overrides: Any) -> RemoteRunnerConfig:
    (tmp_path / "release" / "snakemake_wrappers").mkdir(parents=True)
    values: dict[str, Any] = {
        "token": "phase2-token",
        "data_root": str(tmp_path / "shared"),
        "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
        "uploads_dir": str(tmp_path / "shared" / "uploads"),
        "results_dir": str(tmp_path / "shared" / "results"),
        "work_dir": str(tmp_path / "shared" / "work"),
        "logs_dir": str(tmp_path / "shared" / "logs"),
        "release_dir": str(tmp_path / "release"),
        "managed_conda_command": "python",
        "snakemake_command": "snakemake",
    }
    values.update(overrides)
    return RemoteRunnerConfig(
        **values,
    )
