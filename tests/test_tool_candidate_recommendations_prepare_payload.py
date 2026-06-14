from __future__ import annotations


def test_semantic_recommendation_candidate_exposes_prepare_payload() -> None:
    from apps.api.tool_candidate_recommendations import recommend_tool_candidates

    catalog = recommend_tool_candidates(
        output_port={"kind": "sequence_reads", "mimeType": "text/plain"},
        page=1,
        page_size=20,
    )

    fastqc = next(item for item in catalog["items"] if item["candidate"]["candidateId"] == "h2ometa-tool-profile::fastqc")
    assert fastqc["candidate"]["preparePayload"] == fastqc["preparePayload"]
    assert fastqc["candidate"]["preparePayload"]["id"] == "bioconda::fastqc"
    assert fastqc["candidate"]["preparePayload"]["ruleSpecDraft"]["requiresUserCompletion"] is False
    assert fastqc["blockReason"] == "WORKFLOW_TOOL_NOT_READY"


def test_semantic_recommendations_include_unified_catalog_wrapper_candidates() -> None:
    from apps.api.tool_candidate_recommendations import recommend_tool_candidates

    wrapper_candidate = {
        "candidateId": "snakemake-wrapper::v9.8.0/bio/wrapper-fastqc",
        "candidateKind": "snakemake-wrapper",
        "name": "wrapper-fastqc",
        "toolNames": ["wrapper-fastqc"],
        "contractState": "SnakemakeRenderable",
        "qualityTier": "draft-runnable",
        "preparePayload": {
            "id": "bioconda::wrapper-fastqc",
            "name": "wrapper-fastqc",
            "source": "bioconda",
            "packageSpec": "bioconda::wrapper-fastqc=1.0",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "inputs": [
                    {
                        "name": "reads",
                        "type": "file",
                        "kind": "sequence_reads",
                        "format": "http://edamontology.org/format_1930",
                    }
                ],
                "outputs": [{"name": "html", "path": "results/report.html"}],
                "commandTemplate": "wrapper-fastqc {input.reads:q}",
            },
            "ruleSpecDraft": {"requiresUserCompletion": False},
        },
    }

    catalog = recommend_tool_candidates(
        output_port={"kind": "sequence_reads", "format": "http://edamontology.org/format_1930"},
        catalog_items=[wrapper_candidate],
        page=1,
        page_size=50,
    )

    item = next(
        item
        for item in catalog["items"]
        if item["candidate"]["candidateId"] == "snakemake-wrapper::v9.8.0/bio/wrapper-fastqc"
    )
    assert item["decision"] == "recommended"
    assert item["candidate"]["candidateKind"] == "snakemake-wrapper"
    assert item["preparePayload"] == wrapper_candidate["preparePayload"]
    assert item["validationPlan"]["requiredState"] == "WorkflowReady"
    assert item["executionGate"]["canAddStep"] is False
    assert item["executionGate"]["nextAction"] == "prepare-tool"
    assert item["blockReason"] == "WORKFLOW_TOOL_NOT_READY"
    assert item["matchedFields"] == ["kind", "format"]
