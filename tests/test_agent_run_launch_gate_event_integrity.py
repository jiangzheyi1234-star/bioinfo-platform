from __future__ import annotations

import json
from typing import Any

import pytest

from apps.remote_runner.run_worker import process_next_run_job
from apps.remote_runner.storage_core import get_connection
from tests.test_agent_run_launch_gate import _assert_launch_gate_failure, _authorize


pytest_plugins = ("tests.test_agent_fastq_qc_execution_candidate",)


@pytest.mark.parametrize(
    ("mutation", "failure_component"),
    [
        ("event_hash", "input"),
        ("stage", "input"),
        ("sequence_zero", "authority"),
        ("state_version", "input"),
    ],
)
def test_materialization_event_tamper_is_rejected_before_executor(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    failure_component: str,
) -> None:
    from apps.remote_runner import run_worker

    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    original_gate = run_worker.require_agent_run_launch_authorization
    gate_calls = 0

    def gate_then_tamper_event(*args: Any, **kwargs: Any):
        nonlocal gate_calls
        result = original_gate(*args, **kwargs)
        gate_calls += 1
        if gate_calls == 1 and result is not None:
            _tamper_materialization_event(cfg, run_id=run_id, mutation=mutation)
        return result

    monkeypatch.setattr(
        run_worker,
        "require_agent_run_launch_authorization",
        gate_then_tamper_event,
    )
    result = process_next_run_job(
        cfg,
        worker_id=f"agent-input-event-tamper-{mutation}",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not run after materialization evidence tamper"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == (
        f"AGENT_RUN_LAUNCH_GATE_FAILED: {failure_component}"
    )
    _assert_launch_gate_failure(cfg, run_id)


def _tamper_materialization_event(cfg: Any, *, run_id: str, mutation: str) -> None:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? AND event_type = 'agent_input_materialized'",
            (run_id,),
        ).fetchone()
        assert row is not None
        if mutation == "event_hash":
            connection.execute(
                "UPDATE run_events SET event_hash = ? WHERE event_id = ?",
                ("0" * 64, row["event_id"]),
            )
        elif mutation == "stage":
            connection.execute(
                "UPDATE run_events SET stage = ? WHERE event_id = ?",
                ("tampered-agent-input", row["event_id"]),
            )
        elif mutation == "sequence_zero":
            details = json.loads(row["details_json"])
            details["sequence"] = 0
            connection.execute(
                "UPDATE run_events SET seq = 0, details_json = ? WHERE event_id = ?",
                (
                    json.dumps(details, sort_keys=True, separators=(",", ":")),
                    row["event_id"],
                ),
            )
        elif mutation == "state_version":
            connection.execute(
                "UPDATE run_events SET state_version = state_version + 1 WHERE event_id = ?",
                (row["event_id"],),
            )
        else:
            raise AssertionError(mutation)
        connection.commit()
