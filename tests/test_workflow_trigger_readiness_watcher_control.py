from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.remote_runner import route_utils
from apps.remote_runner.api_models import WorkflowTriggerReadinessWatcherRunOnceRequest
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.trigger_readiness_watcher_control import (
    run_governed_workflow_trigger_readiness_watcher_once,
)
from tests.helpers.reference_database import make_configured_remote_runner


def test_readiness_watcher_run_once_returns_safe_aggregate_and_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )

    def fake_watcher_once(_cfg, *, limit: int):
        assert limit == 5
        return {
            "checked": 3,
            "skipped": 1,
            "missing": 1,
            "ready": 2,
            "submitted": 1,
            "unchanged": 1,
            "observations": [
                {
                    "triggerId": "wtr_secret",
                    "sourceType": "file",
                    "resourceType": "file",
                    "resourceId": "file:/secret/reads.fastq",
                    "resourceUri": "file:///E:/secret/reads.fastq",
                    "watcherAdapter": "local_path",
                    "observedState": "ready",
                    "dispatchState": "submitted",
                    "runId": "run_secret",
                    "triggerEventId": "wte_secret",
                },
                {
                    "triggerId": "wtr_database",
                    "sourceType": "database_ready",
                    "resourceType": "database",
                    "watcherAdapter": "database_registry",
                    "observedState": "missing",
                    "dispatchState": "",
                },
            ],
            "errors": [
                {
                    "triggerId": "wtr_broken",
                    "errorType": "ValueError",
                    "message": "WATCH_BAD: E:/secret/raw-path",
                }
            ],
            "evaluatedAt": "2026-06-23T02:00:00Z",
        }

    monkeypatch.setattr(
        "apps.remote_runner.trigger_readiness_watcher_control.run_workflow_trigger_readiness_watcher_once",
        fake_watcher_once,
    )

    result = run_governed_workflow_trigger_readiness_watcher_once(
        cfg,
        WorkflowTriggerReadinessWatcherRunOnceRequest(
            confirmation="run-readiness-watcher-once",
            limit=5,
            actor="readiness-operator",
            reason="do not audit this free text",
        ),
    )

    data = result["data"]
    assert data["schemaVersion"] == "h2ometa.workflow-trigger-readiness-watcher-run-once-result.v1"
    assert data["runOnceId"].startswith("wfrw_")
    assert data["evaluatedAt"] == "2026-06-23T02:00:00Z"
    assert data["limit"] == 5
    assert data["controlsExposed"] is False
    assert data["readiness"] == {
        "checked": 3,
        "skipped": 1,
        "missing": 1,
        "ready": 2,
        "submitted": 1,
        "unchanged": 1,
        "observationCount": 2,
        "errorCount": 1,
        "stateCounts": {"missing": 1, "ready": 1},
        "sourceTypeCounts": {"database_ready": 1, "file": 1},
        "resourceTypeCounts": {"database": 1, "file": 1},
        "watcherAdapterCounts": {"database_registry": 1, "local_path": 1},
        "dispatchStateCounts": {"submitted": 1},
        "errorTypes": {"ValueError": 1},
        "reasonCodes": {"WATCH_BAD": 1},
    }
    audit = list_governance_audit_events(cfg, action="workflow_trigger.readiness_watcher.run_once")["items"]
    assert audit[-1]["actor"] == "readiness-operator"
    serialized = json.dumps({"result": data, "auditDetails": audit[-1]["details"]}, sort_keys=True)
    for sensitive in (
        "wtr_secret",
        "wte_secret",
        "run_secret",
        "file:/secret/reads.fastq",
        "file:///E:/secret/reads.fastq",
        "E:/secret/raw-path",
        "do not audit this free text",
        "triggerId",
        "triggerEventId",
        "runId",
        "resourceId",
        "resourceUri",
        '"path"',
    ):
        assert sensitive not in serialized


def test_readiness_watcher_run_once_route_denies_wrong_role_before_tick(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_watcher(*_args, **_kwargs):
        raise AssertionError("readiness watcher must not run before authorization")

    monkeypatch.setattr(
        "apps.remote_runner.trigger_readiness_watcher_control.run_workflow_trigger_readiness_watcher_once",
        fail_watcher,
    )

    response = TestClient(app).post(
        "/api/v1/workflow-trigger-readiness-watcher/run-once",
        headers={"Authorization": "Bearer rbac-token"},
        json={"confirmation": "run-readiness-watcher-once", "limit": 3},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    deny_events = list_governance_audit_events(cfg, action="workflow_trigger.readiness_watcher.run_once")["items"]
    assert deny_events[-1]["decision"] == "deny"
    assert deny_events[-1]["details"]["requiredRoles"] == ["workflow-operator"]
    assert deny_events[-1]["actorRoles"] == ["auditor"]
