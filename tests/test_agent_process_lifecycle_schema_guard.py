from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.remote_runner.agent_process_instance_v23_schema import (
    AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME,
)
from apps.remote_runner.agent_process_lifecycle_storage import (
    AgentProcessLifecycleStorageConflictError,
    fetch_agent_process_lifecycle_for_connection,
)
from apps.remote_runner.event_contracts import append_run_event_v2
from core.contracts.agent_process_instance import AgentProcessLaunchIntentV1
from tests.agent_process_lifecycle_storage_fixtures import (
    FINISHED_AT,
    PROCESS_GROUP_ID,
    PROCESS_PID,
    STARTED_AT,
    prepare_process,
    process_db as _base_process_db,
    start_process,
)


@pytest.fixture
def process_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[sqlite3.Connection]:
    yield from _base_process_db.__wrapped__(tmp_path, monkeypatch)


LINUX_INCARNATION = {
    "bootId": "01234567-89ab-cdef-0123-456789abcdef",
    "evidenceProfile": "linux-procfs-boot-id-pid-starttime-v1",
    "pid": PROCESS_PID,
    "procStartTicks": 987654321,
    "schemaVersion": "h2ometa.linux-process-incarnation.v1",
}
WINDOWS_INCARNATION = {
    "creationTimeFiletime": "133700000000000000",
    "evidenceProfile": "windows-process-pid-creation-filetime-v1",
    "pid": PROCESS_PID,
    "schemaVersion": "h2ometa.windows-process-incarnation.v1",
}
INVALID_LIFECYCLE_REASONS = (
    pytest.param(
        "spawn_failed",
        r"C:\private\raw-error.txt",
        id="spawn-failed-path",
    ),
    pytest.param(
        "spawn_failed",
        "UNREGISTERED_FAILURE_CODE",
        id="spawn-failed-unregistered-code",
    ),
    pytest.param("exited", r"C:\private\raw-error.txt", id="exited-path"),
    pytest.param(
        "terminated",
        r"C:\private\raw-error.txt",
        id="terminated-path",
    ),
    pytest.param("lost", r"C:\private\raw-error.txt", id="lost-path"),
)


@pytest.mark.parametrize(
    "incarnation",
    [
        LINUX_INCARNATION,
        WINDOWS_INCARNATION,
        {**WINDOWS_INCARNATION, "creationTimeFiletime": "18446744073709551615"},
    ],
    ids=["linux-v1", "windows-v1", "windows-v1-uint64-max"],
)
def test_v23_started_guard_accepts_only_exact_production_shapes(
    process_db: sqlite3.Connection,
    incarnation: dict[str, object],
) -> None:
    intent = prepare_process(process_db, f"schema-valid-{incarnation['pid']}")

    _apply_raw_started_update(process_db, intent, incarnation)
    process_db.commit()

    stored = process_db.execute(
        "SELECT state, process_incarnation_json "
        "FROM agent_process_instances WHERE process_instance_id = ?",
        (intent.processInstanceId,),
    ).fetchone()
    assert tuple(stored) == ("started", _stable_json(incarnation))


