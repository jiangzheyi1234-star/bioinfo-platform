from __future__ import annotations

from pathlib import Path
import threading
import time

import pytest

from apps.remote_runner import executor_paths
from apps.remote_runner import execution_attempt_authority
from apps.remote_runner import run_execution_storage
from apps.remote_runner.execution_lease_time import execution_lease_expiry_is_future
from apps.remote_runner.run_execution_storage import (
    claim_next_run_job,
    complete_run_attempt,
    heartbeat_run_attempt,
    record_run_attempt_process_group,
    run_attempt_cancel_requested,
)
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.run_worker import process_next_run_job
from apps.remote_runner.workflow_run_storage import (
    StaleRunAttemptError,
    update_run_state,
)
from tests.helpers.reference_database import make_configured_remote_runner


@pytest.mark.parametrize(
    ("expires_at", "observed_at", "expected"),
    [
        ("2099-06-07T10:00:01Z", "2099-06-07T10:00:00Z", True),
        ("2099-06-07T10:00:00Z", "2099-06-07T10:00:00Z", False),
        ("2099-06-07T09:59:59Z", "2099-06-07T10:00:00Z", False),
        ("2099-02-29T10:00:00Z", "2099-01-01T00:00:00Z", False),
        ("2099-6-07T10:00:00Z", "2099-01-01T00:00:00Z", False),
        ("2099-06-07T10:00:00+00:00", "2099-01-01T00:00:00Z", False),
        (True, "2099-01-01T00:00:00Z", False),
        ("2099-06-07T10:00:00Z", "invalid", False),
    ],
)
def test_execution_lease_comparison_is_strict_utc_seconds(
    expires_at: object,
    observed_at: object,
    expected: bool,
) -> None:
    assert (
        execution_lease_expiry_is_future(expires_at, observed_at=observed_at)
        is expected
    )


def test_expired_active_lease_cannot_be_revived_publish_or_record_process(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    created = create_run_record(
        cfg,
        server_id="lease-expiry-test",
        request_id="req-lease-expiry-test",
        run_spec={
            "projectId": "proj_lease",
            "pipelineId": "pipeline_lease",
            "pipelineVersion": "1.0.0",
        },
        idempotency_key="idem-lease-expiry-test",
        payload_hash="hash-lease-expiry-test",
    )
    run_id = created.run["runId"]
    claim = claim_next_run_job(
        cfg,
        worker_id="lease-expiry-worker",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    attempt_id = claim["attemptId"]
    generation = claim["leaseGeneration"]

    heartbeat = heartbeat_run_attempt(
        cfg,
        attempt_id,
        lease_generation=generation,
        now="2099-06-07T10:00:10Z",
        lease_seconds=60,
    )
    process_group = record_run_attempt_process_group(
        cfg,
        attempt_id,
        lease_generation=generation,
        process_group_id="4321",
        now="2099-06-07T10:00:10Z",
    )

    assert heartbeat == {"accepted": False, "reason": "lease_expired"}
    assert process_group == {"accepted": False, "reason": "lease_expired"}
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE run_leases SET expires_at = '2000-01-01T00:00:00Z' "
            "WHERE run_id = ?",
            (run_id,),
        )
        connection.commit()
    with pytest.raises(StaleRunAttemptError, match="RUN_ATTEMPT_STALE"):
        update_run_state(
            cfg,
            run_id=run_id,
            status="running",
            stage="validate",
            message="must not publish",
            request_id="req-lease-expiry-test",
            attempt_id=attempt_id,
            lease_generation=generation,
        )
    completion = complete_run_attempt(
        cfg,
        attempt_id,
        lease_generation=generation,
        state="failed",
        now="2099-06-07T10:00:10Z",
    )
    assert completion == {"accepted": False, "reason": "lease_expired"}
    repeated_completion = complete_run_attempt(
        cfg,
        attempt_id,
        lease_generation=generation,
        state="failed",
        now="2099-06-07T10:00:11Z",
    )
    assert repeated_completion == {
        "accepted": False,
        "reason": "stale_generation",
    }

    with get_connection(cfg) as connection:
        lease = connection.execute(
            "SELECT expires_at, state FROM run_leases WHERE run_id = ?", (run_id,)
        ).fetchone()
        fence_events = connection.execute(
            "SELECT COUNT(*) FROM run_events "
            "WHERE run_id = ? AND event_type = 'run_attempt_fenced'",
            (run_id,),
        ).fetchone()[0]
    assert dict(lease) == {
        "expires_at": "2000-01-01T00:00:00Z",
        "state": "expired",
    }
    assert fence_events == 1


def test_cancel_poll_treats_time_expired_active_lease_as_cancelled(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    created = create_run_record(
        cfg,
        server_id="lease-cancel-test",
        request_id="req-lease-cancel-test",
        run_spec={"projectId": "proj", "pipelineId": "pipeline"},
        idempotency_key="idem-lease-cancel-test",
        payload_hash="hash-lease-cancel-test",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="lease-cancel-worker",
        now="2099-06-07T10:00:00Z",
        lease_seconds=10,
    )
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE run_leases SET expires_at = '2000-01-01T00:00:00Z' "
            "WHERE run_id = ?",
            (created.run["runId"],),
        )
        connection.commit()

    assert run_attempt_cancel_requested(
        cfg,
        claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
    )


def test_process_group_recorder_raises_when_authority_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        executor_paths,
        "record_run_attempt_process_group",
        lambda *_args, **_kwargs: {"accepted": False, "reason": "lease_expired"},
    )
    recorder = executor_paths._process_group_recorder(
        object(), attempt_id="att_0123456789ab", lease_generation=1
    )

    assert recorder is not None
    with pytest.raises(StaleRunAttemptError, match="RUN_ATTEMPT_STALE"):
        recorder(4321)


