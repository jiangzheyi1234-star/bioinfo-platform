from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from apps.remote_runner import agent_process_start_commit as start_commit
from apps.remote_runner.agent_process_lifecycle_storage import (
    AgentProcessLifecycleStorageConflictError,
    fetch_agent_process_lifecycle_for_connection,
)
from tests.agent_process_lifecycle_storage_fixtures import (
    GATE_TOKEN,
    PROCESS_GROUP_ID,
    PROCESS_PID,
    PROCESS_PLATFORM,
    STARTED_AT,
    incarnation,
    prepare_process,
    process_db as _base_process_db,
)


@pytest.fixture
def process_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[sqlite3.Connection]:
    yield from _base_process_db.__wrapped__(tmp_path, monkeypatch)


def test_commit_wrapper_releases_only_after_first_durable_start(
    process_db: sqlite3.Connection,
) -> None:
    intent = prepare_process(process_db, "start-commit-release")
    release_transaction_states: list[bool] = []

    first = _commit_start(
        process_db,
        intent.processInstanceId,
        lambda: release_transaction_states.append(process_db.in_transaction),
    )
    replay = _commit_start(
        process_db,
        intent.processInstanceId,
        lambda: release_transaction_states.append(True),
    )

    assert first["durableTransitionApplied"] is True
    assert first["gateReleased"] is True
    assert replay["durableTransitionApplied"] is False
    assert replay["gateReleased"] is False
    assert release_transaction_states == [False]
    assert replay["event"]["eventId"] == first["event"]["eventId"]


def test_commit_failure_rolls_back_and_never_releases(
    process_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = prepare_process(process_db, "start-commit-failure")
    releases: list[str] = []

    def reject_commit(_connection: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("injected commit failure")

    monkeypatch.setattr(start_commit, "_commit", reject_commit)
    with pytest.raises(sqlite3.OperationalError, match="injected commit failure"):
        _commit_start(
            process_db,
            intent.processInstanceId,
            lambda: releases.append("released"),
        )

    assert releases == []
    assert process_db.in_transaction is False
    assert _stored_state(process_db, intent.processInstanceId) == "prepared"
    assert _event_count(process_db, "agent_process_started") == 0


def test_transition_failure_rolls_back_and_never_releases(
    process_db: sqlite3.Connection,
) -> None:
    intent = prepare_process(process_db, "start-transition-failure")
    releases: list[str] = []

    with pytest.raises(
        AgentProcessLifecycleStorageConflictError,
        match="AGENT_PROCESS_GATE_TOKEN_MISMATCH",
    ):
        start_commit.commit_agent_process_started_and_release(
            process_db,
            process_instance_id=intent.processInstanceId,
            gate_token=b"z" * 32,
            expected_platform=PROCESS_PLATFORM,
            process_pid=PROCESS_PID,
            process_group_id=PROCESS_GROUP_ID,
            process_incarnation=incarnation(),
            release_callback=lambda: releases.append("released"),
            occurred_at=STARTED_AT,
        )

    assert releases == []
    assert process_db.in_transaction is False
    assert _stored_state(process_db, intent.processInstanceId) == "prepared"


def test_exception_after_commit_never_releases_from_an_uncertain_commit_result(
    process_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = prepare_process(process_db, "start-uncertain-commit")
    releases: list[str] = []

    def commit_then_raise(connection: sqlite3.Connection) -> None:
        connection.commit()
        raise sqlite3.OperationalError("injected post-commit transport failure")

    monkeypatch.setattr(start_commit, "_commit", commit_then_raise)
    with pytest.raises(
        sqlite3.OperationalError,
        match="injected post-commit transport failure",
    ):
        _commit_start(
            process_db,
            intent.processInstanceId,
            lambda: releases.append("released"),
        )

    assert releases == []
    assert process_db.in_transaction is False
    assert _stored_state(process_db, intent.processInstanceId) == "started"


def test_release_failure_leaves_durable_start_and_replay_does_not_retry(
    process_db: sqlite3.Connection,
) -> None:
    intent = prepare_process(process_db, "start-release-failure")
    attempts: list[str] = []
    private_detail = r"C:\private\helper.exe --token=do-not-persist"

    def fail_release() -> None:
        attempts.append("attempted")
        raise OSError(private_detail)

    with pytest.raises(
        start_commit.AgentProcessGateReleaseError,
        match="^AGENT_PROCESS_GATE_RELEASE_STATE_UNKNOWN$",
    ) as raised:
        _commit_start(process_db, intent.processInstanceId, fail_release)
    replay = _commit_start(
        process_db,
        intent.processInstanceId,
        lambda: attempts.append("retried"),
    )

    assert attempts == ["attempted"]
    assert raised.value.__suppress_context__ is True
    assert private_detail not in str(raised.value)
    assert private_detail not in repr(raised.value)
    assert _stored_state(process_db, intent.processInstanceId) == "started"
    assert replay["durableTransitionApplied"] is False
    assert replay["gateReleased"] is False


def test_commit_wrapper_rejects_an_existing_transaction(
    process_db: sqlite3.Connection,
) -> None:
    intent = prepare_process(process_db, "start-existing-transaction")
    process_db.execute("BEGIN")
    with pytest.raises(
        RuntimeError,
        match="AGENT_PROCESS_START_COMMIT_REQUIRES_IDLE_CONNECTION",
    ):
        _commit_start(process_db, intent.processInstanceId, lambda: None)
    assert process_db.in_transaction is True
    process_db.rollback()


def _commit_start(
    connection: sqlite3.Connection,
    process_instance_id: str,
    release_callback: Callable[[], None],
) -> dict[str, object]:
    return start_commit.commit_agent_process_started_and_release(
        connection,
        process_instance_id=process_instance_id,
        gate_token=GATE_TOKEN,
        expected_platform=PROCESS_PLATFORM,
        process_pid=PROCESS_PID,
        process_group_id=PROCESS_GROUP_ID,
        process_incarnation=incarnation(),
        release_callback=release_callback,
        occurred_at=STARTED_AT,
    )


def _stored_state(connection: sqlite3.Connection, process_instance_id: str) -> str:
    model = fetch_agent_process_lifecycle_for_connection(
        connection,
        process_instance_id,
    )
    assert model is not None
    return str(model["state"])


def _event_count(connection: sqlite3.Connection, event_type: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM run_events WHERE event_type = ?",
        (event_type,),
    ).fetchone()
    return int(row[0])
