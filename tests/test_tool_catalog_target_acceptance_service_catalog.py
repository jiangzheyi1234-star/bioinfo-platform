from __future__ import annotations

import asyncio


def test_target_acceptance_service_includes_unified_catalog_candidates(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance, tool_capability_service

    requested_page_sizes: list[int] = []
    latest_prepare_tool_ids: list[str] = []
    prepare_payload = {
        "id": "bioconda::aaa-ready",
        "name": "aaa-ready",
        "source": "bioconda",
        "sourceLabel": "Bioconda",
        "packageSpec": "bioconda::aaa-ready=1.0",
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "ruleSpecDraft": {"requiresUserCompletion": False},
        "ruleTemplate": {
            "inputs": [{"name": "reads", "kind": "sequence_reads", "format": "http://edamontology.org/format_1930"}],
            "outputs": [{"name": "html", "path": "results/report.html", "format": "http://edamontology.org/format_2331"}],
            "commandTemplate": "aaa-ready {input.reads:q}",
        },
    }

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert tool_ids
            latest_prepare_tool_ids.extend(tool_ids)
            return {
                "data": {
                    "byToolId": {
                        "bioconda::aaa-ready": {
                            "jobId": "toolprep_aaa",
                            "toolId": "bioconda::aaa-ready",
                            "status": "queued",
                            "stage": "queued",
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

    def fake_search_tool_candidates(query: str, *, target_platform: str, page: int, page_size: int) -> dict[str, object]:
        requested_page_sizes.append(page_size)
        items = []
        if page_size >= 100:
            items.append(
                {
                    "candidateId": "aaa-conda::ready",
                    "candidateKind": "conda-package",
                    "contractState": "SnakemakeRenderable",
                    "qualityTier": "draft-runnable",
                    "name": "aaa-ready",
                    "preparePayload": prepare_payload,
                    "snakemakeWrapperCount": 1,
                }
            )
        return {
            "items": items,
            "query": query,
            "total": 12894,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 30},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 30, "total": 12894},
            "qualityCounts": {"discovered": 12894, "draftRunnable": 31, "workflowReady": 0, "productionEnabled": 0},
        }

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(tool_capability_service, "search_tool_candidates", fake_search_tool_candidates)
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 30,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(30)],
        },
    )

    result = asyncio.run(_capability_graph_target_acceptance(tool_capability_service))

    assert requested_page_sizes == [100]
    assert "bioconda::aaa-ready" in latest_prepare_tool_ids
    queued_ids = {item["candidateId"] for item in result["validationQueue"]["items"]}
    assert "aaa-conda::ready" in queued_ids
    queue_item = next(item for item in result["validationQueue"]["items"] if item["candidateId"] == "aaa-conda::ready")
    assert queue_item["latestPrepareJob"]["jobId"] == "toolprep_aaa"
    assert queue_item["action"] == "wait-for-tool-validation"
    assert "preparePayload" not in queue_item


def test_target_acceptance_service_includes_prepare_job_queue_status(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance, tool_capability_service

    queue_requests: list[dict[str, object]] = []

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert tool_ids
            return {"data": {"byToolId": {}}}

        def list_tool_prepare_job_queue(
            self,
            *,
            status: str = "",
            limit: int = 50,
            offset: int = 0,
        ) -> dict[str, object]:
            queue_requests.append({"status": status, "limit": limit, "offset": offset})
            return {
                "data": {
                    "items": [
                        {
                            "jobId": "toolprep_fastqc",
                            "toolId": "bioconda::fastqc",
                            "status": "running",
                            "stage": "dry_run",
                        }
                    ],
                    "total": 4,
                    "limit": 50,
                    "offset": 0,
                    "statusCounts": {
                        "queued": 1,
                        "running": 1,
                        "succeeded": 1,
                        "failed": 0,
                        "waiting_resource": 1,
                        "cancelled": 0,
                        "exhausted": 0,
                    },
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

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 30,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(30)],
        },
    )

    result = asyncio.run(_capability_graph_target_acceptance(tool_capability_service))

    assert queue_requests == [{"status": "", "limit": 50, "offset": 0}]
    assert result["prepareJobQueue"] == {
        "items": [
            {
                "jobId": "toolprep_fastqc",
                "toolId": "bioconda::fastqc",
                "status": "running",
                "stage": "dry_run",
            }
        ],
        "total": 4,
        "limit": 50,
        "offset": 0,
        "statusCounts": {
            "cancelled": 0,
            "exhausted": 0,
            "failed": 0,
            "queued": 1,
            "running": 1,
            "succeeded": 1,
            "waiting_resource": 1,
        },
    }


async def _capability_graph_target_acceptance(tool_capability_service):
    result = await tool_capability_service.get_capability_graph_snapshot_from_request(
        q="",
        target_platform="linux-64",
        page=1,
        page_size=100,
        agent_selectable_only=False,
    )
    return result["data"]["targetAcceptance"]


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
