from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from apps.remote_runner.agent_run_authorization_storage import (
    insert_agent_run_authorization_for_connection,
)
from apps.remote_runner.agent_workspace_proof_storage import (
    AgentWorkspaceProofStorageConflictError,
    fetch_agent_workspace_proof_by_id_for_connection,
    fetch_latest_agent_workspace_proof_for_attempt_for_connection,
    fetch_terminal_agent_workspace_proof_for_attempt_for_connection,
    insert_agent_workspace_proof_for_connection,
    resolve_agent_workspace_proof_replay_for_connection,
)
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.storage_core import get_connection
from core.contracts.agent_run_authorization import (
    AgentRunAuthorizationReceipt,
    agent_run_authorization_receipt_hash,
)
from core.contracts.agent_workspace_proof import (
    AgentWorkspaceProofV1,
    build_agent_workspace_proof_v1,
)
from tests.helpers.reference_database import make_remote_runner_config


RUN_ID = "run_workspace_agent"
AUTHORIZATION_ID = "agrauth_workspace_agent"
TARGET_ATTEMPT_ID = "att_workspace_current"
TARGET_LEASE_GENERATION = 3
SOURCE_ATTEMPT_ID = "att_workspace_source"
SOURCE_LEASE_GENERATION = 2
OTHER_RUN_ID = "run_workspace_other"
OTHER_ATTEMPT_ID = "att_workspace_other"
TIMESTAMP = "2099-06-07T10:00:00Z"


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


def _revision_facts(tag: str) -> dict[str, object]:
    manifest = {"files": [{"path": "workflow/Snakefile", "tag": tag}]}
    content = {
        "schemaVersion": "workflow-revision.v1",
        "draftId": None,
        "draftRevision": None,
        "manifest": manifest,
        "graphSnapshot": {},
        "runtimeLock": {},
        "compiler": {},
    }
    content_hash = hashlib.sha256(_stable_json(content).encode("utf-8")).hexdigest()
    return {
        "workflowRevisionId": f"wfrev_{content_hash[:24]}",
        "contentHash": content_hash,
        "manifest": manifest,
        "manifestHash": hashlib.sha256(
            _stable_json(manifest).encode("utf-8")
        ).hexdigest(),
    }


REVISION = _revision_facts("primary")
OTHER_REVISION = _revision_facts("other")
RUN_SPEC_HASH = _hash("run-spec")
INPUT_SNAPSHOT_HASH = _hash("input-snapshot")
TOOL_ASSETS_HASH = _hash("tool-assets")
RUNTIME_LOCK_HASH = _hash("runtime-lock")
RUNTIME_PROOF_HASH = _hash("runtime-proof")


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    database = get_connection(cfg)
    _seed_authority(database)
    try:
        yield database
    finally:
        database.close()


