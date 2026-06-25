from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.remote_runner import control_service
from apps.remote_runner import run_failure_locator_read_api
from apps.remote_runner import route_utils
from apps.remote_runner.errors import RemoteRunnerAuthorizationError
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.route_utils import authorize_action
from tests.helpers.reference_database import make_configured_remote_runner


RUN_OBSERVABILITY_ACTIONS = (
    "run.events.read",
    "run.execution_context.read",
    "run.attempts.read",
    "run.logs.read",
    "run.rules.read",
    "run.failure_locator.read",
)


@pytest.mark.parametrize("action", RUN_OBSERVABILITY_ACTIONS)
def test_run_observability_read_actions_allow_operator_and_auditor_roles(tmp_path, action: str) -> None:
    denied = make_configured_remote_runner(
        tmp_path / "denied",
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    operator = make_configured_remote_runner(
        tmp_path / "operator",
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    auditor = make_configured_remote_runner(
        tmp_path / "auditor",
        token="rbac-token",
        api_token_roles=("auditor",),
    )

    try:
        authorize_action(denied, action)
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError(f"{action} must require workflow-operator or auditor")

    deny_events = list_governance_audit_events(denied, action=action)["items"]
    assert deny_events[-1]["decision"] == "deny"
    assert deny_events[-1]["details"]["requiredRoles"] == ["workflow-operator", "auditor"]
    assert deny_events[-1]["details"]["providedRoles"] == ["artifact-curator"]
    assert authorize_action(operator, action).roles == ("workflow-operator",)
    assert authorize_action(auditor, action).roles == ("auditor",)


@pytest.mark.parametrize(
    ("path", "action", "subject_kind", "read_attr"),
    (
        ("/api/v1/runs/run_obs_denied/events", "run.events.read", "run_events", "fetch_run_events"),
        (
            "/api/v1/runs/run_obs_denied/execution-context",
            "run.execution_context.read",
            "run_execution_context",
            "fetch_run_execution_context",
        ),
        ("/api/v1/runs/run_obs_denied/attempts", "run.attempts.read", "run_attempts", "fetch_run_attempts_read_model"),
        ("/api/v1/runs/run_obs_denied/logs?stream=stderr&cursor=12", "run.logs.read", "run_logs", "fetch_log_lines"),
        ("/api/v1/runs/run_obs_denied/rules", "run.rules.read", "run_rules", "fetch_run_rules"),
        (
            "/api/v1/runs/run_obs_denied/failure-locator",
            "run.failure_locator.read",
            "run_failure_locator",
            "fetch_run_failure_locator",
        ),
    ),
)
def test_run_observability_routes_deny_wrong_role_before_read(
    tmp_path,
    monkeypatch,
    path: str,
    action: str,
    subject_kind: str,
    read_attr: str,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_read(*_args, **_kwargs):
        raise AssertionError(f"{read_attr} must not run before authorization")

    target_module = run_failure_locator_read_api if read_attr == "fetch_run_failure_locator" else control_service
    monkeypatch.setattr(target_module, read_attr, fail_read)
    response = TestClient(app).get(path, headers={"Authorization": "Bearer rbac-token"})

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    events = list_governance_audit_events(cfg, action=action)["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["subjectKind"] == subject_kind
    assert events[0]["subjectId"] == "authorization"


def test_run_observability_routes_record_safe_allow_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(
        control_service,
        "fetch_run_events",
        lambda *_args: [
            {
                "eventType": "run.accepted",
                "detailsJson": {"token": "TOKEN_SHOULD_NOT_ENTER_AUDIT"},
            },
            {
                "eventType": "run.failed",
                "message": "C:/secret/run.log should not enter audit",
            },
        ],
    )
    monkeypatch.setattr(
        control_service,
        "fetch_run_execution_context",
        lambda *_args: {
            "job": {"executionOptions": {"command": "snakemake --config TOKEN_SHOULD_NOT_ENTER_AUDIT"}},
            "attempts": [{"attemptId": "attempt-1"}],
            "activeLease": {"attemptId": "attempt-1"},
            "retryEligibility": {"eligible": True, "eligibleNow": False},
            "resumeSupported": False,
            "ruleRetryPlan": {"failedRuleCount": 2, "selectedAttemptCount": 1, "selectedFailedRules": ["align"]},
            "ruleRetryExecutionPlan": {"executionEnabled": False, "argsPreview": ["--forcerun", "align"]},
        },
    )
    monkeypatch.setattr(
        control_service,
        "fetch_run_attempts_read_model",
        lambda *_args: {
            "summary": {
                "attemptCount": 1,
                "slotCount": 1,
                "activeLeasePresent": True,
                "attemptsByState": {"failed": 1},
                "slotsByState": {"occupied": 1},
            },
            "attempts": [{"workDir": "C:/secret/work"}],
        },
    )
    monkeypatch.setattr(
        run_failure_locator_read_api,
        "fetch_run_failure_locator",
        lambda *_args: {
            "schemaVersion": "run-failure-locator.v1",
            "runId": "run_obs_safe",
            "available": True,
            "reasonCode": "FAILED_RULE",
            "failedRule": {"ruleName": "align_reads"},
            "logContext": {
                "stderrLineCount": 40,
                "stderrTail": ["TOKEN_SHOULD_NOT_ENTER_AUDIT", "C:/secret/run.log"],
            },
            "ruleLogContext": {
                "status": "available",
                "reasonCode": "PREVIEW_AVAILABLE",
                "tail": ["TOKEN_SHOULD_NOT_ENTER_AUDIT"],
            },
            "artifactContext": {
                "relatedArtifactCount": 2,
                "relatedArtifacts": [{"artifactId": "art_log", "path": "C:/secret/run.log"}],
            },
        },
    )
    monkeypatch.setattr(
        control_service,
        "fetch_log_lines",
        lambda *_args: {
            "lines": ["TOKEN_SHOULD_NOT_ENTER_AUDIT", "C:/secret/run.log"],
            "nextCursor": "cursor-secret-123",
        },
    )
    monkeypatch.setattr(
        control_service,
        "fetch_run_rules",
        lambda *_args: {
            "items": [
                {
                    "status": "failed",
                    "commandSummary": "cat C:/secret/input.fastq",
                    "events": [{"details": {"token": "TOKEN_SHOULD_NOT_ENTER_AUDIT"}}],
                }
            ],
        },
    )

    client = TestClient(app)
    headers = {"Authorization": "Bearer rbac-token"}
    assert client.get("/api/v1/runs/run_obs_safe/events", headers=headers).status_code == 200
    assert client.get("/api/v1/runs/run_obs_safe/execution-context", headers=headers).status_code == 200
    assert client.get("/api/v1/runs/run_obs_safe/attempts", headers=headers).status_code == 200
    assert client.get("/api/v1/runs/run_obs_safe/logs?stream=stderr&cursor=cursor-secret-123", headers=headers).status_code == 200
    assert client.get("/api/v1/runs/run_obs_safe/rules", headers=headers).status_code == 200
    assert client.get("/api/v1/runs/run_obs_safe/failure-locator", headers=headers).status_code == 200

    assert list_governance_audit_events(cfg, action="run.events.read")["items"][-1]["details"] == {
        "returnedCount": 2,
        "eventTypes": {"run.accepted": 1, "run.failed": 1},
    }
    assert list_governance_audit_events(cfg, action="run.execution_context.read")["items"][-1]["details"] == {
        "hasJob": True,
        "attemptCount": 1,
        "activeLeasePresent": True,
        "retryEligible": True,
        "retryEligibleNow": False,
        "resumeSupported": False,
        "ruleRetryFailedRuleCount": 2,
        "ruleRetrySelectedAttemptCount": 1,
        "ruleRetryExecutionEnabled": False,
    }
    assert list_governance_audit_events(cfg, action="run.attempts.read")["items"][-1]["details"] == {
        "attemptCount": 1,
        "slotCount": 1,
        "activeLeasePresent": True,
        "attemptStates": {"failed": 1},
        "slotStates": {"occupied": 1},
    }
    assert list_governance_audit_events(cfg, action="run.logs.read")["items"][-1]["details"] == {
        "stream": "stderr",
        "cursorProvided": True,
        "returnedLineCount": 2,
        "nextCursorProvided": True,
    }
    assert list_governance_audit_events(cfg, action="run.rules.read")["items"][-1]["details"] == {
        "ruleCount": 1,
        "ruleEventCount": 1,
        "ruleStatuses": {"failed": 1},
    }
    assert list_governance_audit_events(cfg, action="run.failure_locator.read")["items"][-1]["details"] == {
        "available": True,
        "reasonCode": "FAILED_RULE",
        "failedRulePresent": True,
        "stderrLineCount": 40,
        "stderrTailLineCount": 2,
        "ruleLogStatus": "available",
        "ruleLogReasonCode": "PREVIEW_AVAILABLE",
        "relatedArtifactCount": 2,
    }
    serialized_audit = json.dumps(list_governance_audit_events(cfg, limit=100)["items"], sort_keys=True)
    assert "TOKEN_SHOULD_NOT_ENTER_AUDIT" not in serialized_audit
    assert "C:/secret" not in serialized_audit
    assert "cursor-secret-123" not in serialized_audit
    assert "commandSummary" not in serialized_audit
    assert "argsPreview" not in serialized_audit
