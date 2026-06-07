from __future__ import annotations

import asyncio


def test_prepare_validation_queue_skips_waiting_resource_jobs(monkeypatch) -> None:
    from apps.api import tool_capability_service

    class Runtime:
        def __init__(self) -> None:
            self.created_payloads: list[dict[str, object]] = []
            self.waiting_tool_id = ""

        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert tool_ids
            if not self.waiting_tool_id:
                self.waiting_tool_id = tool_ids[0]
            return {
                "data": {
                    "byToolId": {
                        tool_id: {
                            "jobId": f"toolprep_waiting_resource_{index}",
                            "toolId": tool_id,
                            "status": "waiting_resource",
                            "stage": "waiting_resource",
                            "message": "Required database resource binding is missing.",
                            "errorCode": "RESOURCE_BINDING_MISSING",
                            "updatedAt": "2026-06-07T00:00:00Z",
                        }
                        for index, tool_id in enumerate(tool_ids)
                    }
                }
            }

        def list_tool_prepare_job_queue(
            self,
            *,
            status: str = "",
            limit: int = 50,
            offset: int = 0,
        ) -> dict[str, object]:
            return _empty_prepare_job_queue(limit=limit, offset=offset)

        def list_tool_index(
            self,
            *,
            query: str = "",
            limit: int = 50,
            offset: int = 0,
            source: str | None = None,
            state: str | None = None,
        ) -> dict[str, object]:
            return {"data": {"items": [], "total": 0, "hasMore": False}}

        def create_tool_prepare_job(self, payload: dict[str, object]) -> dict[str, object]:
            self.created_payloads.append(payload)
            return {
                "data": {
                    "jobId": f"toolprep_{payload['name']}",
                    "toolId": payload["id"],
                    "status": "queued",
                    "stage": "queued",
                }
            }

    runtime = Runtime()
    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: runtime)

    result = asyncio.run(
        tool_capability_service.prepare_tool_validation_queue_from_request(
            target_platform="linux-64",
            max_items=1,
        )
    )

    data = result["data"]
    assert data["queuedCount"] == 0
    assert runtime.created_payloads == []
    assert data["skippedCount"] == data["consideredCount"]
    assert {item["reason"] for item in data["skipped"]} == {"WAITING_RESOURCE"}
    assert data["skipped"][0]["latestPrepareJob"] == {
        "jobId": "toolprep_waiting_resource_0",
        "toolId": data["skipped"][0]["toolId"],
        "status": "waiting_resource",
        "stage": "waiting_resource",
        "message": "Required database resource binding is missing.",
        "errorCode": "RESOURCE_BINDING_MISSING",
        "updatedAt": "2026-06-07T00:00:00Z",
        "resultState": "",
        "workflowReady": False,
        "productionEnabled": False,
        "validationResultId": "",
        "evidenceId": "",
    }


def test_prepare_validation_queue_fills_batch_after_blocked_jobs(monkeypatch) -> None:
    from apps.api import tool_capability_service

    class Runtime:
        def __init__(self) -> None:
            self.created_payloads: list[dict[str, object]] = []
            self.blocked_tool_id = ""

        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert tool_ids
            if not self.blocked_tool_id:
                self.blocked_tool_id = tool_ids[0]
            return {
                "data": {
                    "byToolId": {
                        self.blocked_tool_id: {
                            "jobId": "toolprep_blocked",
                            "toolId": self.blocked_tool_id,
                            "status": "running",
                            "stage": "dry_run",
                            "message": "Validating existing job.",
                            "errorCode": "",
                            "updatedAt": "2026-06-07T00:00:00Z",
                        }
                    }
                }
            }

        def list_tool_index(
            self,
            *,
            query: str = "",
            limit: int = 50,
            offset: int = 0,
            source: str | None = None,
            state: str | None = None,
        ) -> dict[str, object]:
            return {"data": {"items": [], "total": 0, "hasMore": False}}

        def create_tool_prepare_job(self, payload: dict[str, object]) -> dict[str, object]:
            self.created_payloads.append(payload)
            return {
                "data": {
                    "jobId": f"toolprep_{payload['name']}",
                    "toolId": payload["id"],
                    "status": "queued",
                    "stage": "queued",
                }
            }

    runtime = Runtime()
    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: runtime)
    monkeypatch.setattr(
        tool_capability_service,
        "_target_acceptance_with_runtime_state",
        lambda *, runtime, target_platform: {
            "targetPlatform": target_platform,
            "targets": {"workflowReady": {"remaining": 2}},
            "validationQueue": {
                "items": [
                    {
                        "candidateId": "candidate-blocked",
                        "profileId": "blocked",
                        "preparePayload": {"id": "bioconda::blocked", "name": "blocked"},
                    },
                    {
                        "candidateId": "candidate-ready",
                        "profileId": "ready",
                        "preparePayload": {"id": "bioconda::ready", "name": "ready"},
                    },
                ]
            },
        },
    )

    result = asyncio.run(
        tool_capability_service.prepare_tool_validation_queue_from_request(
            target_platform="linux-64",
            max_items=1,
        )
    )

    data = result["data"]
    assert data["requested"] == 1
    assert data["consideredCount"] == 2
    assert data["queuedCount"] == 1
    assert data["skippedCount"] == 1
    assert data["skipped"][0]["reason"] == "ACTIVE_PREPARE_JOB"
    assert runtime.blocked_tool_id == "bioconda::blocked"
    assert data["queued"][0]["toolId"] == "bioconda::ready"
    assert [payload["id"] for payload in runtime.created_payloads] == [data["queued"][0]["toolId"]]
    assert data["batchPlan"] == {
        "planVersion": "tool-validation-batch-plan-v1",
        "status": "queued",
        "targetPlatform": "linux-64",
        "requested": 1,
        "queuedCount": 1,
        "skippedCount": 1,
        "jobIds": [data["queued"][0]["jobId"]],
        "poll": {
            "method": "GET",
            "path": "/api/v1/tools/prepare-jobs",
            "query": {"status": "", "limit": 50, "offset": 0},
        },
        "terminalStatuses": ["cancelled", "exhausted", "failed", "succeeded", "waiting_resource"],
        "activeStatuses": ["queued", "running"],
    }


def _empty_prepare_job_queue(*, limit: int = 50, offset: int = 0) -> dict[str, object]:
    return {
        "data": {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "statusCounts": {
                "cancelled": 0,
                "exhausted": 0,
                "failed": 0,
                "queued": 0,
                "running": 0,
                "succeeded": 0,
                "waiting_resource": 0,
            },
        }
    }