def _seed_authority(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO agent_sessions (
            session_id, contract_version, project_id, goal_json, constraints_json,
            budget_json, status, state_version, plan_generation, active_plan_hash,
            workflow_revision_id, creation_request_id, creation_request_hash,
            created_by, created_at, updated_at
        ) VALUES (
            'ags_workspace', 'agent-session.v1', 'project-workspace', '{}', '{}',
            '{}', 'ready_to_run', 5, 1, ?, ?, 'create-workspace', ?, 'runner', ?, ?
        )
        """,
        (
            _hash("plan"),
            REVISION["workflowRevisionId"],
            _hash("create"),
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    connection.execute(
        """
        INSERT INTO agent_plan_revisions (
            plan_revision_id, contract_version, session_id, plan_generation,
            parent_plan_revision_id, draft_id, draft_revision, plan_hash,
            proposal_json, validation_json, budget_json, created_by, created_at
        ) VALUES (
            'agpr_workspace', 'agent-plan-revision.v1', 'ags_workspace', 1,
            NULL, 'draft-workspace', 1, ?, '{}', '{}', '{}', 'runner', ?
        )
        """,
        (_hash("plan"), TIMESTAMP),
    )
    _insert_revision(connection, REVISION)
    _insert_revision(connection, OTHER_REVISION)
    _insert_run(connection, RUN_ID, str(REVISION["workflowRevisionId"]))
    _insert_run(connection, OTHER_RUN_ID, str(OTHER_REVISION["workflowRevisionId"]))

    receipt_payload: dict[str, object] = {
        "authorizationId": AUTHORIZATION_ID,
        "contractVersion": "agent-run-authorization.v1",
        "sessionId": "ags_workspace",
        "previewHash": _hash("preview"),
        "planRevisionId": "agpr_workspace",
        "planGeneration": 1,
        "planHash": _hash("plan"),
        "workflowRevisionId": REVISION["workflowRevisionId"],
        "expectedStateVersion": 5,
        "inputManifestDigest": f"sha256:{INPUT_SNAPSHOT_HASH}",
        "runSpecHash": RUN_SPEC_HASH,
        "executionPolicyId": "agent-fastq-qc-execution.v1",
        "executionPolicyHash": _hash("execution-policy"),
        "runtimeLockHash": RUNTIME_LOCK_HASH,
        "runtimeProofHash": RUNTIME_PROOF_HASH,
        "effectBudgetHash": _hash("effect-budget"),
        "runId": RUN_ID,
        "scope": "submit_workflow_run",
        "confirmation": "authorize-workflow-run",
        "actor": "runner",
        "requestId": "authorize-workspace",
        "idempotencyKey": "authorize-workspace-idem",
        "commandHash": _hash("authorize-command"),
        "createdAt": TIMESTAMP,
    }
    receipt_payload["receiptHash"] = agent_run_authorization_receipt_hash(
        receipt_payload
    )
    receipt = AgentRunAuthorizationReceipt.model_validate(receipt_payload)
    insert_agent_run_authorization_for_connection(connection, receipt)

    connection.execute(
        """
        INSERT INTO run_jobs (
            job_id, run_id, state, available_at, execution_options_json,
            created_at, updated_at
        ) VALUES (
            'job-workspace', ?, 'claimed', ?, '{}', ?, ?
        )
        """,
        (RUN_ID, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    connection.executemany(
        """
        INSERT INTO run_attempts (
            attempt_id, run_id, job_id, lease_generation, state, worker_id,
            work_dir, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'running', 'worker', ?, ?, ?)
        """,
        (
            (
                SOURCE_ATTEMPT_ID,
                RUN_ID,
                "job-workspace",
                SOURCE_LEASE_GENERATION,
                "source-work",
                TIMESTAMP,
                TIMESTAMP,
            ),
            (
                TARGET_ATTEMPT_ID,
                RUN_ID,
                "job-workspace",
                TARGET_LEASE_GENERATION,
                "target-work",
                TIMESTAMP,
                TIMESTAMP,
            ),
            (
                OTHER_ATTEMPT_ID,
                OTHER_RUN_ID,
                "job-other",
                1,
                "other-work",
                TIMESTAMP,
                TIMESTAMP,
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO run_leases (
            run_id, attempt_id, lease_generation, worker_id, heartbeat_at,
            expires_at, state, updated_at
        ) VALUES (?, ?, ?, 'worker', ?, ?, 'active', ?)
        """,
        (
            RUN_ID,
            TARGET_ATTEMPT_ID,
            TARGET_LEASE_GENERATION,
            TIMESTAMP,
            "2099-06-07T11:00:00Z",
            TIMESTAMP,
        ),
    )
    connection.commit()


def _insert_revision(
    connection: sqlite3.Connection,
    revision: dict[str, object],
) -> None:
    connection.execute(
        """
        INSERT INTO workflow_revisions (
            workflow_revision_id, draft_id, draft_revision, content_hash,
            manifest_json, graph_snapshot_json, runtime_lock_json, compiler_json,
            created_by, created_at
        ) VALUES (?, NULL, NULL, ?, ?, '{}', '{}', '{}', 'runner', ?)
        """,
        (
            revision["workflowRevisionId"],
            revision["contentHash"],
            _stable_json(revision["manifest"]),
            TIMESTAMP,
        ),
    )


