from __future__ import annotations


def test_curated_profile_candidate_includes_prepare_payload() -> None:
    from apps.api.tool_profile_catalog import catalog_tool_profiles

    catalog = catalog_tool_profiles(query="fastqc", page=1, page_size=10)

    fastqc = next(item for item in catalog["items"] if item["profileId"] == "fastqc")
    prepare_payload = fastqc["preparePayload"]
    assert fastqc["contractState"] == "SnakemakeRenderable"
    assert fastqc["qualityTier"] == "draft-runnable"
    assert prepare_payload["id"] == "bioconda::fastqc"
    assert prepare_payload["source"] == "bioconda"
    assert prepare_payload["targetPlatformSupported"] is True
    assert prepare_payload["ruleSpecDraft"]["requiresUserCompletion"] is False
    assert prepare_payload["ruleTemplate"]["wrapper"] == "v9.8.0/bio/fastqc"
