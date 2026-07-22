from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.remote_runner.agent_process_instance_storage import (
    AgentProcessInstanceStorageConflictError,
    fetch_agent_process_instance_by_attempt_lease_ordinal_for_connection,
    fetch_agent_process_instance_by_id_for_connection,
    insert_prepared_agent_process_instance_for_connection,
)
from apps.remote_runner.agent_run_input_materialization import (
    agent_run_input_materialization_payload,
)
from apps.remote_runner.agent_workspace_proof_storage import (
    insert_agent_workspace_proof_for_connection,
)
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.event_contracts import append_run_event_v2
from apps.remote_runner.storage_core import get_connection
from core.contracts.agent_process_instance import (
    AgentProcessLaunchIntentV1,
    agent_process_ordinal,
    build_agent_process_launch_intent_v1,
)
from core.contracts.agent_fastq_qc import fastq_qc_manifest_digest
from core.contracts.agent_fastq_qc_execution import agent_workflow_run_spec_hash
from core.contracts.agent_workspace_proof import (
    AgentWorkspaceProofV1,
    agent_workspace_tool_assets_hash,
    build_agent_workspace_proof_v1,
)
from tests.helpers.reference_database import make_remote_runner_config
from tests.test_agent_workspace_proof_storage import (
    AUTHORIZATION_ID,
    REVISION,
    RUNTIME_LOCK_HASH,
    RUNTIME_PROOF_HASH,
    RUN_ID,
    TARGET_ATTEMPT_ID,
    TARGET_LEASE_GENERATION,
    _seed_authority,
)
import tests.test_agent_workspace_proof_storage as workspace_proof_fixtures


TIMESTAMP = "2099-07-22T10:00:00Z"
REQUEST_ID = f"request-{RUN_ID}"
INPUT_BYTES = b"@read\nACGT\n+\nFFFF\n"
INPUT_SHA256 = hashlib.sha256(INPUT_BYTES).hexdigest()
INPUT_GOAL_CONTEXT = {
    "schemaVersion": "agent-fastq-qc-goal.v1",
    "analysis": "fastq-qc",
    "inputs": [
        {
            "uploadId": "upload-process-storage",
            "filename": "reads.fastq",
            "sha256": INPUT_SHA256,
            "sizeBytes": len(INPUT_BYTES),
            "mimeType": "text/plain",
        }
    ],
    "reportFormat": "multiqc-html",
}
INPUT_MANIFEST_DIGEST = fastq_qc_manifest_digest(INPUT_GOAL_CONTEXT)
INPUT_SNAPSHOT_HASH = INPUT_MANIFEST_DIGEST.removeprefix("sha256:")
RUN_SPEC = {
    "pipelineId": "generated-tool-run-v1",
    "inputs": [
        {
            "uploadId": "upload-process-storage",
            "filename": "reads.fastq",
            "role": "reads",
        }
    ],
}
RUN_SPEC_HASH = agent_workflow_run_spec_hash(RUN_SPEC)
IMMUTABLE_MANIFEST = [
    {
        "relativePath": "run-config.json",
        "size": 23,
        "sha256": hashlib.sha256(b"run-config").hexdigest(),
    },
    {
        "relativePath": "workflow/Snakefile",
        "size": 41,
        "sha256": hashlib.sha256(b"Snakefile").hexdigest(),
    },
]


