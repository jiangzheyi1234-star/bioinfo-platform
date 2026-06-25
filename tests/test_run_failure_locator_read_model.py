from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.remote_runner import route_utils
from apps.remote_runner.artifact_storage import persist_artifact
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.log_storage import append_log_lines
from apps.remote_runner.main import app
from apps.remote_runner.rule_execution_storage import append_run_rule_event, upsert_run_rule_state
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.run_failure_locator_read_model import fetch_run_failure_locator
from apps.remote_runner.storage import create_run_record, update_run_state
from tests.helpers.reference_database import make_configured_remote_runner


def test_failure_locator_projects_managed_rule_log_without_storage_locators(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    claim = _failed_rule_run_with_log_artifact(cfg, tmp_path)

    locator = fetch_run_failure_locator(cfg, "run_failure_locator")

    assert locator["schemaVersion"] == "run-failure-locator.v1"
    assert locator["available"] is True
    assert locator["reasonCode"] == "FAILED_RULE"
    assert locator["failedRule"]["ruleName"] == "align_reads"
    assert locator["failedRule"]["attemptId"] == claim["attemptId"]
    assert locator["failedRule"]["inputCount"] == 1
    assert locator["failedRule"]["outputCount"] == 1
    assert locator["failedRule"]["logReferenceCount"] == 1
    assert locator["failedRule"]["message"] == ""
    assert locator["failedRule"]["wildcards"] == {"sample": "S1"}
    assert "commandSummary" not in locator["failedRule"]
    assert "logs" not in locator["failedRule"]
    assert locator["failedRule"]["latestFailureEvent"]["message"] == ""
    assert locator["failedRule"]["latestFailureEvent"]["details"] == {"exitCode": 1}
    assert locator["message"] == "Failed rule message redacted by run-failure-locator.v1."
    assert locator["logContext"]["stderrLineCount"] == 35
    assert locator["logContext"]["stderrTail"][0] == "stderr 5"
    assert locator["ruleLogContext"]["status"] == "available"
    assert locator["ruleLogContext"]["reasonCode"] == "PREVIEW_AVAILABLE"
    assert locator["ruleLogContext"]["logReferenceCount"] == 1
    assert locator["ruleLogContext"]["selectedArtifact"]["artifactId"].startswith("art_")
    assert locator["ruleLogContext"]["lineCount"] == 40
    assert locator["ruleLogContext"]["tail"][0] == "rule log 10"
    assert locator["artifactContext"]["relatedArtifactCount"] == 2
    assert locator["redactionPolicy"] == {
        "artifactPathsExposed": False,
        "storageUrisExposed": False,
        "commandSummaryExposed": False,
        "eventDetailsSanitized": True,
        "runSpecExposed": False,
    }
    serialized = json.dumps(locator, sort_keys=True)
    for forbidden in (
        '"storageUri":',
        "storage_uri",
        '"path":',
        '"commandSummary":',
        "snakemake --cores 1",
        "TOKEN_SHOULD_NOT_LEAK",
        "TOKEN_WILDCARD_SHOULD_NOT_LEAK",
        str(tmp_path),
    ):
        assert forbidden not in serialized

    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    response = TestClient(app).get(
        "/api/v1/runs/run_failure_locator/failure-locator",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 200
    route_locator = response.json()["data"]
    assert route_locator["ruleLogContext"]["reasonCode"] == "PREVIEW_AVAILABLE"
    audit = list_governance_audit_events(cfg, action="run.failure_locator.read")["items"][-1]
    assert audit["details"] == {
        "available": True,
        "reasonCode": "FAILED_RULE",
        "failedRulePresent": True,
        "stderrLineCount": 35,
        "stderrTailLineCount": 30,
        "ruleLogStatus": "available",
        "ruleLogReasonCode": "PREVIEW_AVAILABLE",
        "relatedArtifactCount": 2,
    }
    serialized_audit = json.dumps(audit, sort_keys=True)
    assert "rule log" not in serialized_audit
    assert "stderr 5" not in serialized_audit
    assert str(tmp_path) not in serialized_audit


def _failed_rule_run_with_log_artifact(cfg, tmp_path: Path) -> dict[str, object]:
    create_run_record(
        cfg,
        server_id="srv_failure_locator",
        request_id="req_failure_locator",
        run_spec={
            "runId": "run_failure_locator",
            "projectId": "proj_failure_locator",
            "pipelineId": "pipeline_failure_locator",
            "pipelineVersion": "0.1.0",
            "runSpecVersion": "2026-04-21",
            "workflowRevisionId": "wfrev_failure_locator",
        },
        idempotency_key="idem_failure_locator",
        payload_hash="hash_failure_locator",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_failure_locator",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    attempt = claim["attempt"]
    upsert_run_rule_state(
        cfg,
        run_id="run_failure_locator",
        rule_name="align_reads",
        step_id="align",
        runtime_status_key="rule:align_reads",
        status="failed",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(attempt["attemptNumber"]),
        started_at="2099-06-07T10:00:01Z",
        finished_at="2099-06-07T10:00:02Z",
        exit_code=1,
        message=f"Command exited with status 1 at {tmp_path / 'secret' / 'align_reads.log'} TOKEN_SHOULD_NOT_LEAK",
        command_summary="snakemake --cores 1 align_reads TOKEN_SHOULD_NOT_LEAK",
        inputs=["inputs/reads.fastq"],
        outputs=["outputs/aligned.bam"],
        wildcards={"sample": "S1", "secret": f"{tmp_path / 'secret' / 'sample.txt'} TOKEN_WILDCARD_SHOULD_NOT_LEAK"},
        logs=["logs/align_reads.log"],
        occurred_at="2099-06-07T10:00:02Z",
    )
    append_run_rule_event(
        cfg,
        run_id="run_failure_locator",
        rule_name="align_reads",
        step_id="align",
        event_type="JOB_ERROR",
        status="failed",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(attempt["attemptNumber"]),
        message=f"align_reads failed at {tmp_path / 'secret' / 'align_reads.log'} TOKEN_SHOULD_NOT_LEAK",
        details={
            "exitCode": 1,
            "command": "snakemake --cores 1 align_reads TOKEN_SHOULD_NOT_LEAK",
            "logPath": str(tmp_path / "secret" / "align_reads.log"),
        },
        occurred_at="2099-06-07T10:00:03Z",
    )
    append_log_lines(cfg, "run_failure_locator", "stderr", [f"stderr {index}" for index in range(35)])
    outputs_dir = Path(cfg.results_dir) / "outputs"
    logs_dir = Path(cfg.results_dir) / "logs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    output_path = outputs_dir / "aligned.bam"
    output_path.write_text("bam", encoding="utf-8")
    log_path = logs_dir / "align_reads.log"
    log_path.write_text("\n".join(f"rule log {index}" for index in range(40)), encoding="utf-8")
    persist_artifact(
        cfg,
        run_id="run_failure_locator",
        kind="aligned.bam",
        path=output_path,
        mime_type="application/bam",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        artifact_key="aligned_bam",
        step_id="align",
    )
    persist_artifact(
        cfg,
        run_id="run_failure_locator",
        kind="align_reads.log",
        path=log_path,
        mime_type="text/plain",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        artifact_key="align_reads_log",
        step_id="align",
    )
    update_run_state(
        cfg,
        run_id="run_failure_locator",
        status="failed",
        stage="running",
        message="Snakemake failed.",
        request_id="req_failure_locator",
    )
    return claim
