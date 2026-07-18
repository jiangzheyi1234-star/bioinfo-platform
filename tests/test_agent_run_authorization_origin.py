from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from apps.remote_runner.agent_run_authorization_origin import (
    AGENT_RUN_AUTHORIZATION_ORIGIN_TRANSACTION_REQUIRED,
    AgentRunAuthorizationOriginIntegrityError,
    require_agent_run_authorization_origin_for_connection,
)
from apps.remote_runner.agent_run_authorization_storage import (
    insert_agent_run_authorization_for_connection,
)
from apps.remote_runner.agent_session_storage import create_agent_session
from apps.remote_runner.event_contracts import append_run_event_v2, record_run_command
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import create_run_record_for_connection
from core.contracts.agent_fastq_qc_execution import (
    AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
    agent_fastq_qc_execution_hash,
    agent_workflow_run_spec_hash,
    build_agent_fastq_qc_execution,
)
from core.contracts.agent_run_authorization import (
    AgentRunAuthorizationReceipt,
    agent_run_authorization_receipt_hash,
    agent_run_authorization_run_idempotency_key,
)
from tests.helpers.reference_database import make_configured_remote_runner


_CREATED_AT = "2099-06-07T10:00:00Z"
_ACTOR = "runner-principal-研究员"


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _seed_origin(tmp_path: Path, suffix: str = "one"):
    cfg = make_configured_remote_runner(tmp_path)
    session = create_agent_session(
        cfg,
        project_id=f"proj_研究_{suffix}",
        goal={"summary": "Inspect FASTQ quality"},
        constraints={"forbiddenActions": ["arbitrary_shell"]},
        budget={
            "maxModelTurns": 8,
            "maxToolCalls": 12,
            "maxReplans": 3,
            "maxRetries": 2,
            "maxWallClockSeconds": 3_600,
        },
        creation_request_id=f"create-{suffix}",
        created_by=_ACTOR,
    )
    plan_id = f"agpr_origin_{suffix}"
    workflow_id = f"wfrev_origin_{suffix}"
    run_id = f"run_origin_{suffix}"
    authorization_id = f"agrauth_origin_{suffix}"
    request_id = f"authorize-origin-{suffix}"
    command_hash = _hash(f"command-{suffix}")
    run_spec = {
        "projectId": f"proj_研究_{suffix}",
        "pipelineId": "generated-tool-run-v1",
        "workflowRevisionId": workflow_id,
        "inputs": [{"role": "reads", "filename": "样本.fastq", "uploadId": "upl_1"}],
        "execution": build_agent_fastq_qc_execution().runtime_payload(),
    }
    run_spec_hash = agent_workflow_run_spec_hash(run_spec)
    receipt_payload: dict[str, object] = {
        "authorizationId": authorization_id,
        "contractVersion": "agent-run-authorization.v1",
        "sessionId": session["sessionId"],
        "previewHash": _hash(f"preview-{suffix}"),
        "planRevisionId": plan_id,
        "planGeneration": 1,
        "planHash": _hash(f"plan-{suffix}"),
        "workflowRevisionId": workflow_id,
        "expectedStateVersion": 5,
        "inputManifestDigest": f"sha256:{_hash(f'input-{suffix}')}",
        "runSpecHash": run_spec_hash,
        "executionPolicyId": AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
        "executionPolicyHash": agent_fastq_qc_execution_hash(run_spec["execution"]),
        "runtimeLockHash": _hash(f"runtime-lock-{suffix}"),
        "runtimeProofHash": _hash(f"runtime-proof-{suffix}"),
        "effectBudgetHash": _hash(f"effect-budget-{suffix}"),
        "runId": run_id,
        "scope": "submit_workflow_run",
        "confirmation": "authorize-workflow-run",
        "actor": _ACTOR,
        "requestId": request_id,
        "idempotencyKey": f"public-idem-{suffix}",
        "commandHash": command_hash,
        "createdAt": _CREATED_AT,
    }
    receipt_payload["receiptHash"] = agent_run_authorization_receipt_hash(
        receipt_payload
    )
    receipt = AgentRunAuthorizationReceipt.model_validate(receipt_payload)
    internal_key = agent_run_authorization_run_idempotency_key(
        session["sessionId"], authorization_id, command_hash
    )
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO agent_plan_revisions (
                plan_revision_id, contract_version, session_id, plan_generation,
                parent_plan_revision_id, draft_id, draft_revision, plan_hash,
                proposal_json, validation_json, budget_json, created_by, created_at
            ) VALUES (?, 'agent-plan-revision.v1', ?, 1, NULL, ?, 1, ?,
                '{}', '{}', '{}', ?, ?)
            """,
            (
                plan_id,
                session["sessionId"],
                f"draft_origin_{suffix}",
                receipt.planHash,
                _ACTOR,
                _CREATED_AT,
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
                workflow_id,
                f"draft_origin_{suffix}",
                _hash(f"workflow-{suffix}"),
                _ACTOR,
                _CREATED_AT,
            ),
        )
        create_run_record_for_connection(
            connection,
            server_id="agent-control-plane.v1",
            actor=_ACTOR,
            request_id=request_id,
            run_spec=run_spec,
            idempotency_key=internal_key,
            payload_hash=run_spec_hash,
            run_id=run_id,
            submitted_at=_CREATED_AT,
        )
        insert_agent_run_authorization_for_connection(connection, receipt)
        connection.commit()
    return cfg, receipt


def _require(cfg, authorization_id: str):
    with get_connection(cfg) as connection:
        connection.execute("BEGIN")
        result = require_agent_run_authorization_origin_for_connection(
            connection, authorization_id
        )
        connection.rollback()
        return result


def test_origin_accepts_exact_non_ascii_creation_chain(tmp_path: Path) -> None:
    cfg, receipt = _seed_origin(tmp_path)

    result = _require(cfg, receipt.authorizationId)

    assert result["authorizationId"] == receipt.authorizationId
    assert result["runId"] == receipt.runId
    assert result["runSpecHash"] == receipt.runSpecHash


def test_origin_requires_caller_transaction_and_binding_first(tmp_path: Path) -> None:
    cfg, receipt = _seed_origin(tmp_path)
    with get_connection(cfg) as connection:
        with pytest.raises(
            AgentRunAuthorizationOriginIntegrityError,
            match=AGENT_RUN_AUTHORIZATION_ORIGIN_TRANSACTION_REQUIRED,
        ):
            require_agent_run_authorization_origin_for_connection(
                connection, receipt.authorizationId
            )

        connection.execute("BEGIN")
        with pytest.raises(AgentRunAuthorizationOriginIntegrityError) as caught:
            require_agent_run_authorization_origin_for_connection(
                connection, "agrauth_missing"
            )
        assert caught.value.component == "binding"
        connection.rollback()


def test_origin_allows_mutable_lifecycle_and_later_command_events(
    tmp_path: Path,
) -> None:
    cfg, receipt = _seed_origin(tmp_path)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            UPDATE runs SET status = 'running', stage = 'execute', state_version = 2,
                message = 'Running', started_at = ?, finished_at = NULL,
                result_dir = 'results', last_error_json = '{}', last_updated_at = ?
            WHERE run_id = ?
            """,
            (_CREATED_AT, "2099-06-07T10:00:01Z", receipt.runId),
        )
        connection.execute(
            """
            UPDATE run_jobs SET state = 'claimed', available_at = ?,
                wait_reason_json = '{"reason":"worker"}', attempt_count = 1,
                execution_options_json = '{"resume":true}',
                dead_lettered_at = NULL, updated_at = ? WHERE run_id = ?
            """,
            (_CREATED_AT, "2099-06-07T10:00:01Z", receipt.runId),
        )
        command = record_run_command(
            connection,
            run_id=receipt.runId,
            command_type="cancel_run",
            payload={"runId": receipt.runId},
            actor=_ACTOR,
            requested_at="2099-06-07T10:00:02Z",
        )
        append_run_event_v2(
            connection,
            run_id=receipt.runId,
            event_type="cancel_requested",
            from_status="running",
            to_status="canceling",
            stage="canceling",
            state_version=3,
            message="Cancellation requested.",
            request_id=receipt.requestId,
            command_id=command["commandId"],
            actor=_ACTOR,
            payload={"runId": receipt.runId},
            occurred_at="2099-06-07T10:00:02Z",
            command_derived=True,
        )
        connection.commit()

    assert _require(cfg, receipt.authorizationId)["runId"] == receipt.runId


