from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.api_models import RunCreateRequest
from apps.remote_runner.governance_audit import (
    GOVERNANCE_AUDIT_EVENT_TYPE,
    list_governance_audit_events,
    record_governance_audit_event,
)
from apps.remote_runner.execution_query_storage import fetch_run
from apps.remote_runner.submission_service import create_run_from_request
from apps.remote_runner.workflow_revision_storage import fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


def test_governance_audit_events_are_hash_chained_and_projected(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    first = record_governance_audit_event(
        cfg,
        action="run.submit",
        subject_kind="run",
        subject_id="run_audit",
        actor="pytest",
        details={"serverId": "srv_audit", "requestId": "req_audit"},
    )
    second = record_governance_audit_event(
        cfg,
        action="result.export",
        subject_kind="result",
        subject_id="res_audit",
        actor="pytest",
        details={"runId": "run_audit", "artifactCount": 1},
    )

    all_events = list_governance_audit_events(cfg, limit=10)["items"]
    filtered = list_governance_audit_events(
        cfg,
        subject_kind="run",
        subject_id="run_audit",
        action="run.submit",
    )["items"]

    assert [item["eventHash"] for item in all_events] == [
        first["eventHash"],
        second["eventHash"],
    ]
    assert all_events[0]["prevEventHash"] == ""
    assert all_events[1]["prevEventHash"] == first["eventHash"]
    assert filtered == [first]
    assert filtered[0]["eventType"] == GOVERNANCE_AUDIT_EVENT_TYPE
    assert filtered[0]["decision"] == "allow"
    assert filtered[0]["details"] == {"serverId": "srv_audit", "requestId": "req_audit"}
    assert "payload" not in filtered[0]


def test_governance_audit_details_reject_secret_like_keys(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(ValueError, match="GOVERNANCE_AUDIT_SECRET_FIELD_FORBIDDEN"):
        record_governance_audit_event(
            cfg,
            action="run.submit",
            subject_kind="run",
            subject_id="run_secret",
            details={"nested": {"authorization": "Bearer should-not-log"}},
        )


def test_run_submission_records_governance_audit_without_run_spec_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.submission_service.ensure_submission_ready", lambda _cfg: None)
    monkeypatch.setattr(
        "apps.remote_runner.submission_service.ensure_execution_admission_ready",
        lambda _cfg: None,
    )

    response = create_run_from_request(
        cfg,
        RunCreateRequest(
            serverId="srv_audit",
            requestId="req_audit_submit",
            runSpec={
                "projectId": "proj_audit",
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
        ),
        idempotency_key="idem_audit_submit",
        x_request_id="req_audit_submit",
    )
    run_id = response["data"]["runId"]
    events = list_governance_audit_events(
        cfg,
        subject_kind="run",
        subject_id=run_id,
        action="run.submit",
    )["items"]

    assert len(events) == 1
    assert events[0]["details"]["serverId"] == "srv_audit"
    assert events[0]["details"]["pipelineId"] == "file-summary-standard-v1"
    assert events[0]["details"]["idempotencyReplay"] is False
    assert events[0]["details"]["workflowRevisionId"].startswith("wfrev_")
    assert "inputs" not in events[0]["details"]
    assert "params" not in events[0]["details"]

    run = fetch_run(cfg, run_id)
    assert run is not None
    workflow_revision_id = run["workflowRevisionId"]
    assert workflow_revision_id
    assert run["runSpec"]["workflowRevisionId"] == workflow_revision_id
    workflow_revision = fetch_workflow_revision(cfg, workflow_revision_id)
    assert workflow_revision is not None
    assert workflow_revision["manifest"]["pipelineId"] == "file-summary-standard-v1"
    assert workflow_revision["manifest"]["pipelineVersion"]
    assert workflow_revision["manifest"]["files"]
