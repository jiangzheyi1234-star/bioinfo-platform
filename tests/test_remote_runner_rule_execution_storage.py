from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.errors import RemoteRunnerNotFoundError
from apps.remote_runner.rule_execution_storage import (
    append_run_rule_event,
    fetch_run_rules,
    upsert_run_rule_state,
)
from apps.remote_runner.run_execution_storage import claim_next_run_job, complete_run_attempt
from apps.remote_runner.storage import create_run_record
from tests.helpers.reference_database import make_configured_remote_runner


def _create_claim(tmp_path: Path, run_id: str = "run_rule_view") -> tuple[object, dict[str, object]]:
    cfg = make_configured_remote_runner(tmp_path)
    create_run_record(
        cfg,
        server_id="srv_rules",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_rules",
            "pipelineId": "pipeline_rules",
            "pipelineVersion": "0.1.0",
            "runSpecVersion": "2026-04-21",
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_rules",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    return cfg, claim


def test_rule_execution_storage_records_current_attempt_rule_state_and_events(tmp_path: Path) -> None:
    cfg, claim = _create_claim(tmp_path)
    attempt = claim["attempt"]

    rule = upsert_run_rule_state(
        cfg,
        run_id=str(claim["runId"]),
        rule_name="trim_reads",
        step_id="trim",
        runtime_status_key="rule:trim_reads",
        status="running",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(attempt["attemptNumber"]),
        started_at="2099-06-07T10:00:02Z",
        inputs=["reads.fastq.gz"],
        outputs=["trimmed.fastq.gz"],
        wildcards={"sample": "S1"},
        logs=["logs/trim_reads.stderr.log"],
        occurred_at="2099-06-07T10:00:02Z",
    )
    event = append_run_rule_event(
        cfg,
        run_id=str(claim["runId"]),
        rule_name="trim_reads",
        step_id="trim",
        event_type="job_started",
        status="running",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        message="trim_reads started",
        details={"threads": 2},
        occurred_at="2099-06-07T10:00:03Z",
    )
    upsert_run_rule_state(
        cfg,
        run_id=str(claim["runId"]),
        rule_name="trim_reads",
        step_id="trim",
        runtime_status_key="rule:trim_reads",
        status="succeeded",
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(attempt["attemptNumber"]),
        started_at="2099-06-07T10:00:02Z",
        finished_at="2099-06-07T10:00:06Z",
        exit_code=0,
        command_summary="fastp --in1 reads.fastq.gz --out1 trimmed.fastq.gz",
        inputs=["reads.fastq.gz"],
        outputs=["trimmed.fastq.gz"],
        wildcards={"sample": "S1"},
        logs=["logs/trim_reads.stderr.log"],
        occurred_at="2099-06-07T10:00:06Z",
    )

    fetched = fetch_run_rules(cfg, str(claim["runId"]))

    assert rule["ruleName"] == "trim_reads"
    assert event["eventType"] == "job_started"
    assert fetched["runId"] == claim["runId"]
    assert len(fetched["items"]) == 1
    item = fetched["items"][0]
    assert item["status"] == "succeeded"
    assert item["runtimeStatusKey"] == "rule:trim_reads"
    assert item["inputs"] == ["reads.fastq.gz"]
    assert item["outputs"] == ["trimmed.fastq.gz"]
    assert item["wildcards"] == {"sample": "S1"}
    assert item["logs"] == ["logs/trim_reads.stderr.log"]
    assert item["events"][0]["eventType"] == "job_started"
    assert item["events"][0]["details"] == {"threads": 2}


def test_rule_execution_storage_rejects_stale_attempt_publish(tmp_path: Path) -> None:
    cfg, claim = _create_claim(tmp_path, "run_rule_stale")
    complete_run_attempt(
        cfg,
        str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        state="succeeded",
        exit_code=0,
        now="2099-06-07T10:00:10Z",
    )

    with pytest.raises(RuntimeError, match="RUN_RULE_EVENT_STALE_ATTEMPT"):
        upsert_run_rule_state(
            cfg,
            run_id=str(claim["runId"]),
            rule_name="late_rule",
            status="running",
            attempt_id=str(claim["attemptId"]),
            lease_generation=int(claim["leaseGeneration"]),
        )


def test_fetch_run_rules_requires_existing_run(tmp_path: Path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    with pytest.raises(RemoteRunnerNotFoundError, match="RUN_NOT_FOUND"):
        fetch_run_rules(cfg, "missing_run")