def test_invalid_execution_timestamps_are_rejected_before_any_mutation(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    created = create_run_record(
        cfg,
        server_id="invalid-execution-time-test",
        request_id="req-invalid-execution-time-test",
        run_spec={"projectId": "proj", "pipelineId": "pipeline"},
        idempotency_key="idem-invalid-execution-time-test",
        payload_hash="hash-invalid-execution-time-test",
    )

    with pytest.raises(ValueError, match="EXECUTION_TIMESTAMP_INVALID"):
        claim_next_run_job(
            cfg,
            worker_id="invalid-claim-time-worker",
            now="2099-06-07T10:00:00+00:00",
        )
    with get_connection(cfg) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM run_attempts").fetchone()[0] == 0
        )

    claim = claim_next_run_job(
        cfg,
        worker_id="invalid-mutation-time-worker",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    attempt_id = claim["attemptId"]
    generation = claim["leaseGeneration"]

    with get_connection(cfg) as connection:
        before_attempt = dict(
            connection.execute(
                "SELECT state, process_group_id, process_pid, updated_at "
                "FROM run_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        )
        before_lease = dict(
            connection.execute(
                "SELECT state, heartbeat_at, expires_at, updated_at "
                "FROM run_leases WHERE run_id = ?",
                (created.run["runId"],),
            ).fetchone()
        )
        before_events = connection.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id = ?",
            (created.run["runId"],),
        ).fetchone()[0]

    for mutation in (
        lambda: heartbeat_run_attempt(
            cfg,
            attempt_id,
            lease_generation=generation,
            now="invalid",
        ),
        lambda: record_run_attempt_process_group(
            cfg,
            attempt_id,
            lease_generation=generation,
            process_group_id="4321",
            now="2099-6-07T10:00:01Z",
        ),
        lambda: complete_run_attempt(
            cfg,
            attempt_id,
            lease_generation=generation,
            state="failed",
            now="2099-06-07T10:00:01+00:00",
        ),
    ):
        with pytest.raises(ValueError, match="EXECUTION_TIMESTAMP_INVALID"):
            mutation()

    with get_connection(cfg) as connection:
        after_attempt = dict(
            connection.execute(
                "SELECT state, process_group_id, process_pid, updated_at "
                "FROM run_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        )
        after_lease = dict(
            connection.execute(
                "SELECT state, heartbeat_at, expires_at, updated_at "
                "FROM run_leases WHERE run_id = ?",
                (created.run["runId"],),
            ).fetchone()
        )
        after_events = connection.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id = ?",
            (created.run["runId"],),
        ).fetchone()[0]
    assert after_attempt == before_attempt
    assert after_lease == before_lease
    assert after_events == before_events


def test_conditional_mutations_reject_authority_drift_even_after_guard_accepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    created = create_run_record(
        cfg,
        server_id="conditional-lease-fence-test",
        request_id="req-conditional-lease-fence-test",
        run_spec={"projectId": "proj", "pipelineId": "pipeline"},
        idempotency_key="idem-conditional-lease-fence-test",
        payload_hash="hash-conditional-lease-fence-test",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="conditional-lease-fence-worker",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    attempt_id = claim["attemptId"]
    generation = claim["leaseGeneration"]
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE run_jobs SET state = 'queued' WHERE job_id = ?",
            (claim["jobId"],),
        )
        connection.commit()

    accepted_guard = type(
        "AcceptedGuard",
        (),
        {"accepted": True, "reason": "current"},
    )()
    monkeypatch.setattr(
        execution_attempt_authority,
        "current_attempt_lease_guard",
        lambda *_args, **_kwargs: accepted_guard,
    )
    monkeypatch.setattr(
        run_execution_storage,
        "_current_lease_guard",
        lambda *_args, **_kwargs: accepted_guard,
    )

    assert heartbeat_run_attempt(
        cfg,
        attempt_id,
        lease_generation=generation,
        now="2099-06-07T10:00:01Z",
    ) == {"accepted": False, "reason": "stale_generation"}
    assert record_run_attempt_process_group(
        cfg,
        attempt_id,
        lease_generation=generation,
        process_group_id="4321",
        now="2099-06-07T10:00:01Z",
    ) == {"accepted": False, "reason": "stale_generation"}
    assert complete_run_attempt(
        cfg,
        attempt_id,
        lease_generation=generation,
        state="failed",
        now="2099-06-07T10:00:01Z",
    ) == {"accepted": False, "reason": "stale_generation"}

    with get_connection(cfg) as connection:
        attempt = dict(
            connection.execute(
                "SELECT state, process_group_id, process_pid FROM run_attempts "
                "WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        )
        lease = dict(
            connection.execute(
                "SELECT state, heartbeat_at, expires_at FROM run_leases "
                "WHERE run_id = ?",
                (created.run["runId"],),
            ).fetchone()
        )
        job_state = connection.execute(
            "SELECT state FROM run_jobs WHERE job_id = ?", (claim["jobId"],)
        ).fetchone()[0]
        completion_events = connection.execute(
            "SELECT COUNT(*) FROM run_events "
            "WHERE run_id = ? AND event_type = 'run_attempt_completed'",
            (created.run["runId"],),
        ).fetchone()[0]
    assert attempt == {
        "state": "running",
        "process_group_id": None,
        "process_pid": None,
    }
    assert lease == {
        "state": "active",
        "heartbeat_at": "2099-06-07T10:00:00Z",
        "expires_at": "2099-06-07T10:00:30Z",
    }
    assert job_state == "queued"
    assert completion_events == 0


def test_rejected_initial_heartbeat_never_enters_custom_executor(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    create_run_record(
        cfg,
        server_id="initial-heartbeat-fence-test",
        request_id="req-initial-heartbeat-fence-test",
        run_spec={"projectId": "proj", "pipelineId": "pipeline"},
        idempotency_key="idem-initial-heartbeat-fence-test",
        payload_hash="hash-initial-heartbeat-fence-test",
    )
    times = iter(
        (
            "2099-06-07T10:00:00Z",
            "2099-06-07T10:00:10Z",
            "2099-06-07T10:00:11Z",
        )
    )

    result = process_next_run_job(
        cfg,
        worker_id="initial-heartbeat-fence-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "custom executor must not run after the initial heartbeat is rejected"
        ),
        lease_seconds=10,
        heartbeat_interval_seconds=0,
        now_factory=lambda: next(times),
    )

    assert result["heartbeat"] == {"accepted": False, "reason": "lease_expired"}
    assert result["executionError"] == "RUN_ATTEMPT_STALE"
    assert result["attemptCompletion"] == {
        "accepted": False,
        "reason": "lease_expired",
    }


def test_writer_lock_wait_cannot_resurrect_a_lease_that_expires_while_waiting(
    tmp_path: Path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    created = create_run_record(
        cfg,
        server_id="lock-wait-expiry-test",
        request_id="req-lock-wait-expiry-test",
        run_spec={"projectId": "proj", "pipelineId": "pipeline"},
        idempotency_key="idem-lock-wait-expiry-test",
        payload_hash="hash-lock-wait-expiry-test",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="lock-wait-expiry-worker",
        lease_seconds=1,
    )
    assert claim is not None
    attempt_id = claim["attemptId"]
    generation = claim["leaseGeneration"]
    before = dict(claim["lease"])
    outcome: dict[str, object] = {}
    errors: list[BaseException] = []
    started = threading.Event()

    def heartbeat_after_wait() -> None:
        started.set()
        try:
            outcome.update(
                heartbeat_run_attempt(
                    cfg,
                    attempt_id,
                    lease_generation=generation,
                    lease_seconds=30,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    with get_connection(cfg) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        thread = threading.Thread(target=heartbeat_after_wait)
        thread.start()
        assert started.wait(timeout=1)
        time.sleep(2.1)
        blocker.rollback()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == []
    assert outcome == {"accepted": False, "reason": "lease_expired"}
    with get_connection(cfg) as connection:
        lease = dict(
            connection.execute(
                "SELECT heartbeat_at AS heartbeatAt, expires_at AS expiresAt, "
                "state FROM run_leases WHERE run_id = ?",
                (created.run["runId"],),
            ).fetchone()
        )
    assert lease == {
        "heartbeatAt": before["heartbeatAt"],
        "expiresAt": before["expiresAt"],
        "state": "active",
    }