@pytest.mark.parametrize(
    ("case", "incarnation"),
    [
        (
            "synthetic-profile",
            {
                "evidenceProfile": "synthetic-test-pid-nonce-v1",
                "nonce": "a" * 64,
                "pid": PROCESS_PID,
                "schemaVersion": "h2ometa.synthetic-process-incarnation.v1",
            },
        ),
        ("empty-object", {}),
        ("wrong-pid", {**LINUX_INCARNATION, "pid": PROCESS_PID + 1}),
        ("linux-extra-field", {**LINUX_INCARNATION, "forged": True}),
        (
            "linux-uppercase-boot-id",
            {
                **LINUX_INCARNATION,
                "bootId": "01234567-89AB-cdef-0123-456789abcdef",
            },
        ),
        ("linux-zero-start-ticks", {**LINUX_INCARNATION, "procStartTicks": 0}),
        (
            "windows-leading-zero-filetime",
            {**WINDOWS_INCARNATION, "creationTimeFiletime": "0133700000000000000"},
        ),
        (
            "windows-zero-filetime",
            {**WINDOWS_INCARNATION, "creationTimeFiletime": "0"},
        ),
        (
            "windows-integer-filetime",
            {**WINDOWS_INCARNATION, "creationTimeFiletime": 133700000000000000},
        ),
        (
            "windows-overflow-filetime",
            {**WINDOWS_INCARNATION, "creationTimeFiletime": "18446744073709551616"},
        ),
    ],
)
def test_v23_started_guard_rejects_raw_sql_incarnation_forgery(
    process_db: sqlite3.Connection,
    case: str,
    incarnation: dict[str, object],
) -> None:
    intent = prepare_process(process_db, f"schema-forged-{case}")

    with pytest.raises(
        sqlite3.IntegrityError,
        match="AGENT_PROCESS_INSTANCE_LIFECYCLE_EVENT_INVALID",
    ):
        _apply_raw_started_update(process_db, intent, incarnation)
    process_db.rollback()

    assert (
        process_db.execute(
            "SELECT state FROM agent_process_instances WHERE process_instance_id = ?",
            (intent.processInstanceId,),
        ).fetchone()[0]
        == "prepared"
    )


def test_v23_started_guard_rejects_raw_sql_process_group_mismatch(
    process_db: sqlite3.Connection,
) -> None:
    intent = prepare_process(process_db, "schema-forged-process-group")

    with pytest.raises(
        sqlite3.IntegrityError,
        match="AGENT_PROCESS_INSTANCE_LIFECYCLE_EVENT_INVALID",
    ):
        _apply_raw_started_update(
            process_db,
            intent,
            LINUX_INCARNATION,
            process_group_id=PROCESS_PID + 1,
        )
    process_db.rollback()

    assert (
        process_db.execute(
            "SELECT state FROM agent_process_instances WHERE process_instance_id = ?",
            (intent.processInstanceId,),
        ).fetchone()[0]
        == "prepared"
    )


@pytest.mark.parametrize(
    ("state", "reason"),
    INVALID_LIFECYCLE_REASONS,
)
def test_v23_terminal_guard_rejects_raw_sql_invalid_reason(
    process_db: sqlite3.Connection,
    state: str,
    reason: str,
) -> None:
    intent = prepare_process(process_db, f"schema-path-reason-{state}")
    expected_state = "prepared"
    if state != "spawn_failed":
        start_process(process_db, intent)
        expected_state = "started"

    with pytest.raises(
        sqlite3.IntegrityError,
        match="AGENT_PROCESS_INSTANCE_LIFECYCLE_EVENT_INVALID",
    ):
        _apply_raw_terminal_update(
            process_db,
            intent,
            state=state,
            reason=reason,
        )
    process_db.rollback()

    assert (
        process_db.execute(
            "SELECT state FROM agent_process_instances WHERE process_instance_id = ?",
            (intent.processInstanceId,),
        ).fetchone()[0]
        == expected_state
    )


@pytest.mark.parametrize(
    ("state", "reason"),
    INVALID_LIFECYCLE_REASONS,
)
def test_lifecycle_read_model_rejects_invalid_reason_without_trigger(
    process_db: sqlite3.Connection,
    state: str,
    reason: str,
) -> None:
    intent = prepare_process(process_db, f"read-model-path-reason-{state}")
    if state != "spawn_failed":
        start_process(process_db, intent)
    process_db.execute(f"DROP TRIGGER {AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME}")
    process_db.commit()

    _apply_raw_terminal_update(
        process_db,
        intent,
        state=state,
        reason=reason,
    )
    process_db.commit()

    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_LIFECYCLE_STORED_PAYLOAD_INVALID",
    ):
        fetch_agent_process_lifecycle_for_connection(
            process_db,
            intent.processInstanceId,
        )


