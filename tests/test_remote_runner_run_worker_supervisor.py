from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any


def test_run_worker_supervisor_polls_until_stopped(monkeypatch) -> None:
    from apps.remote_runner import worker_supervisor

    calls: list[dict[str, Any]] = []

    def fake_process_next_run_job(cfg, *, worker_id: str, heartbeat_interval_seconds: float):
        calls.append(
            {
                "cfg": cfg,
                "workerId": worker_id,
                "heartbeatIntervalSeconds": heartbeat_interval_seconds,
            }
        )
        return {"claimed": False}

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
    }
