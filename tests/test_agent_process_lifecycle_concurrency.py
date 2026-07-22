from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.agent_process_lifecycle_storage import (
    AgentProcessLifecycleStorageConflictError,
    mark_agent_process_exited_for_connection,
    mark_agent_process_lost_for_connection,
    mark_agent_process_spawn_failed_for_connection,
    mark_agent_process_started_for_connection,
    mark_agent_process_terminated_for_connection,
)
from tests.agent_process_lifecycle_storage_fixtures import (
    FINISHED_AT,
    GATE_TOKEN,
    PROCESS_GROUP_ID,
    PROCESS_PID,
    PROCESS_PLATFORM,
    STARTED_AT,
    digest,
    incarnation,
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


def test_two_connections_consume_one_gate_token_at_most_once(
    process_db: sqlite3.Connection,
) -> None:
    intent = prepare_process(process_db, "lifecycle-concurrent-start")
    barrier = threading.Barrier(2)

    def transition(connection: sqlite3.Connection) -> dict[str, Any]:
        return mark_agent_process_started_for_connection(
            connection,
            process_instance_id=intent.processInstanceId,
            gate_token=GATE_TOKEN,
            expected_platform=PROCESS_PLATFORM,
            process_pid=PROCESS_PID,
            process_group_id=PROCESS_GROUP_ID,
            process_incarnation=incarnation(),
            occurred_at=STARTED_AT,
        )

    outcomes = _run_concurrent(
        process_db,
        barrier=barrier,
        transitions=(transition, transition),
    )

    applied = sorted(
        outcome["transactionApplied"]
        for outcome in outcomes
        if isinstance(outcome, dict)
    )
    assert applied == [False, True]
    assert _event_count(process_db, "agent_process_started") == 1


def test_started_and_spawn_failed_race_has_one_durable_winner(
    process_db: sqlite3.Connection,
) -> None:
    intent = prepare_process(process_db, "lifecycle-start-spawn-failed-race")
    barrier = threading.Barrier(2)

    def start_transition(connection: sqlite3.Connection) -> dict[str, Any]:
        return mark_agent_process_started_for_connection(
            connection,
            process_instance_id=intent.processInstanceId,
            gate_token=GATE_TOKEN,
            expected_platform=PROCESS_PLATFORM,
            process_pid=PROCESS_PID,
            process_group_id=PROCESS_GROUP_ID,
            process_incarnation=incarnation(),
            occurred_at=STARTED_AT,
        )

    def fail_transition(connection: sqlite3.Connection) -> dict[str, Any]:
        return mark_agent_process_spawn_failed_for_connection(
            connection,
            process_instance_id=intent.processInstanceId,
            gate_token=GATE_TOKEN,
            failure_code="PROCESS_CREATE_FAILED",
            occurred_at=STARTED_AT,
        )

    outcomes = _run_concurrent(
        process_db,
        barrier=barrier,
        transitions=(start_transition, fail_transition),
    )

    assert (
        sum(
            isinstance(outcome, dict) and outcome["transactionApplied"] is True
            for outcome in outcomes
        )
        == 1
    )
    assert sum(isinstance(outcome, str) for outcome in outcomes) == 1
    assert (
        _event_count(process_db, "agent_process_started")
        + _event_count(process_db, "agent_process_spawn_failed")
        == 1
    )


def test_three_terminal_observations_have_one_durable_winner(
    process_db: sqlite3.Connection,
) -> None:
    intent = prepare_process(process_db, "lifecycle-terminal-race")
    start_process(process_db, intent)
    barrier = threading.Barrier(3)
    evidence = digest("terminal-race-evidence")

    transitions: tuple[Callable[[sqlite3.Connection], dict[str, Any]], ...] = (
        lambda connection: mark_agent_process_exited_for_connection(
            connection,
            process_instance_id=intent.processInstanceId,
            process_incarnation=incarnation(),
            exit_code=0,
            exit_reason="exit_code",
            occurred_at=FINISHED_AT,
        ),
        lambda connection: mark_agent_process_terminated_for_connection(
            connection,
            process_instance_id=intent.processInstanceId,
            process_incarnation=incarnation(),
            exit_reason="reconciler_terminated",
            evidence_hash=evidence,
            occurred_at=FINISHED_AT,
        ),
        lambda connection: mark_agent_process_lost_for_connection(
            connection,
            process_instance_id=intent.processInstanceId,
            process_incarnation=incarnation(),
            exit_reason="controller_lost",
            evidence_hash=evidence,
            occurred_at=FINISHED_AT,
        ),
    )
    outcomes = _run_concurrent(
        process_db,
        barrier=barrier,
        transitions=transitions,
    )

    assert (
        sum(
            isinstance(outcome, dict) and outcome["transactionApplied"] is True
            for outcome in outcomes
        )
        == 1
    )
    assert sum(isinstance(outcome, str) for outcome in outcomes) == 2
    assert (
        sum(
            _event_count(process_db, event_type)
            for event_type in (
                "agent_process_exited",
                "agent_process_terminated",
                "agent_process_lost",
            )
        )
        == 1
    )


def _run_concurrent(
    connection: sqlite3.Connection,
    *,
    barrier: threading.Barrier,
    transitions: tuple[Callable[[sqlite3.Connection], dict[str, Any]], ...],
) -> list[dict[str, Any] | str]:
    database_path = str(connection.execute("PRAGMA database_list").fetchone()[2])

    def run(
        transition: Callable[[sqlite3.Connection], dict[str, Any]],
    ) -> dict[str, Any] | str:
        worker = sqlite3.connect(database_path, timeout=10)
        worker.row_factory = sqlite3.Row
        worker.execute("PRAGMA busy_timeout = 10000")
        worker.execute("PRAGMA foreign_keys = ON")
        try:
            barrier.wait(timeout=10)
            worker.execute("BEGIN IMMEDIATE")
            try:
                result = transition(worker)
                worker.commit()
                return result
            except AgentProcessLifecycleStorageConflictError as exc:
                worker.rollback()
                return str(exc)
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=len(transitions)) as executor:
        return list(executor.map(run, transitions))


def _event_count(connection: sqlite3.Connection, event_type: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM run_events WHERE event_type = ?",
        (event_type,),
    ).fetchone()
    return int(row[0])
