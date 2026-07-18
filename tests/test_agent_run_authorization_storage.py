from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.remote_runner.agent_run_authorization_storage import (
    AgentRunAuthorizationStorageConflictError,
    AgentRunAuthorizationStorageNotFoundError,
    count_agent_run_authorizations_for_connection,
    fetch_agent_run_authorization_by_run_for_connection,
    fetch_agent_run_authorization_by_session_for_connection,
    insert_agent_run_authorization_for_connection,
    read_agent_run_authorization_for_connection,
    resolve_agent_run_authorization_replay_for_connection,
)
from apps.remote_runner.agent_session_storage import create_agent_session
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.storage_core import get_connection
from core.contracts.agent_run_authorization import (
    AgentRunAuthorizationReceipt,
    agent_run_authorization_receipt_hash,
)
from tests.helpers.reference_database import make_remote_runner_config


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _configured_runner(tmp_path: Path):
    cfg = make_remote_runner_config(tmp_path)
    ensure_runtime_layout(cfg)
    return cfg


def _seed_dependencies(cfg, suffix: str) -> dict[str, str]:
    session = create_agent_session(
        cfg,
        project_id=f"proj_auth_{suffix}",
        goal={"summary": f"Inspect FASTQ quality {suffix}"},
        constraints={"forbiddenActions": ["arbitrary_shell"]},
        budget={
            "maxModelTurns": 8,
            "maxToolCalls": 12,
            "maxReplans": 3,
            "maxRetries": 2,
            "maxWallClockSeconds": 3_600,
        },
        creation_request_id=f"create-auth-{suffix}",
        created_by="runner-principal",
    )
    plan_revision_id = f"agpr_auth_{suffix}"
    workflow_revision_id = f"wfrev_auth_{suffix}"
    run_id = f"run_auth_{suffix}"
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO agent_plan_revisions (
                plan_revision_id, contract_version, session_id, plan_generation,
                parent_plan_revision_id, draft_id, draft_revision, plan_hash,
                proposal_json, validation_json, budget_json, created_by, created_at
            ) VALUES (?, 'agent-plan-revision.v1', ?, 1, NULL, ?, 1, ?, '{}', '{}', '{}', ?, ?)
            """,
            (
                plan_revision_id,
                session["sessionId"],
                f"draft_auth_{suffix}",
                _hash(f"plan-{suffix}"),
                "fixture.fastq-qc.v1",
                "2099-06-07T10:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO workflow_revisions (
                workflow_revision_id, draft_id, draft_revision, content_hash,
                manifest_json, graph_snapshot_json, runtime_lock_json,
                compiler_json, created_by, created_at
            ) VALUES (?, ?, 1, ?, '{}', '{}', '{}', '{}', ?, ?)
            """,
            (
                workflow_revision_id,
                f"draft_auth_{suffix}",
                _hash(f"workflow-{suffix}"),
                "fixture.fastq-qc.v1",
                "2099-06-07T10:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO runs (
                run_id, server_id, project_id, pipeline_id, pipeline_version,
                run_spec_version, workflow_revision_id, status, stage,
                state_version, message, result_dir, last_updated_at, request_id,
                submitted_at, run_spec_json
            ) VALUES (?, 'agent-control-plane.v1', ?, 'generated-tool-run-v1',
                '1.0.0', '2026-04-21', ?, 'queued', 'queued', 1, 'Accepted',
                '', ?, ?, ?, '{}')
            """,
            (
                run_id,
                session["projectId"],
                workflow_revision_id,
                "2099-06-07T10:00:00Z",
                f"submit-auth-{suffix}",
                "2099-06-07T10:00:00Z",
            ),
        )
        connection.commit()
    return {
        "sessionId": session["sessionId"],
        "planRevisionId": plan_revision_id,
        "planHash": _hash(f"plan-{suffix}"),
        "workflowRevisionId": workflow_revision_id,
        "runId": run_id,
    }


def _receipt(
    dependencies: dict[str, str],
    *,
    suffix: str,
    authorization_id: str | None = None,
    run_id: str | None = None,
) -> AgentRunAuthorizationReceipt:
    payload: dict[str, object] = {
        "authorizationId": authorization_id or f"agrauth_{suffix}",
        "contractVersion": "agent-run-authorization.v1",
        "sessionId": dependencies["sessionId"],
        "previewHash": _hash(f"preview-{suffix}"),
        "planRevisionId": dependencies["planRevisionId"],
        "planGeneration": 1,
        "planHash": dependencies["planHash"],
        "workflowRevisionId": dependencies["workflowRevisionId"],
        "expectedStateVersion": 5,
        "inputManifestDigest": f"sha256:{_hash(f'input-{suffix}')}",
        "runSpecHash": _hash(f"run-spec-{suffix}"),
        "executionPolicyId": "agent-fastq-qc-execution.v1",
        "executionPolicyHash": _hash(f"policy-{suffix}"),
        "runtimeLockHash": _hash(f"runtime-lock-{suffix}"),
        "runtimeProofHash": _hash(f"runtime-proof-{suffix}"),
        "effectBudgetHash": _hash(f"effect-budget-{suffix}"),
        "runId": run_id or dependencies["runId"],
        "scope": "submit_workflow_run",
        "confirmation": "authorize-workflow-run",
        "actor": "runner-principal",
        "requestId": f"authorize-request-{suffix}",
        "idempotencyKey": f"authorize-idem-{suffix}",
        "commandHash": _hash(f"command-{suffix}"),
        "createdAt": "2099-06-07T10:00:00Z",
    }
    payload["receiptHash"] = agent_run_authorization_receipt_hash(payload)
    return AgentRunAuthorizationReceipt.model_validate(payload)


def _insert(cfg, receipt: AgentRunAuthorizationReceipt) -> dict:
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        result = insert_agent_run_authorization_for_connection(connection, receipt)
        connection.commit()
    return result


def test_authorization_connection_primitives_insert_fetch_count_replay_and_read(
    tmp_path: Path,
) -> None:
    cfg = _configured_runner(tmp_path)
    dependencies = _seed_dependencies(cfg, "one")
    receipt = _receipt(dependencies, suffix="one")

    with get_connection(cfg) as connection:
        with pytest.raises(
            AgentRunAuthorizationStorageNotFoundError,
            match="AGENT_SESSION_NOT_FOUND",
        ):
            read_agent_run_authorization_for_connection(connection, "ags_missing")
        assert read_agent_run_authorization_for_connection(
            connection, dependencies["sessionId"]
        ) == {
            "contractVersion": "agent-run-authorization-read.v1",
            "sessionId": dependencies["sessionId"],
            "state": "absent",
        }
        with pytest.raises(RuntimeError, match="WRITER_TRANSACTION_REQUIRED"):
            insert_agent_run_authorization_for_connection(connection, receipt)

    inserted = _insert(cfg, receipt)
    with get_connection(cfg) as connection:
        assert fetch_agent_run_authorization_by_session_for_connection(
            connection, dependencies["sessionId"]
        ) == inserted
        assert fetch_agent_run_authorization_by_run_for_connection(
            connection, dependencies["runId"]
        ) == inserted
        assert count_agent_run_authorizations_for_connection(
            connection, dependencies["sessionId"]
        ) == 1
        assert resolve_agent_run_authorization_replay_for_connection(
            connection,
            session_id=dependencies["sessionId"],
            idempotency_key=receipt.idempotencyKey,
            actor=receipt.actor,
            command_hash=receipt.commandHash,
        ) == inserted
        assert read_agent_run_authorization_for_connection(
            connection, dependencies["sessionId"]
        )["state"] == "present"
        with pytest.raises(
            AgentRunAuthorizationStorageConflictError,
            match="IDEMPOTENCY_CONFLICT",
        ):
            resolve_agent_run_authorization_replay_for_connection(
                connection,
                session_id=dependencies["sessionId"],
                idempotency_key=receipt.idempotencyKey,
                actor=receipt.actor,
                command_hash=_hash("different-command"),
            )


def test_authorization_unique_session_and_run_and_immutable(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    first = _seed_dependencies(cfg, "first")
    second = _seed_dependencies(cfg, "second")
    first_receipt = _receipt(first, suffix="first")
    _insert(cfg, first_receipt)

    same_session = _receipt(
        first | {"runId": second["runId"]},
        suffix="same-session",
        authorization_id="agrauth_same_session",
        run_id=second["runId"],
    )
    with pytest.raises(AgentRunAuthorizationStorageConflictError, match="STORAGE_CONFLICT"):
        _insert(cfg, same_session)

    same_run = _receipt(
        second,
        suffix="same-run",
        authorization_id="agrauth_same_run",
        run_id=first["runId"],
    )
    with pytest.raises(AgentRunAuthorizationStorageConflictError, match="STORAGE_CONFLICT"):
        _insert(cfg, same_run)

    with get_connection(cfg) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_RUN_AUTHORIZATION_IMMUTABLE"):
            connection.execute(
                "UPDATE agent_run_authorizations SET actor = 'tampered' WHERE authorization_id = ?",
                (first_receipt.authorizationId,),
            )
    with get_connection(cfg) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_RUN_AUTHORIZATION_IMMUTABLE"):
            connection.execute(
                "DELETE FROM agent_run_authorizations WHERE authorization_id = ?",
                (first_receipt.authorizationId,),
            )
    with get_connection(cfg) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="AGENT_BOUND_RUN_DELETE_FORBIDDEN"):
            connection.execute("DELETE FROM runs WHERE run_id = ?", (first["runId"],))


def test_authorization_row_conversion_rejects_tampered_receipt_hash(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    dependencies = _seed_dependencies(cfg, "tamper")
    receipt = _receipt(dependencies, suffix="tamper")
    _insert(cfg, receipt)

    with get_connection(cfg) as connection:
        connection.execute("DROP TRIGGER agent_run_authorizations_no_update")
        connection.execute(
            "UPDATE agent_run_authorizations SET receipt_hash = ? WHERE authorization_id = ?",
            ("0" * 64, receipt.authorizationId),
        )
        with pytest.raises(
            AgentRunAuthorizationStorageConflictError,
            match="STORED_RECEIPT_HASH_MISMATCH",
        ):
            fetch_agent_run_authorization_by_session_for_connection(
                connection,
                dependencies["sessionId"],
            )


def test_authorization_insert_leaves_commit_and_rollback_to_caller(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    dependencies = _seed_dependencies(cfg, "caller-rollback")
    receipt = _receipt(dependencies, suffix="caller-rollback")

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        insert_agent_run_authorization_for_connection(connection, receipt)
        assert connection.in_transaction is True
        connection.rollback()
        assert fetch_agent_run_authorization_by_session_for_connection(
            connection,
            dependencies["sessionId"],
        ) is None


def test_authorization_unique_conflict_does_not_end_caller_transaction(
    tmp_path: Path,
) -> None:
    cfg = _configured_runner(tmp_path)
    dependencies = _seed_dependencies(cfg, "caller-conflict")
    receipt = _receipt(dependencies, suffix="caller-conflict")

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        insert_agent_run_authorization_for_connection(connection, receipt)
        with pytest.raises(
            AgentRunAuthorizationStorageConflictError,
            match="STORAGE_CONFLICT",
        ):
            insert_agent_run_authorization_for_connection(connection, receipt)
        assert connection.in_transaction is True
        connection.rollback()
        assert fetch_agent_run_authorization_by_session_for_connection(
            connection,
            dependencies["sessionId"],
        ) is None


def test_authorization_insert_revalidates_mutated_receipt_instance(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    dependencies = _seed_dependencies(cfg, "mutated-receipt")
    receipt = _receipt(dependencies, suffix="mutated-receipt")
    receipt.__dict__["scope"] = "tampered-scope"
    receipt.__dict__["receiptHash"] = agent_run_authorization_receipt_hash(
        receipt.runtime_payload()
    )

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValidationError):
            insert_agent_run_authorization_for_connection(connection, receipt)
        assert connection.in_transaction is True
        connection.rollback()
        assert fetch_agent_run_authorization_by_session_for_connection(
            connection,
            dependencies["sessionId"],
        ) is None
