from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

import apps.remote_runner.agent_run_authorization_authority as authority
import apps.remote_runner.agent_run_authorization_preview_service as preview_service
from apps.remote_runner.errors import (
    RemoteRunnerAuthorizationError,
    WorkflowDesignRevisionConflictError,
)
from apps.remote_runner.main import app
from apps.remote_runner.storage import get_connection, list_runs
from core.contracts.agent_effect_budget import agent_effect_budget_hash
from core.contracts.agent_fastq_qc_execution import (
    AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
    agent_fastq_qc_execution_hash,
)
from core.contracts.agent_run_authorization_preview import (
    AgentRunAuthorizationPreview,
    agent_run_authorization_preview_hash,
)


pytest_plugins = ("tests.test_agent_fastq_qc_execution_candidate",)


def test_preview_is_deterministic_complete_path_free_and_read_only(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    before = _ledger_counts(cfg)

    first = preview_service.build_agent_run_authorization_preview(
        cfg,
        candidate_case["session"]["sessionId"],
        actor="user-1",
    )
    second = preview_service.build_agent_run_authorization_preview(
        cfg,
        candidate_case["session"]["sessionId"],
        actor="user-1",
    )

    assert first == second
    assert AgentRunAuthorizationPreview.model_validate(first).runtime_payload() == first
    assert agent_run_authorization_preview_hash(first) == first["previewHash"]
    assert first["sessionId"] == candidate_case["session"]["sessionId"]
    assert first["stateVersion"] == candidate_case["session"]["stateVersion"]
    assert first["planRevisionId"] == candidate_case["plan"]["planRevisionId"]
    assert first["planHash"] == candidate_case["plan"]["planHash"]
    assert (
        first["workflowRevisionId"] == candidate_case["revision"]["workflowRevisionId"]
    )
    assert (
        first["workflowRevisionContentHash"]
        == candidate_case["revision"]["contentHash"]
    )
    assert first["effectBudgetHash"] == agent_effect_budget_hash(
        candidate_case["effect_budget"]
    )
    assert first["maxRunSubmissions"] == 1
    assert first["usedRunSubmissions"] == 0
    assert first["remainingRunSubmissions"] == 1
    assert first["executionPolicyId"] == AGENT_FASTQ_QC_EXECUTION_POLICY_ID
    assert first["executionPolicyHash"] == agent_fastq_qc_execution_hash(
        first["executionPolicy"]
    )
    assert first["executionPolicy"] == {
        "queueName": "default",
        "retryPolicy": {
            "schemaVersion": "execution-retry-policy.v1",
            "maxAttempts": 3,
            "backoffSeconds": 5,
        },
        "timeoutPolicy": {
            "schemaVersion": "execution-timeout-policy.v1",
            "queueTtlSeconds": 0,
            "startToCloseTimeoutSeconds": 0,
            "heartbeatTimeoutSeconds": 60,
        },
    }
    assert [item["stepId"] for item in first["tools"]] == ["fastqc", "multiqc"]
    assert [item["stepId"] for item in first["resources"]["orderedSteps"]] == [
        "fastqc",
        "multiqc",
    ]
    assert first["consequenceCode"] == "create-and-enqueue-one-workflow-run"
    assert "runSpec" not in first

    serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
    for host_path in _host_paths(candidate_case):
        assert str(host_path) not in serialized
    assert not _keys_matching(first, _unsafe_public_key)
    assert _ledger_counts(cfg) == before
    assert list_runs(cfg) == []


def test_preview_http_uses_authenticated_owner_and_operator_policy(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    client = TestClient(app)

    response = client.get(
        f"/api/v1/agent-sessions/{session_id}/run-authorization-preview",
        headers={"Authorization": "Bearer workflow-design-token"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["sessionId"] == session_id
    cfg.api_token_actor = "different-owner"
    denied = client.get(
        f"/api/v1/agent-sessions/{session_id}/run-authorization-preview",
        headers={"Authorization": "Bearer workflow-design-token"},
    )
    assert denied.status_code == 403
    assert "AGENT_RUN_AUTHORIZATION_PREVIEW_OWNER_MISMATCH" in denied.text


@pytest.mark.parametrize(
    ("change", "error_code"),
    [
        ("missing-budget", "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_REQUIRED"),
        (
            "wrong-budget-owner",
            "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_OWNER_MISMATCH",
        ),
        ("existing-binding", "AGENT_RUN_AUTHORIZATION_ALREADY_BOUND"),
        ("used-budget", "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_EXHAUSTED"),
    ],
)
def test_preview_admission_fails_closed_before_candidate_build(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    error_code: str,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    snapshot = authority.read_agent_run_authorization_authority(cfg, session_id)
    if change == "missing-budget":
        changed = replace(snapshot, effect_budget=None)
    elif change == "wrong-budget-owner":
        budget = dict(snapshot.effect_budget or {})
        budget["actor"] = "different-owner"
        changed = replace(snapshot, effect_budget=budget)
    elif change == "existing-binding":
        changed = replace(snapshot, existing_binding={"authorizationId": "auth_1"})
    else:
        changed = replace(snapshot, used_authorization_count=1)
    monkeypatch.setattr(
        authority,
        "read_agent_run_authorization_authority",
        lambda _cfg, _session_id: changed,
    )
    monkeypatch.setattr(
        authority,
        "build_agent_fastq_qc_execution_candidate",
        lambda *_args, **_kwargs: pytest.fail("candidate must not be built"),
    )

    with pytest.raises(WorkflowDesignRevisionConflictError, match=error_code):
        preview_service.build_agent_run_authorization_preview(
            cfg,
            session_id,
            actor="user-1",
        )


def test_preview_rejects_owner_and_authority_drift(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    with pytest.raises(
        RemoteRunnerAuthorizationError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_OWNER_MISMATCH",
    ):
        preview_service.build_agent_run_authorization_preview(
            cfg,
            session_id,
            actor="different-owner",
        )

    original_read = authority.read_agent_run_authorization_authority
    first = original_read(cfg, session_id)
    drifted_session = dict(first.session)
    drifted_session["stateVersion"] += 1
    snapshots = iter((first, replace(first, session=drifted_session)))
    monkeypatch.setattr(
        authority,
        "read_agent_run_authorization_authority",
        lambda _cfg, _session_id: next(snapshots),
    )
    with pytest.raises(
        WorkflowDesignRevisionConflictError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_AUTHORITY_CHANGED",
    ):
        preview_service.build_agent_run_authorization_preview(
            cfg,
            session_id,
            actor="user-1",
        )


def _ledger_counts(cfg: Any) -> dict[str, int]:
    tables = (
        "agent_events",
        "agent_plan_revisions",
        "agent_run_authorizations",
        "agent_session_effect_budgets",
        "agent_sessions",
        "runs",
        "workflow_revisions",
    )
    with get_connection(cfg) as connection:
        return {
            table: int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in tables
        }


def _host_paths(candidate_case: dict[str, Any]) -> tuple[str, ...]:
    cfg = candidate_case["cfg"]
    return (
        candidate_case["upload"]["path"],
        cfg.release_dir,
        cfg.work_dir,
        cfg.snakemake_command,
        cfg.managed_conda_command,
        cfg.managed_conda_root_prefix,
    )


def _keys_matching(value: Any, predicate: Callable[[str], bool]) -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if predicate(str(key)):
                matches.append(str(key))
            matches.extend(_keys_matching(nested, predicate))
    elif isinstance(value, list | tuple):
        for item in value:
            matches.extend(_keys_matching(item, predicate))
    return matches


def _unsafe_public_key(value: str) -> bool:
    normalized = "".join(
        character for character in value.lower() if character.isalnum()
    )
    return normalized.endswith("path") or any(
        marker in normalized
        for marker in (
            "accesstoken",
            "apikey",
            "authorization",
            "credential",
            "password",
            "privatekey",
            "secret",
        )
    )
