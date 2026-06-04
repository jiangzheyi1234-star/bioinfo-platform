from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from apps.remote_runner.main import app
from apps.remote_runner.storage import fetch_run, list_runs
from apps.remote_runner.workflow_design_contract import workflow_design_to_generated_run_spec
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft
from tests.generated_workflow_test_helpers import upsert_ready_tool
from tests.helpers.workflow_design_drafts import (
    workflow_design_config,
    workflow_design_draft,
    workflow_design_tool_manifest,
)


def _response_data(response) -> Any:
    return json.loads(response.content)["data"]


def test_workflow_design_draft_remote_runner_api_lifecycle(monkeypatch, tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    upsert_ready_tool(cfg, workflow_design_tool_manifest())
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    headers = {"Authorization": "Bearer workflow-design-token"}
    client = TestClient(app)

    created = client.post("/api/v1/workflow-design-drafts", headers=headers, json={"draft": workflow_design_draft()})
    assert created.status_code == 201
    draft_id = _response_data(created)["draftId"]

    listed = client.get("/api/v1/workflow-design-drafts", headers=headers)
    assert listed.status_code == 200
    assert _response_data(listed)["items"][0]["draftId"] == draft_id

    fetched = client.get(f"/api/v1/workflow-design-drafts/{draft_id}", headers=headers)
    assert fetched.status_code == 200
    assert _response_data(fetched)["draft"]["metadata"]["name"] == "QC workflow"
    assert list_runs(cfg) == []

    override_plan = client.post(
        f"/api/v1/workflow-design-drafts/{draft_id}/plan",
        headers=headers,
        json={"inputOverrides": [{"role": "input", "path": "/tmp/override.fastq"}]},
    )
    assert override_plan.status_code == 422

    planned = client.post(f"/api/v1/workflow-design-drafts/{draft_id}/plan", headers=headers, json={})
    assert planned.status_code == 200
    planned_data = _response_data(planned)
    assert planned_data["valid"] is True
    assert planned_data["runSpec"]["workflowDesign"]["draftId"] == draft_id
    assert planned_data["runSpec"]["workflowDesign"]["revision"] == 1
    assert list_runs(cfg) == []

    compiled = client.post(f"/api/v1/workflow-design-drafts/{draft_id}/compile", headers=headers, json={})
    assert compiled.status_code == 200
    compiled_data = _response_data(compiled)
    assert compiled_data["layout"]["snakefile"] == "workflow/Snakefile"
    assert compiled_data["layout"]["rules"] == "workflow/rules/generated.smk"
    assert compiled_data["runSpec"]["workflowDesign"]["draftId"] == draft_id
    assert list_runs(cfg) == []

    invalid_compile = client.post(
        f"/api/v1/workflow-design-drafts/{draft_id}/compile",
        headers=headers,
        json={"serverId": "srv_not_remote_payload"},
    )
    assert invalid_compile.status_code == 422
    assert list_runs(cfg) == []

    patch = workflow_design_draft()
    patch["metadata"]["description"] = "patched"
    updated = client.patch(
        f"/api/v1/workflow-design-drafts/{draft_id}",
        headers=headers,
        json={"draft": patch, "expectedRevision": 1},
    )
    assert updated.status_code == 200
    assert _response_data(updated)["revision"] == 2

    forked = client.post(
        f"/api/v1/workflow-design-drafts/{draft_id}/fork",
        headers=headers,
        json={"name": "Forked UI draft"},
    )
    assert forked.status_code == 201
    assert _response_data(forked)["parentDraftId"] == draft_id

    deleted = client.delete(f"/api/v1/workflow-design-drafts/{draft_id}", headers=headers)
    assert deleted.status_code == 200
    assert _response_data(deleted) == {"draftId": draft_id, "deleted": True}


def test_generated_tool_run_record_keeps_strict_draft_run_spec(monkeypatch, tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    upsert_ready_tool(cfg, workflow_design_tool_manifest())
    saved = create_workflow_design_draft(cfg, workflow_design_draft())
    run_spec = workflow_design_to_generated_run_spec(
        saved["draft"],
        draft_id=saved["draftId"],
        revision=saved["revision"],
    )
    run_spec["inputs"] = [{"role": "input", "uploadId": "upl_reads", "filename": "reads.fastq"}]
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr("apps.remote_runner.submission_service.ensure_submission_ready", lambda cfg: None)
    monkeypatch.setattr(
        "apps.remote_runner.submission_service.start_run_execution",
        lambda cfg, run_id, request_id, run_spec: None,
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/runs",
        headers={"Authorization": "Bearer workflow-design-token", "Idempotency-Key": "idem_design_run"},
        json={"serverId": "srv_design", "requestId": "req_design_run", "runSpec": run_spec},
    )

    assert response.status_code == 202
    run = fetch_run(cfg, _response_data(response)["runId"])
    assert run is not None
    assert run["pipelineVersion"] == "0.1.0"
    assert "pipelineVersion" not in run["runSpec"]
    assert run["runSpec"]["workflowDesign"]["draftId"] == saved["draftId"]
