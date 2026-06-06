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

    fastqc = next(item for item in result["data"]["items"] if item["candidate"]["profileId"] == "fastqc")
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
