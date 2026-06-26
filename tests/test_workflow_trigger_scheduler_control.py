from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.remote_runner import route_utils
from apps.remote_runner.api_models import WorkflowTriggerSchedulerRunOnceRequest
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.trigger_scheduler_control import run_governed_workflow_trigger_scheduler_once
from tests.helpers.reference_database import make_configured_remote_runner


def test_scheduler_run_once_returns_safe_aggregate_and_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )

    def fake_scheduler_once(_cfg, *, limit: int):
        assert limit == 5
        return {
            "checked": 2,
            "skipped": 1,
            "due": 1,
            "submitted": 1,
            "replayed": 0,
            "events": [
                {
                    "triggerEventId": "wte_secret",
                    "triggerId": "wtr_secret",
                    "cursor": "cursor-secret",
                    "payload": {"secret": "payload-secret"},
                    "dispatch": {"runId": "run_secret"},
                }
            ],
            "backfills": {
                "checked": 1,
                "advanced": 1,
                "submitted": 1,
                "replayed": 0,
                "pending": 0,
                "launches": [{"launchId": "bfl_secret", "triggerId": "wtr_secret", "state": "running"}],
                "errors": [{"errorType": "RuntimeError", "message": "BACKFILL_BLOCKED: run_secret"}],
            },
            "errors": [{"triggerId": "wtr_secret", "errorType": "ValueError", "message": "TRIGGER_BAD: wtr_secret"}],
            "evaluatedAt": "2026-06-23T02:00:00Z",
            "tickId": "wfts_safe",
            "evidenceId": "evid_safe",
        }

    monkeypatch.setattr(
        "apps.remote_runner.trigger_scheduler_control.run_workflow_trigger_scheduler_once",
        fake_scheduler_once,
    )

    result = run_governed_workflow_trigger_scheduler_once(
        cfg,
        WorkflowTriggerSchedulerRunOnceRequest(
            confirmation="run-scheduler-once",
            limit=5,
            actor="scheduler-operator",
            reason="do not audit this free text",
        ),
    )

    assert result["data"] == {
        "schemaVersion": "h2ometa.workflow-trigger-scheduler-run-once-result.v1",
        "tickId": "wfts_safe",
        "evidenceId": "evid_safe",
        "evaluatedAt": "2026-06-23T02:00:00Z",
        "limit": 5,
        "controlsExposed": False,
        "cron": {
            "checked": 2,
            "skipped": 1,
            "due": 1,
            "submitted": 1,
            "replayed": 0,
            "eventCount": 1,
            "dispatchRunCount": 1,
            "errorCount": 1,
            "errorTypes": {"ValueError": 1},
            "reasonCodes": {"TRIGGER_BAD": 1},
        },
        "backfills": {
            "checked": 1,
            "advanced": 1,
            "submitted": 1,
            "replayed": 0,
            "pending": 0,
            "launchCount": 1,
            "stateCounts": {"running": 1},
            "errorCount": 1,
            "errorTypes": {"RuntimeError": 1},
            "reasonCodes": {"BACKFILL_BLOCKED": 1},
        },
    }
    audit = list_governance_audit_events(cfg, action="workflow_trigger.scheduler.run_once")["items"]
    assert audit[-1]["actor"] == "scheduler-operator"
    serialized = json.dumps({"result": result["data"], "auditDetails": audit[-1]["details"]}, sort_keys=True)
    for sensitive in (
        "wtr_secret",
        "wte_secret",
        "run_secret",
        "cursor-secret",
        "payload-secret",
        "do not audit this free text",
        "triggerId",
        "triggerEventId",
        "runId",
        "cursor",
        "payload",
        "runSpec",
    ):
        assert sensitive not in serialized


def test_scheduler_run_once_route_denies_wrong_role_before_tick(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_scheduler(*_args, **_kwargs):
        raise AssertionError("scheduler tick must not run before authorization")

    monkeypatch.setattr(
        "apps.remote_runner.trigger_scheduler_control.run_workflow_trigger_scheduler_once",
        fail_scheduler,
    )

    response = TestClient(app).post(
        "/api/v1/workflow-trigger-scheduler/run-once",
        headers={"Authorization": "Bearer rbac-token"},
        json={"confirmation": "run-scheduler-once", "limit": 3},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    deny_events = list_governance_audit_events(cfg, action="workflow_trigger.scheduler.run_once")["items"]
    assert deny_events[-1]["decision"] == "deny"
    assert deny_events[-1]["details"]["requiredRoles"] == ["workflow-operator"]
    assert deny_events[-1]["actorRoles"] == ["auditor"]
