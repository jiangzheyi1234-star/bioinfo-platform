from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from apps.remote_runner import agent_process_lifecycle_storage as lifecycle_storage
from apps.remote_runner.agent_process_lifecycle_storage import (
    AgentProcessLifecycleStorageConflictError,
    fetch_agent_process_lifecycle_for_connection,
    mark_agent_process_exited_for_connection,
    mark_agent_process_lost_for_connection,
    mark_agent_process_spawn_failed_for_connection,
    mark_agent_process_started_for_connection,
    mark_agent_process_terminated_for_connection,
)
from apps.remote_runner.event_contracts import append_run_event_v2
from core.contracts.agent_process_lifecycle import (
    agent_process_incarnation_hash,
    build_windows_process_incarnation,
)
from tests.agent_process_lifecycle_storage_fixtures import (
    FINISHED_AT,
    GATE_TOKEN,
    PROCESS_GROUP_ID,
    PROCESS_PID,
    PROCESS_PLATFORM,
    STARTED_AT,
    digest as _digest,
    incarnation as _incarnation,
    prepare_process as _prepare_process,
    process_db as _base_process_db,
    start_process as _start_process,
)
from tests.test_agent_workspace_proof_storage import RUN_ID, TARGET_ATTEMPT_ID


@pytest.fixture
def process_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[sqlite3.Connection]:
    yield from _base_process_db.__wrapped__(tmp_path, monkeypatch)