@pytest.fixture
def connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[sqlite3.Connection]:
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    database = get_connection(cfg)
    monkeypatch.setattr(
        workspace_proof_fixtures,
        "INPUT_SNAPSHOT_HASH",
        INPUT_SNAPSHOT_HASH,
    )
    monkeypatch.setattr(workspace_proof_fixtures, "RUN_SPEC_HASH", RUN_SPEC_HASH)
    _seed_authority(database)
    goal = {
        "summary": "Verify one durable FASTQ QC process launch.",
        "successCriteria": [],
        "context": INPUT_GOAL_CONTEXT,
    }
    budget = {
        "maxModelTurns": 10,
        "maxToolCalls": 20,
        "maxReplans": 2,
        "maxRetries": 2,
        "maxWallClockSeconds": 3600,
    }
    creation_payload = {
        "budget": budget,
        "contractVersion": "agent-session.v1",
        "constraints": {},
        "createdBy": "runner",
        "goal": goal,
        "projectId": "project-workspace",
    }
    creation_hash = hashlib.sha256(
        json.dumps(
            creation_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    database.execute(
        "UPDATE agent_sessions SET goal_json = ?, budget_json = ?, "
        "creation_request_hash = ? "
        "WHERE session_id = 'ags_workspace'",
        (_stable_json(goal), _stable_json(budget), creation_hash),
    )
    database.execute(
        "UPDATE runs SET run_spec_json = ? WHERE run_id = ?",
        (_stable_json(RUN_SPEC), RUN_ID),
    )
    database.execute(
        """
        INSERT INTO uploads (
            upload_id, filename, path, size_bytes, sha256, mime_type, uploaded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "upload-process-storage",
            "reads.fastq",
            "managed/process-storage/reads.fastq",
            len(INPUT_BYTES),
            INPUT_SHA256,
            "text/plain",
            TIMESTAMP,
        ),
    )
    append_run_event_v2(
        database,
        run_id=RUN_ID,
        event_type="run_attempt_started",
        stage="running",
        state_version=2,
        message="Run attempt started.",
        request_id=REQUEST_ID,
        payload={
            "attemptId": TARGET_ATTEMPT_ID,
            "leaseGeneration": TARGET_LEASE_GENERATION,
        },
        occurred_at="2099-07-22T09:59:58Z",
    )
    receipt_hash = database.execute(
        "SELECT receipt_hash FROM agent_run_authorizations WHERE authorization_id = ?",
        (AUTHORIZATION_ID,),
    ).fetchone()[0]
    expectation = {
        **INPUT_GOAL_CONTEXT["inputs"][0],
        "role": "reads",
        "inputManifestDigest": INPUT_MANIFEST_DIGEST,
        "authorizationId": AUTHORIZATION_ID,
        "receiptHash": receipt_hash,
    }
    append_run_event_v2(
        database,
        run_id=RUN_ID,
        event_type="agent_input_materialized",
        stage="agent_input",
        state_version=2,
        message="Agent-authorized input materialized and verified.",
        request_id=REQUEST_ID,
        payload=agent_run_input_materialization_payload(
            expectation,
            state_version=2,
        ),
        occurred_at="2099-07-22T09:59:59Z",
    )
    database.commit()
    try:
        yield database
    finally:
        database.close()


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _prepare_intent(
    connection: sqlite3.Connection,
    tag: str,
    *,
    attempt_id: str = TARGET_ATTEMPT_ID,
    lease_generation: int = TARGET_LEASE_GENERATION,
    process_kind: str = "dry_run",
    previous_proof_hash: str | None = None,
    gate_token_hash: str | None = None,
    spawn_stage: str = "agent_process",
    spawn_message: str = "Agent process launch intent prepared.",
    spawn_request_id: str = REQUEST_ID,
    spawn_actor: str | None = "remote-runner",
    spawn_state_version: int = 2,
    proof_created_at: str | None = None,
    event_created_at: str | None = None,
    intent_prepared_at: str | None = None,
) -> tuple[AgentProcessLaunchIntentV1, AgentWorkspaceProofV1]:
    ordinal = agent_process_ordinal(process_kind)
    prepared_at = f"2099-07-22T10:00:0{ordinal}Z"
    event_id = f"evt_{_hash(f'process-event-{tag}')[:10]}"
    proof = build_agent_workspace_proof_v1(
        {
            "runId": RUN_ID,
            "authorizationId": AUTHORIZATION_ID,
            "attemptId": attempt_id,
            "leaseGeneration": lease_generation,
            "sourceAttemptId": None,
            "processBoundary": (
                "pre_dry_run" if process_kind == "dry_run" else "pre_run"
            ),
            "processOrdinal": ordinal,
            "workflowRevisionId": REVISION["workflowRevisionId"],
            "workflowRevisionContentHash": REVISION["contentHash"],
            "workflowRevisionManifestHash": REVISION["manifestHash"],
            "runSpecHash": RUN_SPEC_HASH,
            "inputSnapshotHash": INPUT_SNAPSHOT_HASH,
            "runtimeLockHash": RUNTIME_LOCK_HASH,
            "runtimeProofHash": RUNTIME_PROOF_HASH,
            "immutableManifest": IMMUTABLE_MANIFEST,
            "snakemakeManifest": [],
            "previousProofHash": previous_proof_hash,
            "eventId": event_id,
            "createdAt": proof_created_at or prepared_at,
        }
    )
    assert proof.toolAssetsHash == agent_workspace_tool_assets_hash(IMMUTABLE_MANIFEST)
    launch_spec_hash = _hash(f"launch-spec-{tag}")
    gate_hash = gate_token_hash or _hash(f"gate-hash-{tag}")
    event = append_run_event_v2(
        connection,
        run_id=RUN_ID,
        event_type="agent_process_spawn_intent_recorded",
        stage=spawn_stage,
        state_version=spawn_state_version,
        message=spawn_message,
        request_id=spawn_request_id,
        payload={
            "attemptId": attempt_id,
            "leaseGeneration": lease_generation,
            "processKind": process_kind,
            "processOrdinal": ordinal,
            "workspaceProofId": proof.workspaceProofId,
            "launchSpecHash": launch_spec_hash,
            "gateTokenHash": gate_hash,
        },
        event_id=event_id,
        actor=spawn_actor,
        occurred_at=event_created_at or prepared_at,
    )
    insert_agent_workspace_proof_for_connection(connection, proof)
    return (
        build_agent_process_launch_intent_v1(
            {
                "runId": RUN_ID,
                "authorizationId": AUTHORIZATION_ID,
                "attemptId": attempt_id,
                "leaseGeneration": lease_generation,
                "processOrdinal": ordinal,
                "processKind": process_kind,
                "workspaceProofId": proof.workspaceProofId,
                "toolAssetsHash": proof.toolAssetsHash,
                "launchSpecHash": launch_spec_hash,
                "gateTokenHash": gate_hash,
                "spawnIntentEventId": event_id,
                "spawnIntentEventHash": event["event_hash"],
                "preparedAt": intent_prepared_at or prepared_at,
            }
        ),
        proof,
    )


def _insert_and_commit(
    connection: sqlite3.Connection,
) -> AgentProcessLaunchIntentV1:
    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(connection, "committed")
    insert_prepared_agent_process_instance_for_connection(connection, intent)
    connection.commit()
    return intent


def test_prepared_intent_roundtrips_by_id_and_attempt_ordinal(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(connection, "roundtrip")
    inserted = insert_prepared_agent_process_instance_for_connection(
        connection, intent.runtime_payload()
    )
    connection.commit()

    by_id = fetch_agent_process_instance_by_id_for_connection(
        connection, intent.processInstanceId
    )
    by_ordinal = fetch_agent_process_instance_by_attempt_lease_ordinal_for_connection(
        connection,
        attempt_id=TARGET_ATTEMPT_ID,
        lease_generation=TARGET_LEASE_GENERATION,
        process_ordinal=1,
    )
    assert inserted == by_id == by_ordinal == intent.runtime_payload()

    row = connection.execute(
        "SELECT * FROM agent_process_instances WHERE process_instance_id = ?",
        (intent.processInstanceId,),
    ).fetchone()
    assert row["state"] == "prepared"
    assert all(
        row[field] is None
        for field in (
            "process_pid",
            "process_group_id",
            "process_incarnation_json",
            "process_incarnation_hash",
            "started_event_id",
            "terminal_event_id",
            "exit_code",
            "exit_reason",
            "started_at",
            "finished_at",
        )
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"spawn_stage": "process"},
        {"spawn_message": "non-production message"},
        {"spawn_request_id": "request-non-production"},
        {"spawn_actor": None},
        {"spawn_state_version": 3},
    ],
)
def test_insert_rejects_nonproduction_spawn_event_envelope(
    connection: sqlite3.Connection,
    overrides: dict[str, object],
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(
        connection,
        "nonproduction-envelope",
        **overrides,
    )

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_STORED_SPAWN_EVENT_MISMATCH",
    ):
        insert_prepared_agent_process_instance_for_connection(connection, intent)
    connection.rollback()


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        (
            {"proof_created_at": "2099-07-22T10:00:31Z"},
            "AGENT_PROCESS_INSTANCE_PREPARED_TIME_MISMATCH",
        ),
        (
            {"event_created_at": "2099-07-22T10:00:32Z"},
            "AGENT_PROCESS_INSTANCE_STORED_SPAWN_EVENT_MISMATCH",
        ),
        (
            {"intent_prepared_at": "2099-07-22T10:00:33Z"},
            "AGENT_PROCESS_INSTANCE_PREPARED_TIME_MISMATCH",
        ),
    ],
)
def test_insert_rejects_proof_event_or_intent_time_drift(
    connection: sqlite3.Connection,
    overrides: dict[str, str],
    code: str,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(connection, f"time-drift-{code}", **overrides)

    with pytest.raises(AgentProcessInstanceStorageConflictError, match=code):
        insert_prepared_agent_process_instance_for_connection(connection, intent)
    connection.rollback()


def test_writer_requires_existing_transaction_and_never_commits(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(connection, "transaction")
    connection.commit()

    with pytest.raises(RuntimeError, match="WRITER_TRANSACTION_REQUIRED"):
        insert_prepared_agent_process_instance_for_connection(connection, intent)

    connection.execute("BEGIN IMMEDIATE")
    insert_prepared_agent_process_instance_for_connection(connection, intent)
    assert connection.in_transaction is True
    connection.rollback()
    assert (
        fetch_agent_process_instance_by_id_for_connection(
            connection, intent.processInstanceId
        )
        is None
    )


def test_exact_duplicate_id_is_a_conflict_not_a_successful_replay(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(connection, "duplicate-id")
    insert_prepared_agent_process_instance_for_connection(connection, intent)

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_ALREADY_PREPARED",
    ):
        insert_prepared_agent_process_instance_for_connection(connection, intent)
    assert (
        connection.execute("SELECT COUNT(*) FROM agent_process_instances").fetchone()[0]
        == 1
    )
    connection.rollback()


def test_duplicate_attempt_lease_ordinal_with_drifted_intent_is_rejected(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(connection, "duplicate-ordinal")
    insert_prepared_agent_process_instance_for_connection(connection, intent)
    conflicting_payload = intent.runtime_payload()
    conflicting_payload["preparedAt"] = "2099-07-22T10:00:59Z"
    conflicting_payload.pop("processInstanceId")
    conflicting_payload.pop("launchIntentHash")
    conflicting = build_agent_process_launch_intent_v1(conflicting_payload)

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_PREPARED_TIME_MISMATCH",
    ):
        insert_prepared_agent_process_instance_for_connection(connection, conflicting)
    connection.rollback()


def test_duplicate_gate_token_hash_is_a_stable_conflict(
    connection: sqlite3.Connection,
) -> None:
    shared_gate_hash = _hash("shared-gate-hash")
    connection.execute("BEGIN IMMEDIATE")
    dry_intent, dry_proof = _prepare_intent(
        connection,
        "gate-dry",
        gate_token_hash=shared_gate_hash,
    )
    insert_prepared_agent_process_instance_for_connection(connection, dry_intent)
    run_intent, _ = _prepare_intent(
        connection,
        "gate-run",
        process_kind="run",
        previous_proof_hash=dry_proof.proofHash,
        gate_token_hash=shared_gate_hash,
    )

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_GATE_TOKEN_CONFLICT",
    ):
        insert_prepared_agent_process_instance_for_connection(connection, run_intent)
    connection.rollback()


def test_forged_content_addressed_contract_is_rejected(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(connection, "forged")
    forged = intent.runtime_payload()
    forged["launchSpecHash"] = _hash("forged-launch-spec")

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_INTENT_INVALID",
    ):
        insert_prepared_agent_process_instance_for_connection(connection, forged)
    connection.rollback()


def test_read_rejects_tampered_immutable_intent_row(
    connection: sqlite3.Connection,
) -> None:
    intent = _insert_and_commit(connection)
    connection.execute("DROP TRIGGER agent_process_instances_intent_immutable")
    connection.execute("DROP TRIGGER agent_process_instances_transition_guard")
    connection.execute(
        "UPDATE agent_process_instances SET prepared_at = ? "
        "WHERE process_instance_id = ?",
        ("2099-07-22T10:00:58Z", intent.processInstanceId),
    )
    connection.commit()

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_STORED_PAYLOAD_INVALID",
    ):
        fetch_agent_process_instance_by_id_for_connection(
            connection, intent.processInstanceId
        )


def test_read_rejects_tampered_prepared_shape(
    connection: sqlite3.Connection,
) -> None:
    intent = _insert_and_commit(connection)
    connection.execute("DROP TRIGGER agent_process_instances_transition_guard")
    connection.execute(
        "UPDATE agent_process_instances SET process_pid = 4242 "
        "WHERE process_instance_id = ?",
        (intent.processInstanceId,),
    )
    connection.commit()

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_STORED_PREPARED_SHAPE_INVALID",
    ):
        fetch_agent_process_instance_by_id_for_connection(
            connection, intent.processInstanceId
        )


def test_read_rejects_tampered_spawn_event_hash(
    connection: sqlite3.Connection,
) -> None:
    intent = _insert_and_commit(connection)
    connection.execute("DROP TRIGGER agent_process_instances_run_events_no_update")
    connection.execute(
        "UPDATE run_events SET event_hash = ? WHERE event_id = ?",
        (_hash("tampered-event"), intent.spawnIntentEventId),
    )
    connection.commit()

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_STORED_SPAWN_EVENT_MISMATCH",
    ):
        fetch_agent_process_instance_by_id_for_connection(
            connection, intent.processInstanceId
        )


def test_read_rejects_tampered_linked_workspace_proof(
    connection: sqlite3.Connection,
) -> None:
    intent = _insert_and_commit(connection)
    connection.execute("DROP TRIGGER agent_workspace_proofs_no_update")
    connection.execute(
        "UPDATE agent_workspace_proofs SET immutable_manifest_json = '[]' "
        "WHERE workspace_proof_id = ?",
        (intent.workspaceProofId,),
    )
    connection.commit()

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_WORKSPACE_PROOF_INVALID",
    ):
        fetch_agent_process_instance_by_id_for_connection(
            connection, intent.processInstanceId
        )


def test_read_rejects_tampered_spawn_event_predecessor_chain(
    connection: sqlite3.Connection,
) -> None:
    predecessor = connection.execute(
        "SELECT event_id FROM run_events "
        "WHERE run_id = ? AND event_type = 'agent_input_materialized'",
        (RUN_ID,),
    ).fetchone()
    intent = _insert_and_commit(connection)
    with pytest.raises(sqlite3.IntegrityError, match="EVENT_IMMUTABLE"):
        connection.execute(
            "UPDATE run_events SET event_hash = ? WHERE event_id = ?",
            (_hash("blocked-predecessor"), predecessor["event_id"]),
        )
    with pytest.raises(sqlite3.IntegrityError, match="EVENT_IMMUTABLE"):
        connection.execute(
            "DELETE FROM run_events WHERE event_id = ?",
            (predecessor["event_id"],),
        )
    connection.execute("DROP TRIGGER agent_process_instances_run_events_no_update")
    connection.execute(
        "UPDATE run_events SET event_hash = ? WHERE event_id = ?",
        (_hash("tampered-predecessor"), predecessor["event_id"]),
    )
    connection.commit()

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_INPUT_AUTHORITY_INVALID",
    ):
        fetch_agent_process_instance_by_id_for_connection(
            connection, intent.processInstanceId
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("stage", "tampered-stage"),
        ("state_version", 3),
        ("message", "tampered message"),
        ("request_id", "tampered-request"),
        ("event_id", "invalid-materialization-event-id"),
    ],
)
def test_read_rejects_tampered_production_input_event_semantics(
    connection: sqlite3.Connection,
    column: str,
    value: object,
) -> None:
    intent = _insert_and_commit(connection)
    connection.execute("DROP TRIGGER agent_process_instances_run_events_no_update")
    materialization_id = connection.execute(
        "SELECT event_id FROM run_events "
        "WHERE run_id = ? AND event_type = 'agent_input_materialized'",
        (RUN_ID,),
    ).fetchone()[0]
    connection.execute(
        f"UPDATE run_events SET {column} = ? WHERE event_id = ?",
        (value, materialization_id),
    )
    connection.commit()

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_INPUT_AUTHORITY_INVALID",
    ):
        fetch_agent_process_instance_by_id_for_connection(
            connection,
            intent.processInstanceId,
        )


@pytest.mark.parametrize("authority", ["run_spec", "request_id", "upload"])
def test_read_rebuilds_input_authority_from_persistent_roots(
    connection: sqlite3.Connection,
    authority: str,
) -> None:
    intent = _insert_and_commit(connection)
    if authority == "run_spec":
        connection.execute(
            "UPDATE runs SET run_spec_json = '{\"inputs\":[]}' WHERE run_id = ?",
            (RUN_ID,),
        )
    elif authority == "request_id":
        connection.execute(
            "UPDATE runs SET request_id = '' WHERE run_id = ?",
            (RUN_ID,),
        )
    else:
        connection.execute(
            "UPDATE uploads SET sha256 = ? WHERE upload_id = ?",
            (_hash("tampered-upload"), "upload-process-storage"),
        )
    connection.commit()

    with pytest.raises(
        AgentProcessInstanceStorageConflictError,
        match="AGENT_PROCESS_INSTANCE_INPUT_AUTHORITY_INVALID",
    ):
        fetch_agent_process_instance_by_id_for_connection(
            connection,
            intent.processInstanceId,
        )


def test_read_uses_historical_materialization_state_after_run_advances(
    connection: sqlite3.Connection,
) -> None:
    intent = _insert_and_commit(connection)
    connection.execute(
        "UPDATE runs SET state_version = state_version + 1 WHERE run_id = ?",
        (RUN_ID,),
    )
    connection.commit()

    assert (
        fetch_agent_process_instance_by_id_for_connection(
            connection,
            intent.processInstanceId,
        )
        == intent.runtime_payload()
    )


def test_storage_surface_contains_only_the_gate_token_hash(
    connection: sqlite3.Connection,
) -> None:
    parameters = inspect.signature(
        insert_prepared_agent_process_instance_for_connection
    ).parameters
    assert tuple(parameters) == ("connection", "intent")

    connection.execute("BEGIN IMMEDIATE")
    intent, _ = _prepare_intent(connection, "gate-surface")
    inserted = insert_prepared_agent_process_instance_for_connection(connection, intent)
    assert "gateTokenHash" in inserted
    assert "gateToken" not in inserted
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(agent_process_instances)")
    }
    assert "gate_token_hash" in columns
    assert "gate_token" not in columns
    connection.rollback()