def _insert_run(
    connection: sqlite3.Connection,
    run_id: str,
    workflow_revision_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO runs (
            run_id, server_id, project_id, pipeline_id, pipeline_version,
            run_spec_version, workflow_revision_id, status, stage, state_version,
            message, result_dir, last_updated_at, request_id, submitted_at,
            run_spec_json
        ) VALUES (?, 'agent-control-plane.v1', 'project-workspace',
            'generated-tool-run-v1', '1.0.0', '2026-04-21', ?, 'running',
            'running', 2, 'running', '', ?, ?, ?, '{}')
        """,
        (run_id, workflow_revision_id, TIMESTAMP, f"request-{run_id}", TIMESTAMP),
    )


def _proof(
    tag: str,
    *,
    run_id: str = RUN_ID,
    authorization_id: str = AUTHORIZATION_ID,
    attempt_id: str = TARGET_ATTEMPT_ID,
    lease_generation: int = TARGET_LEASE_GENERATION,
    source_attempt_id: str | None = None,
    process_boundary: str = "pre_dry_run",
    process_ordinal: int = 1,
    previous_proof_hash: str | None = None,
    workflow_revision: dict[str, object] = REVISION,
    snakemake_manifest: list[dict[str, object]] | None = None,
    event_id: str | None = None,
) -> AgentWorkspaceProofV1:
    return build_agent_workspace_proof_v1(
        {
            "runId": run_id,
            "authorizationId": authorization_id,
            "attemptId": attempt_id,
            "leaseGeneration": lease_generation,
            "sourceAttemptId": source_attempt_id,
            "processBoundary": process_boundary,
            "processOrdinal": process_ordinal,
            "workflowRevisionId": workflow_revision["workflowRevisionId"],
            "workflowRevisionContentHash": workflow_revision["contentHash"],
            "workflowRevisionManifestHash": workflow_revision["manifestHash"],
            "runSpecHash": RUN_SPEC_HASH,
            "inputSnapshotHash": INPUT_SNAPSHOT_HASH,
            "toolAssetsHash": TOOL_ASSETS_HASH,
            "runtimeLockHash": RUNTIME_LOCK_HASH,
            "runtimeProofHash": RUNTIME_PROOF_HASH,
            "immutableManifest": [
                {
                    "relativePath": "run-config.json",
                    "size": 23,
                    "sha256": _hash("run-config"),
                },
                {
                    "relativePath": "workflow/Snakefile",
                    "size": 41,
                    "sha256": _hash("Snakefile"),
                },
            ],
            "snakemakeManifest": snakemake_manifest or [],
            "previousProofHash": previous_proof_hash,
            "eventId": event_id or f"evt_workspace_{tag}",
            "createdAt": f"2099-06-07T10:00:{process_ordinal:02d}Z",
        }
    )


def _insert(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1,
) -> dict:
    connection.execute("BEGIN IMMEDIATE")
    inserted = insert_agent_workspace_proof_for_connection(connection, proof)
    connection.commit()
    return inserted


def _activate_lease(
    connection: sqlite3.Connection,
    attempt_id: str,
    lease_generation: int,
) -> None:
    connection.execute(
        """
        UPDATE run_leases
        SET attempt_id = ?, lease_generation = ?, state = 'active'
        WHERE run_id = ?
        """,
        (attempt_id, lease_generation, RUN_ID),
    )
    connection.commit()


def _resume_execution_options(
    source_attempt_id: str,
    source_lease_generation: int,
) -> dict[str, object]:
    return {
        "schemaVersion": "run-job-execution-options.v1",
        "snakemake": {
            "schemaVersion": "snakemake-run-resume-options.v1",
            "rerunIncomplete": True,
            "forcerunRules": [],
            "argsPreview": ["--rerun-incomplete"],
            "unsafeFlagsProhibited": [
                "--forceall",
                "--forcerun",
                "--ignore-incomplete",
                "--touch",
            ],
        },
        "resumeScope": {
            "schemaVersion": "run-resume-execution-scope.v1",
            "mode": "run-resume",
            "sourcePlanHash": _hash("source-plan"),
            "sourceAttempt": {
                "attemptId": source_attempt_id,
                "attemptNumber": 1,
                "leaseGeneration": source_lease_generation,
                "state": "failed",
            },
            "outputCount": 1,
            "outputKeys": ["report"],
            "finalizeRunOnAdoption": True,
            "postExecutionAdoptionRequired": True,
            "cacheAdoptionAllowed": False,
            "pathExposed": False,
            "storageUriExposed": False,
            "checksumValueExposed": False,
        },
    }


def _set_resume_job_options(
    connection: sqlite3.Connection,
    source_attempt_id: str,
    source_lease_generation: int,
) -> None:
    connection.execute(
        "UPDATE run_attempts SET state = 'failed' WHERE attempt_id = ?",
        (source_attempt_id,),
    )
    connection.execute(
        "UPDATE run_jobs SET execution_options_json = ? WHERE job_id = 'job-workspace'",
        (
            _stable_json(
                _resume_execution_options(source_attempt_id, source_lease_generation)
            ),
        ),
    )
    connection.commit()


def _assert_insert_conflict(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1,
    code: str,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    with pytest.raises(AgentWorkspaceProofStorageConflictError, match=code):
        insert_agent_workspace_proof_for_connection(connection, proof)
    connection.rollback()


def test_insert_requires_writer_transaction_and_leaves_rollback_to_caller(
    connection: sqlite3.Connection,
) -> None:
    proof = _proof("transaction")

    with pytest.raises(RuntimeError, match="WRITER_TRANSACTION_REQUIRED"):
        insert_agent_workspace_proof_for_connection(connection, proof)

    connection.execute("BEGIN IMMEDIATE")
    inserted = insert_agent_workspace_proof_for_connection(connection, proof)
    assert inserted == proof.runtime_payload()
    assert connection.in_transaction is True
    connection.rollback()
    assert (
        fetch_agent_workspace_proof_by_id_for_connection(
            connection, proof.workspaceProofId
        )
        is None
    )


def test_exact_replay_returns_existing_without_appending_duplicate(
    connection: sqlite3.Connection,
) -> None:
    proof = _proof("replay")

    connection.execute("BEGIN IMMEDIATE")
    first = insert_agent_workspace_proof_for_connection(connection, proof)
    replay = resolve_agent_workspace_proof_replay_for_connection(connection, proof)
    second = insert_agent_workspace_proof_for_connection(connection, proof)

    assert replay == first == second == proof.runtime_payload()
    assert (
        connection.execute("SELECT COUNT(*) FROM agent_workspace_proofs").fetchone()[0]
        == 1
    )
    connection.commit()


def test_same_attempt_lease_ordinal_with_different_payload_is_conflict(
    connection: sqlite3.Connection,
) -> None:
    first = _proof("ordinal-first")
    conflicting = _proof("ordinal-conflicting")

    connection.execute("BEGIN IMMEDIATE")
    insert_agent_workspace_proof_for_connection(connection, first)
    with pytest.raises(
        AgentWorkspaceProofStorageConflictError,
        match="AGENT_WORKSPACE_PROOF_ORDINAL_CONFLICT",
    ):
        insert_agent_workspace_proof_for_connection(connection, conflicting)
    connection.rollback()


def test_different_payload_reusing_another_unique_key_is_stable_conflict(
    connection: sqlite3.Connection,
) -> None:
    first = _proof("unique-first")
    conflicting = _proof(
        "unique-conflicting",
        process_boundary="pre_run",
        process_ordinal=2,
        previous_proof_hash=first.proofHash,
        event_id=first.eventId,
    )

    connection.execute("BEGIN IMMEDIATE")
    insert_agent_workspace_proof_for_connection(connection, first)
    with pytest.raises(
        AgentWorkspaceProofStorageConflictError,
        match="AGENT_WORKSPACE_PROOF_UNIQUE_CONFLICT",
    ):
        insert_agent_workspace_proof_for_connection(connection, conflicting)
    connection.rollback()


def test_row_read_rejects_tampered_manifest_json(
    connection: sqlite3.Connection,
) -> None:
    proof = _proof("tampered-row")
    _insert(connection, proof)

    connection.execute("DROP TRIGGER agent_workspace_proofs_no_update")
    connection.execute(
        """
        UPDATE agent_workspace_proofs
        SET immutable_manifest_json = ?
        WHERE workspace_proof_id = ?
        """,
        (
            json.dumps([{"absoluteWorkDir": "C:/private/workspace"}]),
            proof.workspaceProofId,
        ),
    )
    with pytest.raises(
        AgentWorkspaceProofStorageConflictError,
        match="AGENT_WORKSPACE_PROOF_STORED_PAYLOAD_INVALID",
    ):
        fetch_agent_workspace_proof_by_id_for_connection(
            connection, proof.workspaceProofId
        )


def test_source_terminal_and_resume_chain_are_bound_and_queryable(
    connection: sqlite3.Connection,
) -> None:
    checkpoint = [
        {
            "relativePath": ".snakemake/metadata/state.json",
            "size": 17,
            "sha256": _hash("source-checkpoint"),
        }
    ]
    _activate_lease(connection, SOURCE_ATTEMPT_ID, SOURCE_LEASE_GENERATION)
    source_pre = _proof(
        "source-pre",
        attempt_id=SOURCE_ATTEMPT_ID,
        lease_generation=SOURCE_LEASE_GENERATION,
    )
    source_terminal = _proof(
        "source-terminal",
        attempt_id=SOURCE_ATTEMPT_ID,
        lease_generation=SOURCE_LEASE_GENERATION,
        process_boundary="terminal",
        process_ordinal=2,
        previous_proof_hash=source_pre.proofHash,
        snakemake_manifest=checkpoint,
    )
    connection.execute("BEGIN IMMEDIATE")
    insert_agent_workspace_proof_for_connection(connection, source_pre)
    insert_agent_workspace_proof_for_connection(connection, source_terminal)
    connection.commit()

    _set_resume_job_options(
        connection,
        SOURCE_ATTEMPT_ID,
        SOURCE_LEASE_GENERATION,
    )
    _activate_lease(connection, TARGET_ATTEMPT_ID, TARGET_LEASE_GENERATION)
    resume_pre = _proof(
        "resume-pre",
        source_attempt_id=SOURCE_ATTEMPT_ID,
        previous_proof_hash=source_terminal.proofHash,
        snakemake_manifest=checkpoint,
    )
    resume_terminal = _proof(
        "resume-terminal",
        source_attempt_id=SOURCE_ATTEMPT_ID,
        process_boundary="terminal",
        process_ordinal=2,
        previous_proof_hash=resume_pre.proofHash,
        snakemake_manifest=checkpoint,
    )
    connection.execute("BEGIN IMMEDIATE")
    insert_agent_workspace_proof_for_connection(connection, resume_pre)
    insert_agent_workspace_proof_for_connection(connection, resume_terminal)
    connection.commit()

    assert (
        fetch_terminal_agent_workspace_proof_for_attempt_for_connection(
            connection,
            SOURCE_ATTEMPT_ID,
            lease_generation=SOURCE_LEASE_GENERATION,
        )
        == source_terminal.runtime_payload()
    )
    assert (
        fetch_latest_agent_workspace_proof_for_attempt_for_connection(
            connection,
            TARGET_ATTEMPT_ID,
            lease_generation=TARGET_LEASE_GENERATION,
        )
        == resume_terminal.runtime_payload()
    )


@pytest.mark.parametrize(
    ("proof", "code"),
    [
        (
            _proof("terminal-first", process_boundary="terminal"),
            "FRESH_INITIAL_INVALID",
        ),
        (
            _proof("arbitrary-previous", previous_proof_hash=_hash("arbitrary")),
            "FRESH_INITIAL_INVALID",
        ),
        (
            _proof(
                "cross-run",
                run_id=OTHER_RUN_ID,
                attempt_id=OTHER_ATTEMPT_ID,
                lease_generation=1,
                workflow_revision=OTHER_REVISION,
            ),
            "AUTHORIZATION_BINDING_MISMATCH",
        ),
    ],
)
def test_initial_proof_rejects_terminal_arbitrary_previous_and_cross_authority(
    connection: sqlite3.Connection,
    proof: AgentWorkspaceProofV1,
    code: str,
) -> None:
    _assert_insert_conflict(connection, proof, code)


def test_insert_rejects_stale_or_mismatched_active_lease(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        "UPDATE run_leases SET state = 'expired' WHERE run_id = ?", (RUN_ID,)
    )
    connection.commit()

    _assert_insert_conflict(connection, _proof("stale-lease"), "ACTIVE_LEASE_MISMATCH")


def test_insert_rejects_active_lease_after_its_expiry(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        "UPDATE run_leases SET expires_at = '2000-01-01T00:00:00Z' WHERE run_id = ?",
        (RUN_ID,),
    )
    connection.commit()

    _assert_insert_conflict(
        connection, _proof("expired-active"), "ACTIVE_LEASE_MISMATCH"
    )


def test_resume_rejects_missing_terminal_and_cross_run_source(
    connection: sqlite3.Connection,
) -> None:
    _set_resume_job_options(
        connection,
        SOURCE_ATTEMPT_ID,
        SOURCE_LEASE_GENERATION,
    )
    no_terminal = _proof(
        "no-source-terminal",
        source_attempt_id=SOURCE_ATTEMPT_ID,
        previous_proof_hash=_hash("missing-source-terminal"),
    )
    _assert_insert_conflict(connection, no_terminal, "SOURCE_TERMINAL_REQUIRED")

    _set_resume_job_options(connection, OTHER_ATTEMPT_ID, 1)
    cross_run = _proof(
        "cross-run-source",
        source_attempt_id=OTHER_ATTEMPT_ID,
        previous_proof_hash=_hash("other-terminal"),
    )
    _assert_insert_conflict(connection, cross_run, "SOURCE_ATTEMPT_MISMATCH")


def test_resume_proof_must_match_persisted_job_source(
    connection: sqlite3.Connection,
) -> None:
    _set_resume_job_options(
        connection,
        SOURCE_ATTEMPT_ID,
        SOURCE_LEASE_GENERATION,
    )

    _assert_insert_conflict(
        connection,
        _proof("resume-source-omitted"),
        "JOB_RESUME_SOURCE_MISMATCH",
    )
    _assert_insert_conflict(
        connection,
        _proof(
            "resume-source-substituted",
            source_attempt_id=OTHER_ATTEMPT_ID,
            previous_proof_hash=_hash("other-terminal"),
        ),
        "JOB_RESUME_SOURCE_MISMATCH",
    )


def test_successor_rejects_wrong_previous_and_terminal_successor(
    connection: sqlite3.Connection,
) -> None:
    first = _proof("chain-first")
    _insert(connection, first)
    wrong_previous = _proof(
        "wrong-previous",
        process_boundary="pre_run",
        process_ordinal=2,
        previous_proof_hash=_hash("wrong-previous"),
    )
    _assert_insert_conflict(connection, wrong_previous, "CHAIN_PREVIOUS_HASH_MISMATCH")

    terminal = _proof(
        "chain-terminal",
        process_boundary="terminal",
        process_ordinal=2,
        previous_proof_hash=first.proofHash,
    )
    _insert(connection, terminal)
    after_terminal = _proof(
        "after-terminal",
        process_boundary="pre_run",
        process_ordinal=3,
        previous_proof_hash=terminal.proofHash,
    )
    _assert_insert_conflict(connection, after_terminal, "CHAIN_BOUNDARY_INVALID")


def test_insert_exact_replay_requires_live_lease_and_current_chain_head(
    connection: sqlite3.Connection,
) -> None:
    first = _proof("replay-live-head")
    _insert(connection, first)
    connection.execute(
        "UPDATE run_leases SET expires_at = '2000-01-01T00:00:00Z' WHERE run_id = ?",
        (RUN_ID,),
    )
    connection.commit()

    _assert_insert_conflict(connection, first, "ACTIVE_LEASE_MISMATCH")
    assert resolve_agent_workspace_proof_replay_for_connection(connection, first) == (
        first.runtime_payload()
    )

    connection.execute(
        "UPDATE run_leases SET expires_at = '2099-06-07T11:00:00Z' WHERE run_id = ?",
        (RUN_ID,),
    )
    connection.commit()
    terminal = _proof(
        "replay-terminal-head",
        process_boundary="terminal",
        process_ordinal=2,
        previous_proof_hash=first.proofHash,
    )
    _insert(connection, terminal)

    _assert_insert_conflict(connection, first, "REPLAY_NOT_CHAIN_HEAD")
