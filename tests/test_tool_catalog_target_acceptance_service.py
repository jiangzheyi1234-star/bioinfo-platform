from __future__ import annotations

import asyncio


def test_target_acceptance_service_hydrates_registered_tools(monkeypatch) -> None:
    from apps.api import tool_capability_service

    captured: dict[str, object] = {}
    captured_tool_ids: list[str] = []
    registered_tool = {
        "id": "bioconda::fastqc",
        "toolContract": {"state": "WorkflowReady", "workflowReady": True},
    }

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": [registered_tool]}}

        def list_latest_tool_prepare_jobs(
            self, tool_ids: list[str]
        ) -> dict[str, object]:
            captured_tool_ids.extend(tool_ids)
            return {
                "data": {
                    "byToolId": {
                        "bioconda::multiqc": {
                            "jobId": "toolprep_multiqc",
                            "toolId": "bioconda::multiqc",
                            "status": "queued",
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

    def fake_acceptance(**kwargs):
        captured.update(kwargs)
        return {"complete": False}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "items": [],
            "query": query,
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "sourceCounts": {
                "condaPackages": 0,
                "snakemakeWrappers": 0,
                "toolProfiles": 0,
            },
            "addableDraftCounts": {
                "condaPackages": 0,
                "snakemakeWrappers": 0,
                "toolProfiles": 0,
                "total": 0,
            },
            "qualityCounts": {
                "discovered": 0,
                "draftRunnable": 0,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_capability_service, "bio_agent_catalog_target_acceptance", fake_acceptance
    )

    result = asyncio.run(_capability_graph_target_acceptance(tool_capability_service))

    assert result["complete"] is False
    assert result["prepareJobQueue"]["total"] == 0
    assert captured["registered_tools"] == [registered_tool]
    assert "bioconda::multiqc" in captured_tool_ids
    assert captured["latest_prepare_jobs_by_tool_id"] == {
        "bioconda::multiqc": {
            "jobId": "toolprep_multiqc",
            "toolId": "bioconda::multiqc",
            "status": "queued",
        }
    }


def test_target_acceptance_service_counts_remote_tool_index(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance, tool_capability_service

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(
            self, tool_ids: list[str]
        ) -> dict[str, object]:
            assert tool_ids
            return {"data": {"byToolId": {}}}

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
            totals = {
                "SnakemakeRenderable": 100,
                "WorkflowReady": 100,
                "ProductionEnabled": 10,
            }
            if state:
                return {
                    "data": {
                        "items": [],
                        "total": totals.get(state, 0),
                        "hasMore": False,
                    }
                }
            return {"data": {"items": [], "total": 40, "hasMore": False}}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "items": [],
            "query": query,
            "total": 12884,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "sourceCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 466,
                "toolProfiles": 20,
            },
            "addableDraftCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 0,
                "toolProfiles": 20,
                "total": 12418,
            },
            "qualityCounts": {
                "discovered": 12884,
                "draftRunnable": 20,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 30,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(30)],
        },
    )

    result = asyncio.run(_capability_graph_target_acceptance(tool_capability_service))

    report = result
    assert report["targets"]["workflowReady"] == {
        "target": 100,
        "actual": 100,
        "passed": True,
        "remaining": 0,
    }
    assert report["targets"]["productionEnabled"] == {
        "target": 10,
        "actual": 10,
        "passed": True,
        "remaining": 0,
    }
    assert report["catalog"]["sourceCounts"]["registeredToolIndex"] == 40
    assert report["catalog"]["qualityCounts"]["workflowReady"] == 100
    assert report["catalog"]["qualityCounts"]["productionEnabled"] == 10


def test_target_acceptance_service_uses_tool_index_for_production_queue(
    monkeypatch,
) -> None:
    from apps.api import tool_candidate_target_acceptance, tool_capability_service

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(
            self, tool_ids: list[str]
        ) -> dict[str, object]:
            assert tool_ids
            return {"data": {"byToolId": {}}}

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
            if state == "WorkflowReady":
                return {
                    "data": {
                        "items": [
                            {
                                "toolId": "bioconda::fastqc",
                                "latestStableRevisionId": "bioconda::fastqc@0.12.1",
                                "name": "fastqc",
                                "facets": {"state": "WorkflowReady"},
                            }
                        ],
                        "total": 1,
                        "hasMore": False,
                    }
                }
            totals = {"SnakemakeRenderable": 30, "ProductionEnabled": 0}
            if state:
                return {
                    "data": {
                        "items": [],
                        "total": totals.get(state, 0),
                        "hasMore": False,
                    }
                }
            return {"data": {"items": [], "total": 1, "hasMore": False}}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "items": [],
            "query": query,
            "total": 12884,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "sourceCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 466,
                "toolProfiles": 30,
            },
            "addableDraftCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 0,
                "toolProfiles": 30,
                "total": 12428,
            },
            "qualityCounts": {
                "discovered": 12884,
                "draftRunnable": 30,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 30,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(30)],
        },
    )

    result = asyncio.run(_capability_graph_target_acceptance(tool_capability_service))

    production_queue = result["productionQueue"]
    assert production_queue["available"] == 1
    assert production_queue["items"][0]["toolId"] == "bioconda::fastqc"
    assert production_queue["items"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert production_queue["items"][0]["action"] == "submit-production-evidence"
    assert production_queue["items"][0]["productionPlan"]["requiredEvidenceFields"] == [
        "runId",
        "evidenceType",
        "message",
    ]
    assert production_queue["items"][0]["productionPlan"]["acceptedEvidenceTypes"] == [
        "real-data-acceptance",
        "real-database-acceptance",
    ]
    assert "packChecksum" in production_queue["items"][0]["productionPlan"]["scopedAttestation"]
    assert (
        production_queue["items"][0]["executionGate"]["sourceOfTruth"]
        == "registeredTool.toolContract"
    )


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