def test_started_transition_consumes_gate_and_binds_exact_process_chain(
    process_db: sqlite3.Connection,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-start")

    result = _start_process(process_db, intent)

    assert result["transactionApplied"] is True
    assert result["event"]["eventType"] == "agent_process_started"
    assert result["event"]["payload"] == {
        "attemptId": intent.attemptId,
        "launchSpecHash": intent.launchSpecHash,
        "leaseGeneration": intent.leaseGeneration,
        "priorProcessEventHash": intent.spawnIntentEventHash,
        "priorProcessEventId": intent.spawnIntentEventId,
        "processGroupId": PROCESS_GROUP_ID,
        "processIncarnationHash": result["process"]["processIncarnationHash"],
        "processInstanceId": intent.processInstanceId,
        "processKind": intent.processKind,
        "processOrdinal": intent.processOrdinal,
        "processPid": PROCESS_PID,
    }
    stored = fetch_agent_process_lifecycle_for_connection(
        process_db,
        intent.processInstanceId,
    )
    assert stored == result["process"]
    assert stored["state"] == "started"
    assert stored["processPlatform"] == PROCESS_PLATFORM
    assert stored["processIncarnation"] == _incarnation()


def test_started_exact_replay_is_read_only_and_never_releases_twice(
    process_db: sqlite3.Connection,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-start-replay")
    first = _start_process(process_db, intent)

    process_db.execute("BEGIN IMMEDIATE")
    replay = mark_agent_process_started_for_connection(
        process_db,
        process_instance_id=intent.processInstanceId,
        gate_token=GATE_TOKEN,
        expected_platform=PROCESS_PLATFORM,
        process_pid=PROCESS_PID,
        process_group_id=PROCESS_GROUP_ID,
        process_incarnation=_incarnation(),
        occurred_at="2099-07-22T10:09:00Z",
    )
    process_db.commit()

    assert replay["transactionApplied"] is False
    assert replay["event"]["eventId"] == first["event"]["eventId"]
    assert _event_count(process_db, "agent_process_started") == 1


@pytest.mark.parametrize(
    ("expected_platform", "process_incarnation"),
    [
        (
            "linux",
            {
                "evidenceProfile": "synthetic-test-pid-nonce-v1",
                "nonce": _digest("synthetic-incarnation"),
                "pid": PROCESS_PID,
                "schemaVersion": "h2ometa.synthetic-process-incarnation.v1",
            },
        ),
        ("windows", _incarnation()),
    ],
)
def test_started_rejects_synthetic_or_wrong_platform_incarnation(
    process_db: sqlite3.Connection,
    expected_platform: str,
    process_incarnation: dict[str, object],
) -> None:
    intent = _prepare_process(process_db, f"lifecycle-platform-{expected_platform}")

    process_db.execute("BEGIN IMMEDIATE")
    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_INCARNATION_INVALID",
    ):
        mark_agent_process_started_for_connection(
            process_db,
            process_instance_id=intent.processInstanceId,
            gate_token=GATE_TOKEN,
            expected_platform=expected_platform,
            process_pid=PROCESS_PID,
            process_group_id=PROCESS_GROUP_ID,
            process_incarnation=process_incarnation,
        )
    process_db.rollback()

    assert (
        fetch_agent_process_lifecycle_for_connection(
            process_db,
            intent.processInstanceId,
        )["state"]
        == "prepared"
    )
    assert _event_count(process_db, "agent_process_started") == 0


def test_windows_platform_is_derived_and_preserved_through_terminal_replay(
    process_db: sqlite3.Connection,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-windows-platform")
    process_incarnation = build_windows_process_incarnation(
        pid=PROCESS_PID,
        creation_time_filetime=133713371337,
    )
    process_db.execute("BEGIN IMMEDIATE")
    started = mark_agent_process_started_for_connection(
        process_db,
        process_instance_id=intent.processInstanceId,
        gate_token=GATE_TOKEN,
        expected_platform="windows",
        process_pid=PROCESS_PID,
        process_group_id=PROCESS_PID,
        process_incarnation=process_incarnation,
        occurred_at=STARTED_AT,
    )
    process_db.commit()
    process_db.execute("BEGIN IMMEDIATE")
    exited = mark_agent_process_exited_for_connection(
        process_db,
        process_instance_id=intent.processInstanceId,
        process_incarnation=process_incarnation,
        exit_code=0,
        exit_reason="exit_code",
        occurred_at=FINISHED_AT,
    )
    process_db.commit()
    process_db.execute("BEGIN IMMEDIATE")
    replay = mark_agent_process_exited_for_connection(
        process_db,
        process_instance_id=intent.processInstanceId,
        process_incarnation=process_incarnation,
        exit_code=0,
        exit_reason="exit_code",
    )
    process_db.commit()

    assert started["process"]["processPlatform"] == "windows"
    assert exited["process"]["processPlatform"] == "windows"
    assert replay["process"]["processPlatform"] == "windows"
    assert replay["transactionApplied"] is False


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda db: db.execute(
                "UPDATE runs SET status = 'canceling' WHERE run_id = ?",
                (RUN_ID,),
            ),
            "AGENT_PROCESS_START_AUTHORITY_INVALID",
        ),
        (
            lambda db: db.execute(
                "UPDATE run_attempts SET cancel_requested_at = ? WHERE attempt_id = ?",
                ("2099-07-22T10:00:30Z", TARGET_ATTEMPT_ID),
            ),
            "AGENT_PROCESS_START_AUTHORITY_INVALID",
        ),
        (
            lambda db: db.execute(
                "UPDATE run_jobs SET state = 'queued' WHERE run_id = ?",
                (RUN_ID,),
            ),
            "AGENT_PROCESS_START_AUTHORITY_INVALID",
        ),
        (
            lambda db: db.execute(
                "UPDATE run_leases SET state = 'expired' WHERE run_id = ?",
                (RUN_ID,),
            ),
            "AGENT_PROCESS_START_AUTHORITY_INVALID",
        ),
        (
            lambda db: db.execute(
                "UPDATE runs SET run_spec_json = ? WHERE run_id = ?",
                ('{"pipelineId":"forged"}', RUN_ID),
            ),
            "AGENT_PROCESS_START_AUTHORITY_INVALID",
        ),
    ],
)
def test_started_revalidates_cancel_job_and_lease_authority(
    process_db: sqlite3.Connection,
    mutation: Callable[[sqlite3.Connection], object],
    expected_code: str,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-stale-start")
    mutation(process_db)
    process_db.commit()

    process_db.execute("BEGIN IMMEDIATE")
    with pytest.raises(AgentProcessLifecycleStorageConflictError, match=expected_code):
        mark_agent_process_started_for_connection(
            process_db,
            process_instance_id=intent.processInstanceId,
            gate_token=GATE_TOKEN,
            expected_platform=PROCESS_PLATFORM,
            process_pid=PROCESS_PID,
            process_group_id=PROCESS_GROUP_ID,
            process_incarnation=_incarnation(),
            occurred_at=STARTED_AT,
        )
    process_db.rollback()

    assert (
        fetch_agent_process_lifecycle_for_connection(
            process_db,
            intent.processInstanceId,
        )["state"]
        == "prepared"
    )
    assert _event_count(process_db, "agent_process_started") == 0


def test_gate_token_and_started_replay_conflicts_are_fail_closed(
    process_db: sqlite3.Connection,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-gate-conflict")

    process_db.execute("BEGIN IMMEDIATE")
    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_GATE_TOKEN_MISMATCH",
    ):
        mark_agent_process_started_for_connection(
            process_db,
            process_instance_id=intent.processInstanceId,
            gate_token=b"z" * 32,
            expected_platform=PROCESS_PLATFORM,
            process_pid=PROCESS_PID,
            process_group_id=PROCESS_GROUP_ID,
            process_incarnation=_incarnation(),
        )
    process_db.rollback()
    _start_process(process_db, intent)

    process_db.execute("BEGIN IMMEDIATE")
    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_CONTAINMENT_LEADER_INVALID",
    ):
        mark_agent_process_started_for_connection(
            process_db,
            process_instance_id=intent.processInstanceId,
            gate_token=GATE_TOKEN,
            expected_platform=PROCESS_PLATFORM,
            process_pid=PROCESS_PID,
            process_group_id=9999,
            process_incarnation=_incarnation(),
        )
    process_db.rollback()
    assert _event_count(process_db, "agent_process_started") == 1


