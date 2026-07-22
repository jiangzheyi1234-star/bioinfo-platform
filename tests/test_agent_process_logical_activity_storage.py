from __future__ import annotations

import sqlite3

import pytest

from apps.remote_runner.agent_process_instance_storage import (
    AgentProcessInstanceStorageConflictError,
    insert_prepared_agent_process_instance_for_connection,
)
from tests.test_agent_process_instance_storage import (
    RUN_ID,
    TARGET_ATTEMPT_ID,
    TARGET_LEASE_GENERATION,
    TIMESTAMP,
    _prepare_intent,
)


pytest_plugins = ("tests.test_agent_process_instance_storage",)


def test_cross_lease_storage_insert_rejects_retry_stable_logical_activity(
    connection: sqlite3.Connection,
) -> None:
    retry_attempt_id = "att_process_storage_retry"
    retry_generation = TARGET_LEASE_GENERATION + 1
    connection.execute("BEGIN IMMEDIATE")
    first, _ = _prepare_intent(connection, "logical-first")
    insert_prepared_agent_process_instance_for_connection(connection, first)
    connection.execute(
        "UPDATE run_attempts SET state = 'failed' WHERE attempt_id = ?",
        (TARGET_ATTEMPT_ID,),
    )
    connection.execute(
        """
        INSERT INTO run_attempts (
            attempt_id, run_id, job_id, lease_generation, attempt_number,
            state, worker_id, work_dir, created_at, updated_at
        ) VALUES (?, ?, 'job-workspace', ?, 2, 'running', 'worker-retry',
            'work-process-storage-retry', ?, ?)
        """,
        (retry_attempt_id, RUN_ID, retry_generation, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        "UPDATE run_leases SET attempt_id = ?, lease_generation = ?, "
        "worker_id = 'worker-retry' WHERE run_id = ?",
        (retry_attempt_id, retry_generation, RUN_ID),
    )
    retry, _ = _prepare_intent(
        connection,
        "logical-retry",
        attempt_id=retry_attempt_id,
        lease_generation=retry_generation,
    )

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_LOGICAL_ACTIVITY_CONFLICT",
    ):
        insert_prepared_agent_process_instance_for_connection(connection, retry)
    assert (
        connection.execute("SELECT COUNT(*) FROM agent_process_instances").fetchone()[0]
        == 1
    )
    connection.rollback()
