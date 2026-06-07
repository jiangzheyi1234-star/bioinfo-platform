from __future__ import annotations


def test_validation_queue_includes_unified_addable_candidates(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    candidate_prepare_payload = {
        "id": "bioconda::fastqc-wrapper",
        "name": "fastqc-wrapper",
        "source": "snakemake-wrapper",
        "packageSpec": "bioconda::fastqc=0.12.1",
        "targetPlatformSupported": True,
        "ruleSpecDraft": {"requiresUserCompletion": False},
        "ruleTemplate": {
            "inputs": [
                {
                    "name": "reads",
                    "type": "file",
                    "kind": "sequence_reads",
                    "format": "http://edamontology.org/format_1930",
                }
            ],
            "outputs": [
                {
                    "name": "html",
                    "path": "results/fastqc.html",
                    "kind": "report",
                    "format": "http://edamontology.org/format_2331",
                }
            ],
            "commandTemplate": "fastqc {input.reads:q}",
        },
    }
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 30},
            "addableDraftCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 100,
                "toolProfiles": 30,
                "total": 12528,
            },
            "qualityCounts": {
                "discovered": 12884,
                "draftRunnable": 112,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
            "items": [
                {
                    "candidateId": "snakemake-wrapper::v9.8.0/bio/fastqc",
                    "candidateKind": "snakemake-wrapper",
                    "contractState": "SnakemakeRenderable",
                    "qualityTier": "draft-runnable",
                    "toolNames": ["fastqc-wrapper"],
                    "preparePayload": candidate_prepare_payload,
                    "snakemakeWrapperCount": 1,
                    "wrapperContractHintCount": 1,
                    "wrapperContractHintFields": ["description", "environment"],
                    "wrapperCondaDependencies": ["fastqc =0.12.1"],
                },
                {
                    "candidateId": "bioconda::catalog-only",
                    "candidateKind": "conda-package",
                    "contractState": "Discovered",
                    "qualityTier": "discovered",
                    "name": "catalog-only",
                },
            ],
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

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(target_platform="linux-64")

    queued_ids = {item["candidateId"] for item in report["validationQueue"]["items"]}
    assert "snakemake-wrapper::v9.8.0/bio/fastqc" in queued_ids
    assert "bioconda::catalog-only" not in queued_ids
    wrapper_item = next(
        item
        for item in report["validationQueue"]["items"]
        if item["candidateId"] == "snakemake-wrapper::v9.8.0/bio/fastqc"
    )
    assert wrapper_item["candidateKind"] == "snakemake-wrapper"
    assert wrapper_item["currentState"] == "SnakemakeRenderable"
    assert wrapper_item["preparePayload"] == candidate_prepare_payload
    assert "ready-prepare-payload" in wrapper_item["priority"]["reasons"]
