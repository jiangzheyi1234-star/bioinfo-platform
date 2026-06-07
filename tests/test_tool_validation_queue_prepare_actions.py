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
    assert data["skipped"] == [
        {
            "candidateId": data["skipped"][0]["candidateId"],
            "profileId": data["skipped"][0]["profileId"],
            "toolId": data["skipped"][0]["toolId"],
            "reason": "WAITING_RESOURCE",
            "latestPrepareJob": {
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
            },
        }
    ]
