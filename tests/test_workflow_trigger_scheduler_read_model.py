from __future__ import annotations

import json

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.trigger_scheduler import run_workflow_trigger_scheduler_once
from apps.remote_runner.trigger_scheduler_read_model import (
    list_governed_workflow_trigger_scheduler_ticks,
    list_workflow_trigger_scheduler_ticks,
)
from apps.remote_runner.trigger_service import create_workflow_trigger_from_request
from tests.helpers.reference_database import make_configured_remote_runner


def test_scheduler_tick_read_model_projects_safe_evidence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)
    trigger = _create_cron_trigger(cfg)

    tick = run_workflow_trigger_scheduler_once(cfg, now="2026-06-23T02:00:39Z")
    model = list_workflow_trigger_scheduler_ticks(cfg)

    assert tick["tickId"].startswith("wfts_")
    assert tick["evidenceId"].startswith("evid_")
    assert model["schemaVersion"] == "h2ometa.workflow-trigger-scheduler-tick-read-model.v1"
    assert len(model["items"]) == 1
    item = model["items"][0]
    assert item["tickId"] == tick["tickId"]
    assert item["evidenceId"] == tick["evidenceId"]
    assert item["evaluatedAt"] == "2026-06-23T02:00:00Z"
    assert item["controlsExposed"] is False
    assert item["cron"] == {
        "checked": 1,
        "skipped": 0,
        "due": 1,
        "submitted": 1,
        "replayed": 0,
        "overlapSkipped": 0,
        "eventCount": 1,
        "dispatchRunCount": 1,
        "errorCount": 0,
        "errorTypes": {},
        "reasonCodes": {},
    }
    assert item["backfills"] == {
        "checked": 0,
        "advanced": 0,
        "submitted": 0,
        "replayed": 0,
        "pending": 0,
        "launchCount": 0,
        "stateCounts": {},
        "errorCount": 0,
        "errorTypes": {},
        "reasonCodes": {},
    }
    serialized = json.dumps(item, sort_keys=True)
    assert str(trigger["triggerId"]) not in serialized
    assert "externalEventId" not in serialized
    assert "idempotencyKey" not in serialized
    assert "cursor" not in serialized
    assert "payload" not in serialized
    assert "runSpec" not in serialized
    assert "scheduledAt" not in serialized
    assert "dataInterval" not in serialized


def test_governed_scheduler_tick_read_records_safe_allow_audit(tmp_path) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )

    result = list_governed_workflow_trigger_scheduler_ticks(cfg, limit=7)

    assert result["items"] == []
    audit = list_governance_audit_events(cfg, action="workflow_trigger.scheduler_ticks.read")["items"]
    assert audit[-1]["details"] == {
        "limit": 7,
        "returnedCount": 0,
        "cronSubmittedCount": 0,
        "backfillSubmittedCount": 0,
        "errorTickCount": 0,
        "controlsExposed": False,
    }
    assert "rbac-token" not in json.dumps(audit[-1], sort_keys=True)


def _create_cron_trigger(cfg) -> dict[str, object]:
    return create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="Scheduler evidence trigger",
            sourceType="cron",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec={"cron": "0 2 * * *", "timezone": "UTC", "concurrencyPolicy": "Forbid"},
        ),
        actor="pytest",
    )["data"]
