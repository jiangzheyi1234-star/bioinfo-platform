from __future__ import annotations

import asyncio


def test_capability_graph_service_marks_workflow_ready_profiles_agent_selectable() -> None:
    from apps.api.capability_graph_service import CapabilityGraphService
    from apps.api.tool_candidate_catalog import search_tool_candidates

    catalog = search_tool_candidates("fastqc", target_platform="linux-64", page=1, page_size=10)
    snapshot = CapabilityGraphService().snapshot(
        query="fastqc",
        target_platform="linux-64",
        registered_tools=[
            {
                "id": "bioconda::fastqc",
                "name": "fastqc",
                "toolRevisionId": "bioconda::fastqc@0.12.1",
                "toolContract": {"state": "WorkflowReady", "workflowReady": True},
            }
        ],
        catalog=catalog,
    )

    assert snapshot["contractVersion"] == "capability-graph-snapshot-v1"
    assert snapshot["selectionPolicy"]["canAddStepStates"] == ["WorkflowReady", "ProductionEnabled"]
    assert "fastqc" in snapshot["agentSelectableProfileIds"]
    fastqc = next(
        node
        for node in snapshot["semanticGraph"]["nodes"]
        if node.get("kind") == "ToolProfile" and node.get("profileId") == "fastqc"
    )
    assert fastqc["agentSelectable"] is True
    assert fastqc["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert snapshot["registeredTools"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert snapshot["agentSelectableTools"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert snapshot["selectionPolicy"]["sourceOfTruth"] == "CapabilityGraphSnapshot"
    assert snapshot["selectionPolicy"]["readinessSourceOfTruth"] == "registeredTool.toolContract"


def test_capability_graph_snapshot_endpoint_uses_remote_tool_index(monkeypatch) -> None:
    from apps.api import tool_capability_service

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_tool_index(
            self,
            *,
            query: str = "",
            limit: int = 50,
            offset: int = 0,
            source: str | None = None,
            state: str | None = None,
        ) -> dict[str, object]:
            item = {
                "toolId": "bioconda::fastqc",
                "latestStableRevisionId": "bioconda::fastqc@0.12.1",
                "name": "fastqc",
                "state": state or "WorkflowReady",
            }
            if state == "ProductionEnabled":
                return {"data": {"items": [], "total": 0, "hasMore": False}}
            if state == "WorkflowReady":
                return {"data": {"items": [item], "total": 1, "hasMore": False}}
            return {"data": {"items": [item], "total": 1, "hasMore": False}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            return {"data": {"byToolId": {}}}

        def list_tool_prepare_job_queue(
            self,
            *,
            status: str = "",
            limit: int = 50,
            offset: int = 0,
        ) -> dict[str, object]:
            return {
                "data": {
                    "items": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "statusCounts": {},
                }
            }

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
            "sourceCounts": {"condaPackages": 0, "snakemakeWrappers": 0, "toolProfiles": 0},
            "addableDraftCounts": {"condaPackages": 0, "snakemakeWrappers": 0, "toolProfiles": 0, "total": 0},
            "qualityCounts": {"discovered": 0, "draftRunnable": 0, "workflowReady": 0, "productionEnabled": 0},
        },
    )

    result = asyncio.run(
        tool_capability_service.get_capability_graph_snapshot_from_request(
            q="fastqc",
            target_platform="linux-64",
            page=1,
            page_size=10,
            agent_selectable_only=True,
        )
    )

    snapshot = result["data"]
    assert snapshot["catalog"]["sourceCounts"]["registeredToolIndex"] == 1
    assert snapshot["registeredToolCounts"]["workflowReady"] == 1
    assert snapshot["registeredTools"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert snapshot["agentSelectableTools"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert snapshot["agentSelectableProfileIds"] == ["fastqc"]
    assert snapshot["targetAcceptance"]["catalog"]["registeredToolCounts"]["workflowReady"] == 1
    assert snapshot["validationQueue"]["target"] == "workflowReady"
    assert snapshot["prepareJobQueue"]["total"] == 0
    assert {node["profileId"] for node in snapshot["semanticGraph"]["nodes"] if node["kind"] == "ToolProfile"} == {"fastqc"}
