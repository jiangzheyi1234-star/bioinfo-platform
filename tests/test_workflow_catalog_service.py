from __future__ import annotations

import asyncio
from typing import Any

from apps.api.workflow_catalog_service import load_run_detail


def test_run_detail_normalizes_missing_result_id_to_exportable_id(monkeypatch) -> None:
    runtime = FakeRunDetailRuntime()
    monkeypatch.setattr("apps.api.workflow_catalog_service.runtime_service", lambda: runtime)

    payload = asyncio.run(load_run_detail("run_demo"))

    results = payload["data"]["results"]
    assert results["runId"] == "run_demo"
    assert results["resultId"] == "res_run_demo"
    assert runtime.preview_calls == [("res_run_demo", "art_summary")]


def test_run_detail_includes_normalized_failure_locator(monkeypatch) -> None:
    runtime = FakeFailedRunDetailRuntime()
    monkeypatch.setattr("apps.api.workflow_catalog_service.runtime_service", lambda: runtime)

    payload = asyncio.run(load_run_detail("run_failed"))

    locator = payload["data"]["failureLocator"]
    assert locator["schemaVersion"] == "run-failure-locator.v1"
    assert locator["available"] is True
    assert locator["reasonCode"] == "FAILED_RULE"
    assert locator["failedRule"]["ruleName"] == "align_reads"
    assert locator["failedRule"]["attemptId"] == "attempt_2"
    assert locator["failedRule"]["latestFailureEvent"]["eventType"] == "JOB_ERROR"
    assert locator["failedRule"]["logs"] == ["logs/align_reads.log"]
    assert locator["logContext"]["stderrLineCount"] == 35
    assert locator["logContext"]["stderrTail"][0] == "stderr 5"
    assert locator["artifactContext"]["relatedArtifactCount"] == 1
    assert locator["artifactContext"]["relatedArtifacts"][0]["artifactId"] == "art_bam"
    assert locator["artifactContext"]["lineageEdgeCount"] == 1


class FakeRunDetailRuntime:
    def __init__(self) -> None:
        self.preview_calls: list[tuple[str, str]] = []

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {
            "data": {
                "runId": run_id,
                "status": "completed",
                "workflowRevisionId": "wfrev_demo",
            }
        }

    def get_run_events(self, run_id: str) -> dict[str, Any]:
        return {"data": {"items": [], "runId": run_id}}

    def get_run_logs(self, *, run_id: str, stream: str, cursor: str | None) -> dict[str, Any]:
        return {"data": {"runId": run_id, "stream": stream, "cursor": cursor, "lines": []}}

    def get_run_results(self, run_id: str) -> dict[str, Any]:
        return {
            "data": {
                "runId": run_id,
                "resultDir": "results/run_demo",
                "artifacts": [
                    {
                        "artifactId": "art_summary",
                        "path": "summary.tsv",
                        "mimeType": "text/tab-separated-values",
                    }
                ],
            }
        }

    def get_run_rules(self, run_id: str) -> dict[str, Any]:
        return {"data": {"items": [], "runId": run_id}}

    def get_run_execution_context(self, run_id: str) -> dict[str, Any]:
        return {"data": {"runId": run_id}}

    def get_result_preview(self, *, result_id: str, artifact_id: str) -> dict[str, Any]:
        self.preview_calls.append((result_id, artifact_id))
        return {"data": {"resultId": result_id, "artifactId": artifact_id, "content": "sample\tcount\nA\t1\n"}}


class FakeFailedRunDetailRuntime(FakeRunDetailRuntime):
    def get_run(self, run_id: str) -> dict[str, Any]:
        return {
            "data": {
                "runId": run_id,
                "status": "failed",
                "stage": "running",
                "message": "Snakemake failed.",
                "workflowRevisionId": "wfrev_failed",
            }
        }

    def get_run_events(self, run_id: str) -> dict[str, Any]:
        return {
            "data": {
                "items": [
                    {
                        "eventId": "evt_failed",
                        "eventType": "run_failed",
                        "status": "failed",
                        "message": "Run failed.",
                        "createdAt": "2026-01-01T00:02:00Z",
                    }
                ],
                "runId": run_id,
            }
        }

    def get_run_logs(self, *, run_id: str, stream: str, cursor: str | None) -> dict[str, Any]:
        lines = [f"{stream} {index}" for index in range(35)] if stream == "stderr" else ["stdout 0"]
        return {"data": {"runId": run_id, "stream": stream, "cursor": cursor, "lines": lines}}

    def get_run_results(self, run_id: str) -> dict[str, Any]:
        return {
            "data": {
                "runId": run_id,
                "resultId": "res_run_failed",
                "resultDir": "results/run_failed",
                "artifacts": [
                    {
                        "artifactId": "art_bam",
                        "path": "outputs/aligned.bam",
                        "mimeType": "application/bam",
                        "sizeBytes": 128,
                    }
                ],
                "lineageEdges": [
                    {
                        "sourceArtifactId": "art_reads",
                        "targetArtifactId": "art_bam",
                        "relationship": "derived_from",
                    }
                ],
            }
        }

    def get_run_rules(self, run_id: str) -> dict[str, Any]:
        return {
            "data": {
                "runId": run_id,
                "items": [
                    {
                        "runRuleId": "rr_align",
                        "runId": run_id,
                        "ruleName": "align_reads",
                        "stepId": "align",
                        "runtimeStatusKey": "align_reads",
                        "status": "failed",
                        "attemptId": "attempt_2",
                        "attemptNumber": 2,
                        "leaseGeneration": 3,
                        "startedAt": "2026-01-01T00:01:00Z",
                        "finishedAt": "2026-01-01T00:02:00Z",
                        "exitCode": 1,
                        "message": "Command exited with status 1.",
                        "commandSummary": "snakemake --cores 1 align_reads",
                        "inputs": ["inputs/reads.fastq"],
                        "outputs": ["outputs/aligned.bam"],
                        "logs": ["logs/align_reads.log"],
                        "wildcards": {},
                        "events": [
                            {
                                "ruleEventId": "rre_error",
                                "eventType": "JOB_ERROR",
                                "status": "failed",
                                "message": "align_reads failed",
                                "createdAt": "2026-01-01T00:02:00Z",
                                "details": {"exitCode": 1},
                            }
                        ],
                    }
                ],
            }
        }
