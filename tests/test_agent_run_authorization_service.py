from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

import apps.remote_runner.agent_run_authorization_service as service
from apps.remote_runner.agent_run_authorization_authority import (
    prepare_agent_run_authorization_authority,
)
from apps.remote_runner.agent_run_authorization_origin import (
    AgentRunAuthorizationOriginIntegrityError,
)
from apps.remote_runner.agent_run_authorization_storage import (
    AgentRunAuthorizationStorageConflictError,
)
from apps.remote_runner.errors import (
    RemoteRunnerAuthorizationError,
    WorkflowDesignRevisionConflictError,
)
from apps.remote_runner.storage_core import get_connection
from core.contracts.agent_run_authorization import AgentRunAuthorizationResult


pytest_plugins = ("tests.test_agent_fastq_qc_execution_candidate",)


def _request(preview: dict[str, Any], *, suffix: str = "one") -> dict[str, Any]:
    return {
        "expectedStateVersion": preview["stateVersion"],
        "expectedPlanRevisionId": preview["planRevisionId"],
        "expectedPlanGeneration": preview["planGeneration"],
        "expectedPlanHash": preview["planHash"],
        "expectedWorkflowRevisionId": preview["workflowRevisionId"],
        "expectedPreviewHash": preview["previewHash"],
        "expectedInputManifestDigest": preview["inputManifestDigest"],
        "expectedRunSpecHash": preview["runSpecHash"],
        "expectedExecutionPolicyHash": preview["executionPolicyHash"],
        "expectedRuntimeProofHash": preview["runtimeProofHash"],
        "confirmation": "authorize-workflow-run",
        "requestId": f"authorize-agent-run-{suffix}",
        "idempotencyKey": f"authorize-agent-run-{suffix}",
    }


def _preview(candidate_case: dict[str, Any]) -> dict[str, Any]:
    return prepare_agent_run_authorization_authority(
        candidate_case["cfg"],
        candidate_case["session"]["sessionId"],
        actor="user-1",
    ).preview


def _ledger_counts(cfg: Any) -> tuple[int, ...]:
    with get_connection(cfg) as connection:
        return tuple(
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "runs",
                "run_commands",
                "run_events",
                "run_jobs",
                "idempotency",
                "agent_run_authorizations",
            )
        )


