from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
import tests.test_agent_process_instance_storage as process_fixtures

from apps.remote_runner.agent_process_instance_storage import (
    insert_prepared_agent_process_instance_for_connection,
)
from apps.remote_runner.agent_process_launch_recorder import (
    agent_process_gate_token_hash,
)
from apps.remote_runner.agent_process_lifecycle_storage import (
    mark_agent_process_started_for_connection,
)
from core.contracts.agent_process_instance import AgentProcessLaunchIntentV1
from core.contracts.linux_process_incarnation import build_linux_process_incarnation
from tests.test_agent_process_instance_storage import _prepare_intent


GATE_TOKEN = bytes(range(32))
PROCESS_PID = 4242
PROCESS_GROUP_ID = 4242
PROCESS_PLATFORM = "linux"
PROCESS_BOOT_ID = "12345678-1234-5678-9abc-123456789abc"
STARTED_AT = "2099-07-22T10:01:00Z"
FINISHED_AT = "2099-07-22T10:02:00Z"


@pytest.fixture
def process_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[sqlite3.Connection]:
    yield from process_fixtures.connection.__wrapped__(tmp_path, monkeypatch)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def incarnation(tag: str = "primary") -> dict[str, object]:
    return build_linux_process_incarnation(
        boot_id=PROCESS_BOOT_ID,
        pid=PROCESS_PID,
        proc_start_ticks=(9001 if tag == "primary" else 9002),
    )


def prepare_process(
    connection: sqlite3.Connection,
    tag: str,
) -> AgentProcessLaunchIntentV1:
    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(
        connection,
        tag,
        gate_token_hash=agent_process_gate_token_hash(GATE_TOKEN),
    )
    insert_prepared_agent_process_instance_for_connection(connection, intent)
    connection.commit()
    return intent


def start_process(
    connection: sqlite3.Connection,
    intent: AgentProcessLaunchIntentV1,
) -> dict[str, object]:
    connection.execute("BEGIN IMMEDIATE")
    result = mark_agent_process_started_for_connection(
        connection,
        process_instance_id=intent.processInstanceId,
        gate_token=GATE_TOKEN,
        expected_platform=PROCESS_PLATFORM,
        process_pid=PROCESS_PID,
        process_group_id=PROCESS_GROUP_ID,
        process_incarnation=incarnation(),
        occurred_at=STARTED_AT,
    )
    connection.commit()
    return result


__all__ = [
    "FINISHED_AT",
    "GATE_TOKEN",
    "PROCESS_GROUP_ID",
    "PROCESS_PID",
    "PROCESS_PLATFORM",
    "STARTED_AT",
    "digest",
    "incarnation",
    "prepare_process",
    "process_db",
    "start_process",
]
