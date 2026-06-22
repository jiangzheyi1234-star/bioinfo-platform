from __future__ import annotations

from pathlib import Path

from apps.remote_runner.rule_execution_projection import (
    mark_run_rules_failed,
    mark_run_rules_running,
    seed_run_rules_from_graph,
)
from apps.remote_runner.rule_execution_storage import fetch_run_rules
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record
from tests.helpers.reference_database import make_configured_remote_runner


def _claim_for_projection(tmp_path: Path) -> tuple[object, dict[str, object]]:
    cfg = make_configured_remote_runner(tmp_path)
    create_run_record(
        cfg,
        server_id="srv_projection",
        request_id="req_projection",
        run_spec={
            "runId": "run_projection",
            "projectId": "proj_projection",
            "pipelineId": "pipeline_projection",
            "pipelineVersion": "0.1.0",
            "runSpecVersion": "2026-04-21",
        },
        idempotency_key="idem_projection",
        payload_hash="hash_projection",
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_projection",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    return cfg, claim


def test_rule_projection_seeds_graph_rules_and_marks_failed_rule_by_stderr(tmp_path: Path) -> None:
    cfg, claim = _claim_for_projection(tmp_path)

    seed_run_rules_from_graph(
        cfg,
        run_id=str(claim["runId"]),
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(claim["attempt"]["attemptNumber"]),
        graph={
            "nodes": [
                {
                    "id": "quality_control",
                    "label": "quality_control",
                    "kind": "rule",
                    "runtimeStatusKey": "rule:quality_control",
                    "inputs": ["reads.fastq.gz"],
                    "outputs": ["qc.tsv"],
                },
                {
                    "id": "summarize",
                    "label": "summarize",
                    "kind": "rule",
                    "runtimeStatusKey": "rule:summarize",
                    "inputs": ["qc.tsv"],
                    "outputs": ["summary.tsv"],
                },
            ]
        },
    )
    mark_run_rules_running(
        cfg,
        run_id=str(claim["runId"]),
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(claim["attempt"]["attemptNumber"]),
    )
    mark_run_rules_failed(
        cfg,
        run_id=str(claim["runId"]),
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(claim["attempt"]["attemptNumber"]),
        stderr="Error in rule summarize:\n    command exited with 1",
    )

    rules = {item["ruleName"]: item for item in fetch_run_rules(cfg, str(claim["runId"]))["items"]}

    assert rules["quality_control"]["status"] == "running"
    assert rules["summarize"]["status"] == "failed"
    assert rules["summarize"]["exitCode"] == 1
    assert rules["summarize"]["events"][-1]["eventType"] == "rule_failed"