def test_spawn_failed_is_atomic_and_exactly_replayable(
    process_db: sqlite3.Connection,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-spawn-failed")
    process_db.execute("BEGIN IMMEDIATE")
    first = mark_agent_process_spawn_failed_for_connection(
        process_db,
        process_instance_id=intent.processInstanceId,
        gate_token=GATE_TOKEN,
        failure_code="PROCESS_CREATE_FAILED",
        occurred_at=FINISHED_AT,
    )
    process_db.commit()

    process_db.execute("BEGIN IMMEDIATE")
    replay = mark_agent_process_spawn_failed_for_connection(
        process_db,
        process_instance_id=intent.processInstanceId,
        gate_token=GATE_TOKEN,
        failure_code="PROCESS_CREATE_FAILED",
    )
    process_db.commit()

    assert first["transactionApplied"] is True
    assert replay["transactionApplied"] is False
    assert replay["event"]["eventId"] == first["event"]["eventId"]
    assert first["process"]["state"] == "spawn_failed"
    assert first["process"]["exitReason"] == "PROCESS_CREATE_FAILED"
    assert _event_count(process_db, "agent_process_spawn_failed") == 1


def test_lifecycle_reasons_are_bounded_and_path_free(
    process_db: sqlite3.Connection,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-reason-enum")
    process_db.execute("BEGIN IMMEDIATE")
    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_FAILURE_CODE_INVALID",
    ):
        mark_agent_process_spawn_failed_for_connection(
            process_db,
            process_instance_id=intent.processInstanceId,
            gate_token=GATE_TOKEN,
            failure_code=r"C:\private\raw-error.txt",
        )
    process_db.rollback()
    _start_process(process_db, intent)

    process_db.execute("BEGIN IMMEDIATE")
    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_EXIT_REASON_INVALID",
    ):
        mark_agent_process_exited_for_connection(
            process_db,
            process_instance_id=intent.processInstanceId,
            process_incarnation=_incarnation(),
            exit_code=1,
            exit_reason=r"C:\private\raw-error.txt",
        )
    process_db.rollback()
    assert (
        fetch_agent_process_lifecycle_for_connection(
            process_db,
            intent.processInstanceId,
        )["state"]
        == "started"
    )


def test_exit_requires_exact_incarnation_but_not_a_live_lease(
    process_db: sqlite3.Connection,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-exit")
    _start_process(process_db, intent)
    process_db.execute(
        "UPDATE runs SET status = 'canceling' WHERE run_id = ?",
        (intent.runId,),
    )
    process_db.execute(
        "UPDATE run_attempts SET state = 'failed', cancel_requested_at = ? "
        "WHERE attempt_id = ?",
        ("2099-07-22T10:01:30Z", intent.attemptId),
    )
    process_db.execute(
        "UPDATE run_jobs SET state = 'completed' WHERE run_id = ?",
        (intent.runId,),
    )
    process_db.execute(
        "UPDATE run_leases SET state = 'released' WHERE run_id = ?",
        (intent.runId,),
    )
    process_db.commit()

    process_db.execute("BEGIN IMMEDIATE")
    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_INCARNATION_MISMATCH",
    ):
        mark_agent_process_exited_for_connection(
            process_db,
            process_instance_id=intent.processInstanceId,
            process_incarnation=_incarnation("pid-reused"),
            exit_code=0,
            exit_reason="exit_code",
        )
    process_db.rollback()

    process_db.execute("BEGIN IMMEDIATE")
    exited = mark_agent_process_exited_for_connection(
        process_db,
        process_instance_id=intent.processInstanceId,
        process_incarnation=_incarnation(),
        exit_code=0,
        exit_reason="exit_code",
        occurred_at=FINISHED_AT,
    )
    process_db.commit()

    assert exited["transactionApplied"] is True
    assert exited["process"]["processPlatform"] == PROCESS_PLATFORM
    assert exited["process"]["state"] == "exited"
    assert (
        exited["event"]["payload"]["priorProcessEventId"]
        == exited["process"]["startedEventId"]
    )


