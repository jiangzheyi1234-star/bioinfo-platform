from __future__ import annotations


def test_curated_tool_profile_catalog_exposes_tool_candidates() -> None:
    from apps.api.tool_profile_catalog import catalog_tool_profiles

    catalog = catalog_tool_profiles(query="fast", page=1, page_size=10)

    assert catalog["total"] == 2
    assert catalog["addableTotal"] == 2
    assert catalog["qualityCounts"]["discovered"] >= 6
    assert catalog["qualityCounts"]["draftRunnable"] >= 6
    fastp = next(item for item in catalog["items"] if item["profileId"] == "fastp")
    assert fastp["candidateId"] == "h2ometa-tool-profile::fastp"
    assert fastp["candidateKind"] == "h2ometa-tool-profile"
    assert fastp["qualityTier"] == "draft-runnable"
    assert fastp["sourceRef"] == {
        "type": "h2ometa-tool-profile",
        "profileId": "fastp",
        "version": "1",
    }
    assert fastp["toolNames"] == ["fastp"]
    assert fastp["preferredWrapperPaths"] == ["bio/fastp"]


def test_unified_tool_candidate_catalog_merges_sources(monkeypatch) -> None:
    from apps.api import tool_candidate_catalog

    monkeypatch.setattr(
        tool_candidate_catalog,
        "search_tool_capabilities",
        lambda query, *, target_platform, limit, page, page_size: {
            "data": {
                "items": [
                    {
                        "candidateId": "bioconda::fastp",
                        "candidateKind": "conda-package",
                        "qualityTier": "draft-runnable",
                        "name": "fastp",
                    }
                ],
                "total": 1,
            }
        },
    )
    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_snakemake_wrappers",
        lambda *, query, page, page_size: {
            "items": [
                {
                    "candidateId": "snakemake-wrapper::v9.8.0/bio/fastp",
                    "candidateKind": "snakemake-wrapper",
                    "qualityTier": "discovered",
                    "wrapperPath": "bio/fastp",
                }
            ],
            "total": 1,
        },
    )
    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "items": [
                {
                    "candidateId": "h2ometa-tool-profile::fastp",
                    "candidateKind": "h2ometa-tool-profile",
                    "qualityTier": "draft-runnable",
                    "profileId": "fastp",
                }
            ],
            "total": 1,
        },
    )

    catalog = tool_candidate_catalog.search_tool_candidates(
        "fastp",
        target_platform="linux-64",
        page=1,
        page_size=10,
    )

    assert [item["candidateKind"] for item in catalog["items"]] == [
        "h2ometa-tool-profile",
        "snakemake-wrapper",
        "conda-package",
    ]
    assert catalog["sourceCounts"] == {
        "condaPackages": 1,
        "snakemakeWrappers": 1,
        "toolProfiles": 1,
    }
    assert catalog["qualityCounts"] == {
        "discovered": 1,
        "draftRunnable": 2,
        "workflowReady": 0,
        "productionEnabled": 0,
    }
    assert catalog["total"] == 3


def test_unified_tool_candidate_catalog_uses_source_totals(monkeypatch) -> None:
    from apps.api import tool_candidate_catalog

    monkeypatch.setattr(
        tool_candidate_catalog,
        "search_tool_capabilities",
        lambda query, *, target_platform, limit, page, page_size: {
            "data": {
                "items": [{"candidateId": "bioconda::fastp", "candidateKind": "conda-package"}],
                "total": 20,
            }
        },
    )
    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_snakemake_wrappers",
        lambda *, query, page, page_size: {
            "items": [{"candidateId": "snakemake-wrapper::v9.8.0/bio/fastp", "candidateKind": "snakemake-wrapper"}],
            "total": 500,
            "qualityCounts": {
                "discovered": 500,
                "draftRunnable": 100,
                "workflowReady": 30,
                "productionEnabled": 4,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "items": [{"candidateId": "h2ometa-tool-profile::fastp", "candidateKind": "h2ometa-tool-profile"}],
            "total": 12,
            "qualityCounts": {
                "discovered": 12,
                "draftRunnable": 12,
                "workflowReady": 6,
                "productionEnabled": 2,
            },
        },
    )

    catalog = tool_candidate_catalog.search_tool_candidates("fastp", page=1, page_size=10)

    assert catalog["sourceCounts"] == {"condaPackages": 20, "snakemakeWrappers": 500, "toolProfiles": 12}
    assert catalog["total"] == 532
    assert catalog["hasMore"] is True
    assert catalog["qualityCounts"] == {
        "discovered": 513,
        "draftRunnable": 112,
        "workflowReady": 36,
        "productionEnabled": 6,
    }


def test_semantic_tool_recommendations_use_profile_input_ports() -> None:
    from apps.api.tool_candidate_recommendations import recommend_tool_candidates

    catalog = recommend_tool_candidates(
        output_port={"kind": "sequence_reads", "mimeType": "text/plain"},
        page=1,
        page_size=20,
    )

    candidate_ids = [item["candidate"]["candidateId"] for item in catalog["items"]]
    assert "h2ometa-tool-profile::fastqc" in candidate_ids
    assert "h2ometa-tool-profile::bracken" not in candidate_ids
    fastqc = next(item for item in catalog["items"] if item["candidate"]["candidateId"] == "h2ometa-tool-profile::fastqc")
    assert fastqc["decision"] == "recommended"
    assert fastqc["confidence"] >= 0.55
    assert fastqc["matchedFields"] == ["kind", "mimeType"]
    assert fastqc["inputPort"]["name"] == "reads"
    assert fastqc["candidate"]["qualityTier"] == "draft-runnable"
    assert "端口方向 output -> input" in fastqc["hardChecks"]
    assert any("kind" in value for value in fastqc["evidence"])