def test_authorize_fresh_then_fast_replay_without_candidate_and_with_current_run(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    request = _request(_preview(candidate_case))

    fresh = service.authorize_agent_workflow_run(
        cfg,
        session_id,
        request,
        actor="user-1",
    )

    assert AgentRunAuthorizationResult.model_validate(fresh).runtime_payload() == fresh
    assert fresh["contractVersion"] == "agent-run-authorization-result.v1"
    assert fresh["idempotencyReplay"] is False
    assert fresh["authorization"]["runId"] == fresh["run"]["runId"]
    assert _ledger_counts(cfg) == (1, 1, 2, 1, 1, 1)

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            UPDATE runs SET status = 'running', stage = 'execution',
                state_version = 2, message = '', last_updated_at = ?
            WHERE run_id = ?
            """,
            ("2099-07-19T01:02:03Z", fresh["run"]["runId"]),
        )
        connection.commit()

    monkeypatch.setattr(
        service,
        "prepare_agent_run_authorization_authority",
        lambda *_args, **_kwargs: pytest.fail("exact replay must not build candidate"),
    )
    replay = service.authorize_agent_workflow_run(
        cfg,
        session_id,
        request,
        actor="user-1",
    )

    assert replay["idempotencyReplay"] is True
    assert replay["authorization"] == fresh["authorization"]
    assert replay["run"]["status"] == "running"
    assert replay["run"]["stateVersion"] == 2
    assert replay["run"]["message"] == ""
    assert replay["run"]["lastUpdatedAt"] == "2099-07-19T01:02:03Z"
    assert _ledger_counts(cfg) == (1, 1, 2, 1, 1, 1)


def test_authorize_rejects_different_command_and_stale_preview_without_writes(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    request = _request(_preview(candidate_case))
    service.authorize_agent_workflow_run(cfg, session_id, request, actor="user-1")
    before = _ledger_counts(cfg)

    changed = deepcopy(request)
    changed["requestId"] = "authorize-agent-run-different"
    with pytest.raises(
        AgentRunAuthorizationStorageConflictError,
        match="AGENT_RUN_AUTHORIZATION_IDEMPOTENCY_CONFLICT",
    ):
        service.authorize_agent_workflow_run(
            cfg,
            session_id,
            changed,
            actor="user-1",
        )
    assert _ledger_counts(cfg) == before


def test_authorize_rejects_stale_expected_value_and_wrong_owner_before_writes(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    request = _request(_preview(candidate_case))
    request["expectedStateVersion"] += 1

    with pytest.raises(
        WorkflowDesignRevisionConflictError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_MISMATCH",
    ):
        service.authorize_agent_workflow_run(
            cfg,
            session_id,
            request,
            actor="user-1",
        )
    with pytest.raises(
        RemoteRunnerAuthorizationError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_OWNER_MISMATCH",
    ):
        service.authorize_agent_workflow_run(
            cfg,
            session_id,
            _request(_preview(candidate_case), suffix="owner"),
            actor="other-user",
        )
    assert _ledger_counts(cfg) == (0, 0, 0, 0, 0, 0)


def test_authorize_rejects_nested_candidate_mutation_and_writer_authority_drift(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    prepared = prepare_agent_run_authorization_authority(
        cfg,
        session_id,
        actor="user-1",
    )
    request = _request(prepared.preview)
    run_spec = deepcopy(prepared.candidate.run_spec)
    run_spec["execution"]["retryPolicy"]["maxAttempts"] = 2
    mutated = replace(prepared.candidate, run_spec=run_spec)
    monkeypatch.setattr(
        service,
        "prepare_agent_run_authorization_authority",
        lambda *_args, **_kwargs: replace(prepared, candidate=mutated),
    )
    with pytest.raises(
        RuntimeError,
        match="AGENT_RUN_AUTHORIZATION_CANDIDATE_INTEGRITY_MISMATCH",
    ):
        service.authorize_agent_workflow_run(
            cfg,
            session_id,
            request,
            actor="user-1",
        )
    assert _ledger_counts(cfg) == (0, 0, 0, 0, 0, 0)

    monkeypatch.setattr(
        service,
        "prepare_agent_run_authorization_authority",
        lambda *_args, **_kwargs: prepared,
    )
    original_reader = service.read_agent_run_authorization_authority_for_connection

    def drifted_reader(*args: Any, **kwargs: Any) -> Any:
        snapshot = original_reader(*args, **kwargs)
        session = dict(snapshot.session)
        session["stateVersion"] += 1
        return replace(snapshot, session=session)

    monkeypatch.setattr(
        service,
        "read_agent_run_authorization_authority_for_connection",
        drifted_reader,
    )
    with pytest.raises(
        WorkflowDesignRevisionConflictError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_AUTHORITY_CHANGED",
    ):
        service.authorize_agent_workflow_run(
            cfg,
            session_id,
            request,
            actor="user-1",
        )
    assert _ledger_counts(cfg) == (0, 0, 0, 0, 0, 0)


def test_authorize_rolls_back_when_commit_time_origin_proof_fails(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    request = _request(_preview(candidate_case))
    original_insert = service.insert_agent_run_authorization_for_connection

    def insert_then_tamper(connection: Any, receipt: Any) -> dict[str, Any]:
        inserted = original_insert(connection, receipt)
        connection.execute(
            "UPDATE run_commands SET actor = 'tampered' WHERE run_id = ?",
            (inserted["runId"],),
        )
        return inserted

    monkeypatch.setattr(
        service,
        "insert_agent_run_authorization_for_connection",
        insert_then_tamper,
    )
    with pytest.raises(AgentRunAuthorizationOriginIntegrityError):
        service.authorize_agent_workflow_run(
            cfg,
            session_id,
            request,
            actor="user-1",
        )
    assert _ledger_counts(cfg) == (0, 0, 0, 0, 0, 0)


def test_authorize_rechecks_candidate_after_preview_helper_returns(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    request = _request(_preview(candidate_case), suffix="helper-mutation")
    original_builder = service.build_agent_run_authorization_preview_payload

    def mutating_builder(snapshot: Any, candidate: Any) -> dict[str, Any]:
        preview = original_builder(snapshot, candidate)
        candidate.run_spec["inputs"][0]["filename"] = "mutated.fastq"
        return preview

    monkeypatch.setattr(
        service,
        "build_agent_run_authorization_preview_payload",
        mutating_builder,
    )

    with pytest.raises(
        RuntimeError,
        match="AGENT_RUN_AUTHORIZATION_CANDIDATE_INTEGRITY_MISMATCH",
    ):
        service.authorize_agent_workflow_run(
            cfg,
            session_id,
            request,
            actor="user-1",
        )
    assert _ledger_counts(cfg) == (0, 0, 0, 0, 0, 0)
