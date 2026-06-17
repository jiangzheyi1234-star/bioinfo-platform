from __future__ import annotations

import asyncio


def test_prepare_validation_queue_enqueues_candidates_and_skips_active_jobs(
    monkeypatch,
) -> None:
    from apps.api import tool_capability_service
    from apps.api.tool_profile_catalog import catalog_tool_profiles

    class Runtime:
        def __init__(self) -> None:
            self.created_payloads: list[dict[str, object]] = []
            self.active_tool_id = "bioconda::fastqc"

        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(
            self, tool_ids: list[str]
        ) -> dict[str, object]:
            assert tool_ids
            return {
                "data": {
                    "byToolId": {
                        self.active_tool_id: {
                            "jobId": "toolprep_active",
                            "toolId": self.active_tool_id,
                            "status": "running",
                            "stage": "dry_run",
                        }
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

        def create_tool_prepare_job(
            self, payload: dict[str, object]
        ) -> dict[str, object]:
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
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: catalog_tool_profiles(
            page=1, page_size=30
        ),
    )

    result = asyncio.run(
        tool_capability_service.prepare_tool_validation_queue_from_request(
            target_platform="linux-64",
            max_items=50,
        )
    )

    data = result["data"]
    assert data["targetPlatform"] == "linux-64"
    assert data["requested"] == 30
    assert data["consideredCount"] == 31
    assert data["activeStatuses"] == ["queued", "running"]
    assert data["terminalStatuses"] == [
        "cancelled",
        "exhausted",
        "failed",
        "succeeded",
        "waiting_resource",
    ]
    assert data["queuedCount"] == 30
    assert data["skippedCount"] == 1
    assert [item["toolId"] for item in data["queued"]] == [
        payload["id"] for payload in runtime.created_payloads
    ]
    assert all(item["status"] == "queued" for item in data["queued"])
    assert all(item["workflowReady"] is False for item in data["queued"])
    assert all(item["resultState"] == "" for item in data["queued"])
    assert all(
        item["pollPath"] == f"/api/v1/tools/prepare-jobs/{item['jobId']}"
        for item in data["queued"]
    )
    assert data["skipped"] == [
        {
            "candidateId": data["skipped"][0]["candidateId"],
            "profileId": data["skipped"][0]["profileId"],
            "toolId": runtime.active_tool_id,
            "reason": "ACTIVE_PREPARE_JOB",
            "latestPrepareJob": {
                "jobId": "toolprep_active",
                "toolId": runtime.active_tool_id,
                "status": "running",
                "stage": "dry_run",
                "message": "",
                "errorCode": "",
                "updatedAt": "",
                "resultState": "",
                "workflowReady": False,
                "productionEnabled": False,
                "validationResultId": "",
                "evidenceId": "",
            },
        }
    ]
    assert data["targets"]["workflowReady"]["actual"] == 0
    assert (
        data["remainingWorkflowReady"] == data["targets"]["workflowReady"]["remaining"]
    )


def test_validation_queue_tool_id_uses_latest_prepare_job_when_payload_hidden() -> None:
    from apps.api import tool_capability_service

    assert (
        tool_capability_service._queue_item_tool_id(
            {
                "preparePayload": {},
                "latestPrepareJob": {
                    "toolId": "bioconda::fastqc",
                    "status": "running",
                },
            }
        )
        == "bioconda::fastqc"
    )


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
