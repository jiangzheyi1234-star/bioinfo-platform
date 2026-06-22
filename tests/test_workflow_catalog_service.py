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