def _apply_raw_started_update(
    connection: sqlite3.Connection,
    intent: AgentProcessLaunchIntentV1,
    incarnation: dict[str, object],
    *,
    process_group_id: int = PROCESS_GROUP_ID,
) -> None:
    # The trigger validates evidence shape, not this digest's SHA-256 derivation.
    # The application read model owns recomputation of the incarnation hash.
    incarnation_hash = "a" * 64
    run = connection.execute(
        "SELECT state_version, request_id FROM runs WHERE run_id = ?",
        (intent.runId,),
    ).fetchone()
    connection.execute("BEGIN IMMEDIATE")
    event = append_run_event_v2(
        connection,
        run_id=intent.runId,
        event_type="agent_process_started",
        stage="agent_process",
        state_version=int(run["state_version"]),
        message="Agent process started after authorization commit.",
        request_id=str(run["request_id"]),
        actor="remote-runner",
        payload={
            "attemptId": intent.attemptId,
            "launchSpecHash": intent.launchSpecHash,
            "leaseGeneration": intent.leaseGeneration,
            "priorProcessEventHash": intent.spawnIntentEventHash,
            "priorProcessEventId": intent.spawnIntentEventId,
            "processGroupId": process_group_id,
            "processIncarnationHash": incarnation_hash,
            "processInstanceId": intent.processInstanceId,
            "processKind": intent.processKind,
            "processOrdinal": intent.processOrdinal,
            "processPid": PROCESS_PID,
        },
        occurred_at=STARTED_AT,
    )
    connection.execute(
        "UPDATE agent_process_instances SET state = 'started', "
        "process_pid = ?, process_group_id = ?, process_incarnation_json = ?, "
        "process_incarnation_hash = ?, started_event_id = ?, started_at = ? "
        "WHERE process_instance_id = ?",
        (
            PROCESS_PID,
            process_group_id,
            _stable_json(incarnation),
            incarnation_hash,
            event["eventId"],
            STARTED_AT,
            intent.processInstanceId,
        ),
    )


def _apply_raw_terminal_update(
    connection: sqlite3.Connection,
    intent: AgentProcessLaunchIntentV1,
    *,
    state: str,
    reason: str,
) -> None:
    row = connection.execute(
        "SELECT * FROM agent_process_instances WHERE process_instance_id = ?",
        (intent.processInstanceId,),
    ).fetchone()
    run = connection.execute(
        "SELECT state_version, request_id FROM runs WHERE run_id = ?",
        (intent.runId,),
    ).fetchone()
    prior_event_id = (
        row["spawn_intent_event_id"]
        if state == "spawn_failed"
        else row["started_event_id"]
    )
    prior_event_hash = connection.execute(
        "SELECT event_hash FROM run_events WHERE event_id = ?",
        (prior_event_id,),
    ).fetchone()[0]
    payload: dict[str, object] = {
        "attemptId": intent.attemptId,
        "launchSpecHash": intent.launchSpecHash,
        "leaseGeneration": intent.leaseGeneration,
        "priorProcessEventHash": prior_event_hash,
        "priorProcessEventId": prior_event_id,
        "processInstanceId": intent.processInstanceId,
        "processKind": intent.processKind,
        "processOrdinal": intent.processOrdinal,
    }
    if state == "spawn_failed":
        payload["failureCode"] = reason
    else:
        payload["exitReason"] = reason
        payload["processIncarnationHash"] = row["process_incarnation_hash"]
        if state == "exited":
            payload["exitCode"] = 1
        else:
            payload["evidenceHash"] = "b" * 64

    event_type = f"agent_process_{state}"
    message = {
        "spawn_failed": "Agent process spawn failed before start.",
        "exited": "Agent process exited and was reaped.",
        "terminated": "Agent process termination confirmed.",
        "lost": "Agent process identity lost.",
    }[state]
    connection.execute("BEGIN IMMEDIATE")
    event = append_run_event_v2(
        connection,
        run_id=intent.runId,
        event_type=event_type,
        stage="agent_process",
        state_version=int(run["state_version"]),
        message=message,
        request_id=str(run["request_id"]),
        actor="remote-runner",
        payload=payload,
        occurred_at=FINISHED_AT,
    )
    connection.execute(
        "UPDATE agent_process_instances SET state = ?, terminal_event_id = ?, "
        "exit_code = ?, exit_reason = ?, finished_at = ? "
        "WHERE process_instance_id = ?",
        (
            state,
            event["eventId"],
            1 if state == "exited" else None,
            reason,
            FINISHED_AT,
            intent.processInstanceId,
        ),
    )


def _stable_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