def test_terminal_process_chain_allows_intervening_global_events(
    process_db: sqlite3.Connection,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-interleaved-exit")
    started = _start_process(process_db, intent)
    run = process_db.execute(
        "SELECT state_version, request_id FROM runs WHERE run_id = ?",
        (intent.runId,),
    ).fetchone()
    process_db.execute("BEGIN IMMEDIATE")
    interleaved = append_run_event_v2(
        process_db,
        run_id=intent.runId,
        event_type="run_progress_observed",
        stage="running",
        state_version=int(run["state_version"]),
        message="Progress observed between process lifecycle events.",
        request_id=str(run["request_id"]),
        payload={"progress": 50},
        actor="remote-runner",
        occurred_at="2099-07-22T10:01:30Z",
    )
    process_db.commit()

    process_db.execute("BEGIN IMMEDIATE")
    exited = mark_agent_process_exited_for_connection(
        process_db,
        process_instance_id=intent.processInstanceId,
        process_incarnation=_incarnation(),
        exit_code=0,
        exit_reason="exit_code",
        occurred_at=FINISHED_AT,
    )
    process_db.commit()

    terminal = process_db.execute(
        "SELECT seq, prev_event_hash FROM run_events WHERE event_id = ?",
        (exited["event"]["eventId"],),
    ).fetchone()
    assert terminal["prev_event_hash"] == interleaved["event_hash"]
    assert terminal["seq"] == int(interleaved["sequence"]) + 1
    assert (
        exited["event"]["payload"]["priorProcessEventId"] == started["event"]["eventId"]
    )


@pytest.mark.parametrize(
    ("state", "transition"),
    [
        ("terminated", mark_agent_process_terminated_for_connection),
        ("lost", mark_agent_process_lost_for_connection),
    ],
)
def test_stopped_transitions_bind_evidence_and_replay_exactly(
    process_db: sqlite3.Connection,
    state: str,
    transition: Callable[..., dict[str, object]],
) -> None:
    intent = _prepare_process(process_db, f"lifecycle-{state}")
    _start_process(process_db, intent)
    evidence_hash = _digest(f"{state}-evidence")

    process_db.execute("BEGIN IMMEDIATE")
    first = transition(
        process_db,
        process_instance_id=intent.processInstanceId,
        process_incarnation=_incarnation(),
        exit_reason=(
            "reconciler_terminated" if state == "terminated" else "controller_lost"
        ),
        evidence_hash=evidence_hash,
        occurred_at=FINISHED_AT,
    )
    process_db.commit()
    process_db.execute("BEGIN IMMEDIATE")
    replay = transition(
        process_db,
        process_instance_id=intent.processInstanceId,
        process_incarnation=_incarnation(),
        exit_reason=(
            "reconciler_terminated" if state == "terminated" else "controller_lost"
        ),
        evidence_hash=evidence_hash,
    )
    process_db.commit()

    assert first["transactionApplied"] is True
    assert replay["transactionApplied"] is False
    assert first["process"]["processPlatform"] == PROCESS_PLATFORM
    assert first["process"]["state"] == state
    assert first["process"]["terminalEvidenceHash"] == evidence_hash
    assert first["event"]["payload"]["evidenceHash"] == evidence_hash


def test_schema_readiness_rejects_late_trigger_before_event(
    process_db: sqlite3.Connection,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-trigger-rollback")
    process_db.execute(
        """
        CREATE TRIGGER lifecycle_test_reject_start
        BEFORE UPDATE ON agent_process_instances
        WHEN NEW.process_instance_id = OLD.process_instance_id
          AND NEW.state = 'started'
        BEGIN
            SELECT RAISE(ABORT, 'LIFECYCLE_TEST_REJECT_START');
        END
        """
    )
    process_db.commit()

    process_db.execute("BEGIN IMMEDIATE")
    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_LIFECYCLE_SCHEMA_INVALID",
    ):
        mark_agent_process_started_for_connection(
            process_db,
            process_instance_id=intent.processInstanceId,
            gate_token=GATE_TOKEN,
            expected_platform=PROCESS_PLATFORM,
            process_pid=PROCESS_PID,
            process_group_id=PROCESS_GROUP_ID,
            process_incarnation=_incarnation(),
            occurred_at=STARTED_AT,
        )
    process_db.commit()

    stored = fetch_agent_process_lifecycle_for_connection(
        process_db,
        intent.processInstanceId,
    )
    assert stored["state"] == "prepared"
    assert _event_count(process_db, "agent_process_started") == 0


@pytest.mark.parametrize(
    "mutation",
    ["extra_payload", "wrong_pid", "wrong_prior_hash", "wrong_stage", "wrong_actor"],
)
def test_v23_trigger_rejects_forged_started_event_bindings(
    process_db: sqlite3.Connection,
    mutation: str,
) -> None:
    intent = _prepare_process(process_db, f"lifecycle-forged-{mutation}")
    incarnation = _incarnation()
    incarnation_hash = agent_process_incarnation_hash(incarnation)
    payload: dict[str, object] = {
        "attemptId": intent.attemptId,
        "launchSpecHash": intent.launchSpecHash,
        "leaseGeneration": intent.leaseGeneration,
        "priorProcessEventHash": intent.spawnIntentEventHash,
        "priorProcessEventId": intent.spawnIntentEventId,
        "processGroupId": PROCESS_GROUP_ID,
        "processIncarnationHash": incarnation_hash,
        "processInstanceId": intent.processInstanceId,
        "processKind": intent.processKind,
        "processOrdinal": intent.processOrdinal,
        "processPid": PROCESS_PID,
    }
    if mutation == "extra_payload":
        payload["forged"] = True
    elif mutation == "wrong_pid":
        payload["processPid"] = PROCESS_PID + 1
    elif mutation == "wrong_prior_hash":
        payload["priorProcessEventHash"] = "f" * 64
    run = process_db.execute(
        "SELECT state_version, request_id FROM runs WHERE run_id = ?",
        (intent.runId,),
    ).fetchone()
    process_db.execute("BEGIN IMMEDIATE")
    event = append_run_event_v2(
        process_db,
        run_id=intent.runId,
        event_type="agent_process_started",
        stage="process" if mutation == "wrong_stage" else "agent_process",
        state_version=int(run["state_version"]),
        message="Agent process started after authorization commit.",
        request_id=str(run["request_id"]),
        payload=payload,
        actor=None if mutation == "wrong_actor" else "remote-runner",
        occurred_at=STARTED_AT,
    )
    with pytest.raises(
        sqlite3.IntegrityError,
        match="AGENT_PROCESS_INSTANCE_LIFECYCLE_EVENT_INVALID",
    ):
        process_db.execute(
            "UPDATE agent_process_instances SET state = 'started', "
            "process_pid = ?, process_group_id = ?, "
            "process_incarnation_json = ?, process_incarnation_hash = ?, "
            "started_event_id = ?, started_at = ? "
            "WHERE process_instance_id = ?",
            (
                PROCESS_PID,
                PROCESS_GROUP_ID,
                json.dumps(incarnation, separators=(",", ":"), sort_keys=True),
                incarnation_hash,
                event["eventId"],
                STARTED_AT,
                intent.processInstanceId,
            ),
        )
    process_db.rollback()

    assert (
        fetch_agent_process_lifecycle_for_connection(
            process_db,
            intent.processInstanceId,
        )["state"]
        == "prepared"
    )


def test_cas_failure_rolls_back_the_appended_event(
    process_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = _prepare_process(process_db, "lifecycle-cas-rollback")

    def fail_cas(_cursor: sqlite3.Cursor) -> None:
        raise sqlite3.IntegrityError("injected lifecycle CAS failure")

    monkeypatch.setattr(lifecycle_storage, "_require_single_cas", fail_cas)
    process_db.execute("BEGIN IMMEDIATE")
    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_LIFECYCLE_STORAGE_CONFLICT",
    ):
        mark_agent_process_started_for_connection(
            process_db,
            process_instance_id=intent.processInstanceId,
            gate_token=GATE_TOKEN,
            expected_platform=PROCESS_PLATFORM,
            process_pid=PROCESS_PID,
            process_group_id=PROCESS_GROUP_ID,
            process_incarnation=_incarnation(),
            occurred_at=STARTED_AT,
        )
    process_db.commit()

    stored = fetch_agent_process_lifecycle_for_connection(
        process_db,
        intent.processInstanceId,
    )
    assert stored["state"] == "prepared"
    assert _event_count(process_db, "agent_process_started") == 0


def _event_count(connection: sqlite3.Connection, event_type: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM run_events WHERE event_type = ?",
        (event_type,),
    ).fetchone()
    return int(row[0])
