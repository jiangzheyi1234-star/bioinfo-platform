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
