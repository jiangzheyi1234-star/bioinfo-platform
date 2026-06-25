from __future__ import annotations

import pytest

from apps.remote_runner.api_models import (
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
)
from apps.remote_runner.execution_query_storage import fetch_run
from apps.remote_runner.trigger_provenance_read_model import attach_run_trigger_provenance
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    launch_workflow_trigger_backfill_from_request,
    preview_workflow_trigger_backfill_from_request,
    submit_workflow_trigger_event_from_request,
)
from tests.helpers.reference_database import make_configured_remote_runner


def test_run_read_model_attaches_safe_trigger_event_provenance(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)
    trigger = _create_trigger(cfg, source_type="manual", trigger_spec={"mode": "manual"})

    response = submit_workflow_trigger_event_from_request(
        cfg,
        str(trigger["triggerId"]),
        WorkflowTriggerEventRequest(
            eventType="manual",
            externalEventId="evt_safe",
            idempotencyKey="manual:evt-safe",
            cursor="dataset:v1",
            payload={"dataset": "reads.fastq", "token": "payload-secret"},
        ),
    )

    run = fetch_run(cfg, response["data"]["run"]["runId"])
    assert run is not None
    projected = attach_run_trigger_provenance(cfg, run)
    provenance = projected["trigger"]["provenance"]

    assert provenance["schemaVersion"] == "run-trigger-provenance-read.v1"
    assert provenance["available"] is True
    assert provenance["triggerId"] == trigger["triggerId"]
    assert provenance["event"]["eventType"] == "manual"
    assert provenance["event"]["externalEventId"] == "evt_safe"
    assert provenance["event"]["idempotencyKey"] == "manual:evt-safe"
    assert provenance["event"]["cursor"] == "dataset:v1"
    assert provenance["event"]["payloadHash"]
    assert provenance["dispatch"]["state"] == "submitted"
    assert provenance["dispatch"]["runId"] == run["runId"]
    assert "payload-secret" not in repr(provenance)
    assert "reads.fastq" not in repr(provenance)


def test_run_read_model_attaches_backfill_partition_context(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    _skip_runtime_readiness(monkeypatch)
    trigger = _create_trigger(cfg, source_type="backfill", trigger_spec={"partitionUnit": "day"})

    launched = launch_workflow_trigger_backfill_from_request(
        cfg,
        str(trigger["triggerId"]),
        _launch_request(cfg, trigger),
    )["data"]

    run_id = launched["partitions"][0]["runId"]
    run = fetch_run(cfg, run_id)
    assert run is not None
    provenance = attach_run_trigger_provenance(cfg, run)["trigger"]["provenance"]

    assert provenance["source"] == "backfill"
    assert provenance["event"]["eventType"] == "backfill.partition"
    assert provenance["backfillPartition"] == {
        "partitionId": launched["partitions"][0]["partitionId"],
        "launchId": launched["launchId"],
        "triggerId": trigger["triggerId"],
        "partitionKey": "2026-06-01",
        "index": 0,
        "window": {
            "start": "2026-06-01T00:00:00Z",
            "end": "2026-06-02T00:00:00Z",
            "semantics": "half-open",
        },
        "cursor": launched["partitions"][0]["cursor"],
        "idempotencyKey": launched["partitions"][0]["idempotencyKey"],
        "triggerEventId": launched["partitions"][0]["triggerEventId"],
        "runId": run_id,
        "state": "submitted",
        "runSpecHash": launched["partitions"][0]["runSpecHash"],
        "createdAt": provenance["backfillPartition"]["createdAt"],
        "updatedAt": provenance["backfillPartition"]["updatedAt"],
    }
    assert "errorHash" not in provenance["backfillPartition"]
    assert "runSpecPreview" not in repr(provenance)


def test_run_read_model_reports_unavailable_provenance_without_hiding_trigger(
    tmp_path,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    run = {
        "runId": "run_orphan",
        "trigger": {
            "triggerId": "wtr_missing",
            "triggerEventId": "wte_missing",
            "source": "manual",
            "cursor": "cursor:v1",
        },
    }

    projected = attach_run_trigger_provenance(cfg, run)

    assert projected["trigger"]["triggerId"] == "wtr_missing"
    assert projected["trigger"]["provenance"] == {
        "schemaVersion": "run-trigger-provenance-read.v1",
        "available": False,
        "reasonCode": "RUN_NOT_FOUND",
        "runId": "run_orphan",
        "triggerId": "wtr_missing",
        "triggerEventId": "wte_missing",
        "source": "manual",
        "cursor": "cursor:v1",
    }


def _skip_runtime_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)


def _create_trigger(
    cfg,
    *,
    source_type: str,
    trigger_spec: dict[str, object],
) -> dict[str, object]:
    return create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name="FASTQ summary trigger",
            sourceType=source_type,
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec=trigger_spec,
        ),
        actor="pytest",
    )["data"]


def _launch_request(cfg, trigger: dict[str, object]) -> WorkflowTriggerBackfillLaunchRequest:
    preview_request = WorkflowTriggerBackfillPreviewRequest(
        rangeStart="2026-06-01",
        rangeEnd="2026-06-02",
        maxPartitions=10,
    )
    preview = preview_workflow_trigger_backfill_from_request(
        cfg,
        str(trigger["triggerId"]),
        preview_request,
    )["data"]
    return WorkflowTriggerBackfillLaunchRequest(
        **preview_request.model_dump(),
        previewId=str(preview["previewId"]),
        confirmation="launch-backfill",
    )