@pytest.mark.parametrize(
    ("component", "statement"),
    [
        (
            "run",
            "UPDATE runs SET server_id = 'agent-control-plane.v01' WHERE run_id = ?",
        ),
        ("submit_command", "UPDATE run_commands SET actor = 'alias' WHERE run_id = ?"),
        (
            "accepted_event",
            "UPDATE run_events SET stage = 'alias' WHERE run_id = ? AND seq = 1",
        ),
        ("queued_event", "DELETE FROM run_events WHERE run_id = ? AND seq = 2"),
        ("job", "UPDATE run_jobs SET priority = 1 WHERE run_id = ?"),
        ("idempotency", "UPDATE idempotency SET status = 'alias' WHERE run_id = ?"),
        (
            "event_chain",
            "UPDATE run_events SET event_hash = 'alias' WHERE run_id = ? AND seq = 1",
        ),
    ],
)
def test_origin_rejects_each_creation_component(
    tmp_path: Path,
    component: str,
    statement: str,
) -> None:
    cfg, receipt = _seed_origin(tmp_path, component)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(statement, (receipt.runId,))
        connection.commit()

    with pytest.raises(AgentRunAuthorizationOriginIntegrityError) as caught:
        _require(cfg, receipt.authorizationId)
    assert caught.value.component == component


