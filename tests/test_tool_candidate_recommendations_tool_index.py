from __future__ import annotations

import asyncio


def test_tool_recommendation_service_marks_tool_index_workflow_ready_candidates_addable(monkeypatch) -> None:
    from apps.api import tool_capability_service

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert "bioconda::fastqc" not in tool_ids
            return {"data": {"byToolId": {}}}

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
            return {"data": {"items": [], "total": 0, "hasMore": False}}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())

    result = asyncio.run(
        tool_capability_service.recommend_tool_candidates_from_request(
            q="fastqc",
            output_port={"kind": "sequence_reads", "mimeType": "text/plain"},
            page=1,
            page_size=5,
        )
    )

    fastqc = next(item for item in result["data"]["items"] if item["candidate"].get("profileId") == "fastqc")
    assert fastqc["executionGate"] == {
        "currentState": "WorkflowReady",
        "requiredState": "WorkflowReady",
        "canAddStep": True,
        "nextAction": "add-step",
        "reason": "WORKFLOW_TOOL_READY",
        "sourceOfTruth": "registeredTool.toolContract",
        "toolRevisionId": "bioconda::fastqc@0.12.1",
        "toolId": "bioconda::fastqc",
    }
    assert "preparePayload" not in fastqc
    assert "validationPlan" not in fastqc


def test_tool_recommendation_service_passes_unified_catalog_candidates(monkeypatch) -> None:
    from apps.api import tool_capability_service

    captured: dict[str, object] = {}
    latest_tool_ids: list[str] = []
    wrapper_candidate = {
        "candidateId": "snakemake-wrapper::v9.8.0/bio/wrapper-fastqc",
        "candidateKind": "snakemake-wrapper",
        "name": "wrapper-fastqc",
        "contractState": "SnakemakeRenderable",
        "qualityTier": "draft-runnable",
        "preparePayload": {
            "id": "bioconda::wrapper-fastqc",
            "name": "wrapper-fastqc",
            "ruleTemplate": {
                "inputs": [{"name": "reads", "type": "file", "kind": "sequence_reads"}],
                "outputs": [{"name": "html", "path": "results/report.html"}],
            },
            "ruleSpecDraft": {"requiresUserCompletion": False},
        },
    }

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            latest_tool_ids.extend(tool_ids)
            return {"data": {"byToolId": {}}}

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

    def fake_catalog(*, runtime, query: str, target_platform: str, page: int, page_size: int) -> dict[str, object]:
        return {
            "items": [wrapper_candidate],
            "total": 1,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "qualityCounts": {"discovered": 0, "draftRunnable": 1, "workflowReady": 0, "productionEnabled": 0},
        }

    def fake_recommend_tool_candidates(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(tool_capability_service, "_search_tool_candidates_with_tool_index", fake_catalog)
    monkeypatch.setattr(tool_capability_service, "recommend_tool_candidates", fake_recommend_tool_candidates)

    asyncio.run(
        tool_capability_service.recommend_tool_candidates_from_request(
            q="wrapper",
            output_port={"kind": "sequence_reads"},
            page=1,
            page_size=5,
        )
    )

    assert captured["catalog_items"] == [wrapper_candidate]
    assert "bioconda::wrapper-fastqc" in latest_tool_ids
