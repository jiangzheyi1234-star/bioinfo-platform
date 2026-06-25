from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.rule_execution_projection import (
    mark_run_rules_failed,
    mark_run_rules_running,
    seed_run_rules_from_graph,
)
from apps.remote_runner.rule_execution_storage import fetch_run_rules
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.executor_rule_events import run_snakemake_with_rule_events
from apps.remote_runner.snakemake_rule_event_projection import project_snakemake_rule_events
from apps.remote_runner.snakemake_rule_event_projection import SnakemakeRuleEventProjector
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

    assert rules["quality_control"]["status"] == "blocked"
    assert rules["quality_control"]["events"][-1]["eventType"] == "rule_blocked"
    assert rules["summarize"]["status"] == "failed"
    assert rules["summarize"]["exitCode"] == 1
    assert rules["summarize"]["events"][-1]["eventType"] == "rule_failed"


def test_rule_projection_marks_all_rules_failed_when_stderr_has_no_rule_locator(tmp_path: Path) -> None:
    cfg, claim = _claim_for_projection(tmp_path)

    seed_run_rules_from_graph(
        cfg,
        run_id=str(claim["runId"]),
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(claim["attempt"]["attemptNumber"]),
        graph={
            "nodes": [
                {"id": "quality_control", "label": "quality_control", "kind": "rule"},
                {"id": "summarize", "label": "summarize", "kind": "rule"},
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
        stderr="WorkflowError: scheduler crashed before reporting a rule name",
    )

    rules = {item["ruleName"]: item for item in fetch_run_rules(cfg, str(claim["runId"]))["items"]}

    assert rules["quality_control"]["status"] == "failed"
    assert rules["summarize"]["status"] == "failed"
    assert rules["quality_control"]["events"][-1]["eventType"] == "rule_failed"
    assert rules["summarize"]["events"][-1]["eventType"] == "rule_failed"


def test_snakemake_logger_events_project_rule_status_and_metadata(tmp_path: Path) -> None:
    cfg, claim = _claim_for_projection(tmp_path)
    run_id = str(claim["runId"])
    attempt_id = str(claim["attemptId"])
    lease_generation = int(claim["leaseGeneration"])
    attempt_number = int(claim["attempt"]["attemptNumber"])
    seed_run_rules_from_graph(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        graph={
            "nodes": [
                {"id": "quality_control", "label": "quality_control", "kind": "rule"},
                {"id": "summarize", "label": "summarize", "kind": "rule"},
                {"id": "report", "label": "report", "kind": "rule"},
            ]
        },
    )
    event_log = tmp_path / "snakemake-events.jsonl"
    records = [
        {
            "event": "JOB_INFO",
            "jobId": 1,
            "ruleName": "quality_control",
            "input": ["reads.fastq.gz"],
            "output": ["qc.tsv"],
            "log": ["logs/qc.log"],
            "wildcards": {"sample": "S1"},
            "createdAt": "2099-06-07T10:00:01Z",
        },
        {"event": "JOB_STARTED", "jobIds": [1], "createdAt": "2099-06-07T10:00:02Z"},
        {
            "event": "SHELLCMD",
            "jobId": 1,
            "ruleName": "quality_control",
            "shellcmd": "fastqc reads.fastq.gz",
            "createdAt": "2099-06-07T10:00:03Z",
        },
        {"event": "JOB_FINISHED", "jobId": 1, "createdAt": "2099-06-07T10:00:04Z"},
        {
            "event": "JOB_INFO",
            "jobId": 2,
            "ruleName": "summarize",
            "input": ["qc.tsv"],
            "output": ["summary.tsv"],
            "createdAt": "2099-06-07T10:00:05Z",
        },
        {"event": "JOB_STARTED", "jobIds": [2], "createdAt": "2099-06-07T10:00:06Z"},
        {
            "event": "JOB_ERROR",
            "jobId": 2,
            "message": "Error in rule summarize",
            "file": str(tmp_path / "workflow" / "Snakefile"),
            "line": 42,
            "location": f"{tmp_path / 'workflow' / 'Snakefile'}:42",
            "traceback": f"{tmp_path / 'workflow' / 'Snakefile'}:42 TOKEN_SHOULD_NOT_LEAK",
            "createdAt": "2099-06-07T10:00:07Z",
        },
    ]
    event_log.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    result = project_snakemake_rule_events(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        event_log_path=event_log,
        workflow_succeeded=False,
    )

    rules = {item["ruleName"]: item for item in fetch_run_rules(cfg, run_id)["items"]}
    assert result["projected"] is True
    assert rules["quality_control"]["status"] == "succeeded"
    assert rules["quality_control"]["startedAt"] == "2099-06-07T10:00:02Z"
    assert rules["quality_control"]["finishedAt"] == "2099-06-07T10:00:04Z"
    assert rules["quality_control"]["commandSummary"] == "fastqc reads.fastq.gz"
    assert rules["quality_control"]["wildcards"] == {"sample": "S1"}
    assert rules["summarize"]["status"] == "failed"
    assert rules["summarize"]["exitCode"] == 1
    assert rules["report"]["status"] == "blocked"
    assert [event["eventType"] for event in rules["quality_control"]["events"][-3:]] == [
        "rule_started",
        "rule_command",
        "rule_finished",
    ]
    failure_event = rules["summarize"]["events"][-1]
    assert failure_event["eventType"] == "rule_failed"
    assert failure_event["details"]["file"] == str(tmp_path / "workflow" / "Snakefile")
    assert failure_event["details"]["line"] == 42
    assert failure_event["details"]["location"] == f"{tmp_path / 'workflow' / 'Snakefile'}:42"
    assert "TOKEN_SHOULD_NOT_LEAK" in failure_event["details"]["traceback"]


def test_snakemake_logger_events_mark_unexecuted_rules_skipped_on_success(tmp_path: Path) -> None:
    cfg, claim = _claim_for_projection(tmp_path)
    run_id = str(claim["runId"])
    attempt_id = str(claim["attemptId"])
    lease_generation = int(claim["leaseGeneration"])
    attempt_number = int(claim["attempt"]["attemptNumber"])
    seed_run_rules_from_graph(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        graph={"nodes": [{"id": "report", "label": "report", "kind": "rule"}]},
    )
    event_log = tmp_path / "empty-job-events.jsonl"
    event_log.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {"event": "JOB_INFO", "jobId": 1, "ruleName": "other", "createdAt": "2099-06-07T10:00:01Z"},
                {"event": "JOB_STARTED", "jobIds": [1], "createdAt": "2099-06-07T10:00:02Z"},
                {"event": "JOB_FINISHED", "jobId": 1, "createdAt": "2099-06-07T10:00:03Z"},
            ]
        ),
        encoding="utf-8",
    )

    project_snakemake_rule_events(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        event_log_path=event_log,
        workflow_succeeded=True,
    )

    rules = {item["ruleName"]: item for item in fetch_run_rules(cfg, run_id)["items"]}
    assert rules["report"]["status"] == "skipped"
    assert rules["report"]["events"][-1]["eventType"] == "rule_skipped"
    assert rules["other"]["status"] == "succeeded"