def test_origin_rejects_duplicate_creation_rows_but_allows_later_types(
    tmp_path: Path,
) -> None:
    cfg, receipt = _seed_origin(tmp_path, "duplicates")
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        original = connection.execute(
            "SELECT * FROM run_commands WHERE run_id = ?", (receipt.runId,)
        ).fetchone()
        connection.execute(
            """
            INSERT INTO run_commands (
                command_id, run_id, command_type, idempotency_key, actor,
                payload_json, payload_hash, requested_at
            ) VALUES ('cmd_duplicate', ?, 'submit_run', 'duplicate', ?, ?, ?, ?)
            """,
            (
                receipt.runId,
                original["actor"],
                original["payload_json"],
                original["payload_hash"],
                original["requested_at"],
            ),
        )
        connection.commit()

    with pytest.raises(AgentRunAuthorizationOriginIntegrityError) as caught:
        _require(cfg, receipt.authorizationId)
    assert caught.value.component == "submit_command"


def test_origin_rejects_internal_command_key_alias_on_another_run(
    tmp_path: Path,
) -> None:
    cfg, receipt = _seed_origin(tmp_path, "command-alias")
    internal_key = agent_run_authorization_run_idempotency_key(
        receipt.sessionId,
        receipt.authorizationId,
        receipt.commandHash,
    )
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        original = connection.execute(
            "SELECT * FROM run_commands WHERE run_id = ?", (receipt.runId,)
        ).fetchone()
        connection.execute(
            """
            INSERT INTO run_commands (
                command_id, run_id, command_type, idempotency_key, actor,
                payload_json, payload_hash, requested_at
            ) VALUES ('cmd_cross_run_alias', 'run_other', 'submit_run', ?, ?, ?, ?, ?)
            """,
            (
                internal_key,
                original["actor"],
                original["payload_json"],
                original["payload_hash"],
                original["requested_at"],
            ),
        )
        connection.commit()

    with pytest.raises(AgentRunAuthorizationOriginIntegrityError) as caught:
        _require(cfg, receipt.authorizationId)
    assert caught.value.component == "submit_command"


@pytest.mark.parametrize("sequence", [0, -1])
def test_origin_rejects_detached_non_positive_event_sequence(
    tmp_path: Path,
    sequence: int,
) -> None:
    cfg, receipt = _seed_origin(tmp_path, f"detached-{sequence}")
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO run_events (
                event_id, run_id, event_type, seq, schema_version, stage,
                state_version, message, request_id, payload_hash, event_hash,
                created_at, details_json
            ) VALUES (?, ?, 'detached', ?, 'run-event.v2', 'detached', 1,
                'Detached event', ?, 'detached-payload', 'detached-event', ?, '{}')
            """,
            (
                f"evt_detached_{abs(sequence)}",
                receipt.runId,
                sequence,
                receipt.requestId,
                _CREATED_AT,
            ),
        )
        connection.commit()

    with pytest.raises(AgentRunAuthorizationOriginIntegrityError) as caught:
        _require(cfg, receipt.authorizationId)
    assert caught.value.component == "event_chain"


def test_origin_wraps_invalid_json_with_stable_component(tmp_path: Path) -> None:
    cfg, receipt = _seed_origin(tmp_path, "json")
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE run_commands SET payload_json = '{' WHERE run_id = ?",
            (receipt.runId,),
        )
        connection.commit()

    with pytest.raises(AgentRunAuthorizationOriginIntegrityError) as caught:
        _require(cfg, receipt.authorizationId)
    assert caught.value.component == "submit_command"
