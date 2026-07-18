from __future__ import annotations

import pytest

from apps.remote_runner.execution_query_storage import fetch_run
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import create_run_record_for_connection
from tests.helpers.reference_database import make_configured_remote_runner


def _agent_run_spec() -> dict[str, str]:
    return {
        "projectId": "proj_agent",
        "pipelineId": "pipeline_agent",
        "workflowRevisionId": "wfrev_agent",
    }


def test_connection_scoped_run_creation_requires_existing_writer_transaction(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)

    with get_connection(cfg) as connection:
        with pytest.raises(
            RuntimeError, match="RUN_CREATION_WRITER_TRANSACTION_REQUIRED"
        ):
            create_run_record_for_connection(
                connection,
                server_id="agent-control-plane.v1",
                actor="runner-token-principal",
                request_id="req_agent_tx_required",
                run_spec=_agent_run_spec(),
                idempotency_key="agent_internal_tx_required",
                payload_hash="hash_agent_tx_required",
            )


def test_connection_scoped_run_creation_uses_explicit_identity_actor_and_timestamp(
    tmp_path,
):
    cfg = make_configured_remote_runner(tmp_path)
    run_spec = _agent_run_spec()

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        created = create_run_record_for_connection(
            connection,
            server_id="agent-control-plane.v1",
            actor="runner-token-principal",
            request_id="req_agent_bound",
            run_spec=run_spec,
            idempotency_key="agent_internal_bound",
            payload_hash="hash_agent_bound",
            run_id="run_agent_bound",
            submitted_at="2099-06-07T10:00:00Z",
        )
        command = connection.execute(
            "SELECT * FROM run_commands WHERE run_id = ?",
            ("run_agent_bound",),
        ).fetchone()
        accepted = connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? AND event_type = 'accepted'",
            ("run_agent_bound",),
        ).fetchone()
        job = connection.execute(
            "SELECT * FROM run_jobs WHERE run_id = ?",
            ("run_agent_bound",),
        ).fetchone()
        idempotency = connection.execute(
            "SELECT * FROM idempotency WHERE server_id = ? AND idempotency_key = ?",
            ("agent-control-plane.v1", "agent_internal_bound"),
        ).fetchone()

        assert connection.in_transaction is True
        assert created.run["runId"] == "run_agent_bound"
        assert created.run["runSpec"] == run_spec
        assert created.run["submittedAt"] == "2099-06-07T10:00:00Z"
        assert command["actor"] == "runner-token-principal"
        assert command["idempotency_key"] == "agent_internal_bound"
        assert command["requested_at"] == "2099-06-07T10:00:00Z"
        assert accepted["actor"] == "runner-token-principal"
        assert accepted["command_id"] == command["command_id"]
        assert accepted["created_at"] == "2099-06-07T10:00:00Z"
        assert job["state"] == "queued"
        assert job["available_at"] == "2099-06-07T10:00:00Z"
        assert idempotency["run_id"] == "run_agent_bound"
        assert idempotency["canonical_payload_hash"] == "hash_agent_bound"
        connection.commit()

    persisted = fetch_run(cfg, "run_agent_bound")
    assert persisted is not None
    assert persisted["runId"] == created.run["runId"]
    assert persisted["runSpec"] == created.run["runSpec"]
    assert persisted["submittedAt"] == created.run["submittedAt"]


def test_connection_scoped_run_creation_replays_without_committing_caller_transaction(
    tmp_path,
):
    cfg = make_configured_remote_runner(tmp_path)

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        first = create_run_record_for_connection(
            connection,
            server_id="agent-control-plane.v1",
            actor="runner-token-principal",
            request_id="req_agent_first",
            run_spec=_agent_run_spec(),
            idempotency_key="agent_internal_replay",
            payload_hash="hash_agent_replay",
            run_id="run_agent_first",
        )
        replay = create_run_record_for_connection(
            connection,
            server_id="agent-control-plane.v1",
            actor="runner-token-principal",
            request_id="req_agent_replay",
            run_spec=_agent_run_spec(),
            idempotency_key="agent_internal_replay",
            payload_hash="hash_agent_replay",
            run_id="run_agent_second",
        )

        assert first.created is True
        assert replay.created is False
        assert replay.run["runId"] == "run_agent_first"
        assert connection.in_transaction is True
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM run_jobs").fetchone()[0] == 1
        connection.rollback()

    assert fetch_run(cfg, "run_agent_first") is None


def test_connection_scoped_run_creation_rolls_back_every_creation_row(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        create_run_record_for_connection(
            connection,
            server_id="agent-control-plane.v1",
            actor="runner-token-principal",
            request_id="req_agent_rollback",
            run_spec=_agent_run_spec(),
            idempotency_key="agent_internal_rollback",
            payload_hash="hash_agent_rollback",
            run_id="run_agent_rollback",
        )
        connection.rollback()

    with get_connection(cfg) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "runs",
                "run_commands",
                "run_events",
                "run_jobs",
                "idempotency",
            )
        }
    assert counts == {
        "runs": 0,
        "run_commands": 0,
        "run_events": 0,
        "run_jobs": 0,
        "idempotency": 0,
    }


def test_generic_run_creation_wrapper_preserves_server_id_actor_and_commits(tmp_path):
    cfg = make_configured_remote_runner(tmp_path)

    created = create_run_record(
        cfg,
        server_id="srv_generic",
        request_id="req_generic",
        run_spec={**_agent_run_spec(), "runId": "run_generic"},
        idempotency_key="idem_generic",
        payload_hash="hash_generic",
    )

    with get_connection(cfg) as connection:
        command_actor = connection.execute(
            "SELECT actor FROM run_commands WHERE run_id = ?",
            ("run_generic",),
        ).fetchone()[0]
        accepted_actor = connection.execute(
            "SELECT actor FROM run_events WHERE run_id = ? AND event_type = 'accepted'",
            ("run_generic",),
        ).fetchone()[0]
        job_count = connection.execute(
            "SELECT COUNT(*) FROM run_jobs WHERE run_id = ?",
            ("run_generic",),
        ).fetchone()[0]

    assert created.created is True
    assert created.run["serverId"] == "srv_generic"
    assert command_actor == "srv_generic"
    assert accepted_actor == "srv_generic"
    assert job_count == 1