def test_snakemake_rule_event_projector_tails_complete_jsonl_lines_once(tmp_path: Path) -> None:
    cfg, claim = _claim_for_projection(tmp_path)
    run_id = str(claim["runId"])
    attempt_id = str(claim["attemptId"])
    lease_generation = int(claim["leaseGeneration"])
    attempt_number = int(claim["attempt"]["attemptNumber"])
    seed_run_rules_from_graph(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        graph={"nodes": [{"id": "quality_control", "label": "quality_control", "kind": "rule"}]},
    )
    event_log = tmp_path / "live-events.jsonl"
    projector = SnakemakeRuleEventProjector(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        event_log_path=event_log,
    )

    assert projector.poll()["reason"] == "event_log_missing"
    event_log.write_text(json.dumps({"event": "JOB_INFO", "jobId": 1, "ruleName": "quality_control"}), encoding="utf-8")
    assert projector.poll()["newEventCount"] == 0
    event_log.write_text(
        json.dumps({"event": "JOB_INFO", "jobId": 1, "ruleName": "quality_control"}) + "\n",
        encoding="utf-8",
    )
    assert projector.poll()["newEventCount"] == 1
    with event_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "JOB_STARTED", "jobIds": [1], "createdAt": "2099-06-07T10:00:02Z"}) + "\n")
        handle.write(json.dumps({"event": "JOB_FINISHED", "jobId": 1, "createdAt": "2099-06-07T10:00:04Z"}) + "\n")

    assert projector.poll()["newEventCount"] == 2
    assert projector.poll()["newEventCount"] == 0
    result = projector.finalize(workflow_succeeded=True)

    rules = {item["ruleName"]: item for item in fetch_run_rules(cfg, run_id)["items"]}
    event_types = [event["eventType"] for event in rules["quality_control"]["events"]]
    assert result["projected"] is True
    assert result["eventCount"] == 3
    assert rules["quality_control"]["status"] == "succeeded"
    assert event_types.count("rule_observed") == 1
    assert event_types.count("rule_started") == 1
    assert event_types.count("rule_finished") == 1


def test_run_snakemake_with_rule_events_polls_logger_events_while_engine_runs(tmp_path: Path) -> None:
    cfg, claim = _claim_for_projection(tmp_path)
    run_id = str(claim["runId"])
    attempt_id = str(claim["attemptId"])
    lease_generation = int(claim["leaseGeneration"])
    attempt_number = int(claim["attempt"]["attemptNumber"])
    seed_run_rules_from_graph(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        graph={"nodes": [{"id": "quality_control", "label": "quality_control", "kind": "rule"}]},
    )

    class Result:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    class LiveEngine:
        def run(self, *, event_log_path: Path, on_poll, **_kwargs):
            with event_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"event": "JOB_INFO", "jobId": 1, "ruleName": "quality_control"}) + "\n")
            on_poll()
            live_rules = {item["ruleName"]: item for item in fetch_run_rules(cfg, run_id)["items"]}
            assert live_rules["quality_control"]["events"][-1]["eventType"] == "rule_observed"
            with event_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"event": "JOB_STARTED", "jobIds": [1]}) + "\n")
                handle.write(json.dumps({"event": "JOB_FINISHED", "jobId": 1}) + "\n")
            on_poll()
            return Result()

    _, projection = run_snakemake_with_rule_events(
        cfg,
        LiveEngine(),
        snakefile=tmp_path / "Snakefile",
        work_dir=tmp_path,
        config_path=tmp_path / "config.json",
        event_log_path=tmp_path / "engine-live-events.jsonl",
        stdout_log=tmp_path / "stdout.log",
        stderr_log=tmp_path / "stderr.log",
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
    )

    rules = {item["ruleName"]: item for item in fetch_run_rules(cfg, run_id)["items"]}
    assert projection["projected"] is True
    assert projection["eventCount"] == 3
    assert rules["quality_control"]["status"] == "succeeded"
