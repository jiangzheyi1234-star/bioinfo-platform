from __future__ import annotations

import pytest

from apps.remote_runner.api_models import (
    WorkflowTriggerBackfillLaunchRequest,
    WorkflowTriggerBackfillPreviewRequest,
    WorkflowTriggerCreateRequest,
    WorkflowTriggerEventRequest,
)
from apps.remote_runner.trigger_service import (
    create_workflow_trigger_from_request,
    launch_workflow_trigger_backfill_from_request,
    preview_workflow_trigger_backfill_from_request,
    submit_workflow_trigger_event_from_request,
)
from tests.helpers.reference_database import make_configured_remote_runner


def test_backfill_preview_supports_backward_hourly_windows(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    trigger = _create_trigger(
        cfg,
        source_type="backfill",
        trigger_spec={"partitionUnit": "hour"},
        enabled=False,
    )

    response = preview_workflow_trigger_backfill_from_request(
        cfg,
        trigger["triggerId"],
        WorkflowTriggerBackfillPreviewRequest(
            rangeStart="2026-06-01T00:00:00Z",
            rangeEnd="2026-06-01T03:00:00Z",
            partitionUnit="hour",
            timezone="UTC",
            maxPartitions=2,
            runOrder="backward",
        ),
    )

    assert [item["partitionKey"] for item in response["data"]["partitions"]] == [
        "2026-06-01T02",
        "2026-06-01T01",
    ]
    assert [item["index"] for item in response["data"]["partitions"]] == [2, 1]


def test_backfill_preview_rejects_wrong_source_and_invalid_range(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    manual_trigger = _create_trigger(cfg, source_type="manual", trigger_spec={"mode": "manual"})
    with pytest.raises(ValueError, match="WORKFLOW_BACKFILL_PREVIEW_SOURCE_MISMATCH: manual"):
        preview_workflow_trigger_backfill_from_request(
            cfg,
            manual_trigger["triggerId"],
            WorkflowTriggerBackfillPreviewRequest(rangeStart="2026-06-01", rangeEnd="2026-06-02"),
        )

    backfill_trigger = _create_trigger(
        cfg,
        source_type="backfill",
        trigger_spec={"partitionUnit": "day"},
        enabled=False,
    )
    with pytest.raises(ValueError, match="WORKFLOW_BACKFILL_RANGE_INVALID"):
        preview_workflow_trigger_backfill_from_request(
            cfg,
            backfill_trigger["triggerId"],
            WorkflowTriggerBackfillPreviewRequest(rangeStart="2026-06-02", rangeEnd="2026-06-01"),
        )


def test_backfill_launch_rejects_disabled_truncated_and_generic_event_route(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_execution_admission_ready", lambda _cfg: None)

    disabled_trigger = _create_trigger(
        cfg,
        source_type="backfill",
        trigger_spec={"partitionUnit": "day"},
        enabled=False,
    )
    enabled_trigger = _create_trigger(cfg, source_type="backfill", trigger_spec={"partitionUnit": "day"})

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_SOURCE_LAUNCH_UNSUPPORTED: backfill"):
        submit_workflow_trigger_event_from_request(
            cfg,
            enabled_trigger["triggerId"],
            WorkflowTriggerEventRequest(
                eventType="backfill.partition",
                externalEventId="evt_backfill",
                idempotencyKey="backfill:generic",
                cursor="backfill:generic",
                payload={},
            ),
        )
    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_DISABLED"):
        launch_workflow_trigger_backfill_from_request(
            cfg,
            disabled_trigger["triggerId"],
            WorkflowTriggerBackfillLaunchRequest(
                rangeStart="2026-06-01",
                rangeEnd="2026-06-02",
                confirmation="launch-backfill",
            ),
        )

    with pytest.raises(ValueError, match="WORKFLOW_BACKFILL_LAUNCH_TRUNCATED"):
        launch_workflow_trigger_backfill_from_request(
            cfg,
            enabled_trigger["triggerId"],
            WorkflowTriggerBackfillLaunchRequest(
                rangeStart="2026-06-01",
                rangeEnd="2026-06-04",
                maxPartitions=2,
                confirmation="launch-backfill",
            ),
        )


def _create_trigger(
    cfg,
    *,
    source_type: str,
    trigger_spec: dict[str, object],
    enabled: bool = True,
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
            enabled=enabled,
        ),
        actor="pytest",
    )["data"]
