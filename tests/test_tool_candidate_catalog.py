from __future__ import annotations

import asyncio
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EDAM_FASTQ = "http://edamontology.org/format_1930"


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


def test_curated_tool_profile_catalog_attaches_snakemake_wrapper_evidence() -> None:
    from apps.api.tool_profile_catalog import catalog_tool_profiles

    catalog = catalog_tool_profiles(query="fastqc", page=1, page_size=10)

    fastqc = next(item for item in catalog["items"] if item["profileId"] == "fastqc")
    assert fastqc["snakemakeWrapperCount"] >= 1
    assert fastqc["snakemakeWrappers"][0]["wrapperPath"] == "bio/fastqc"
    assert fastqc["snakemakeWrappers"][0]["wrapperRepository"] == "snakemake/snakemake-wrappers"
    assert fastqc["snakemakeWrappers"][0]["sourceRef"]["type"] == "snakemake-wrapper"


def test_unified_tool_candidate_catalog_merges_sources(monkeypatch) -> None:
    from apps.api import tool_candidate_catalog

    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_conda_package_candidates",
        lambda *, query, target_platform, page, page_size: {
            "items": [
                {
                    "candidateId": "bioconda::fastp",
                    "candidateKind": "conda-package",
                    "qualityTier": "draft-runnable",
                    "name": "fastp",
                }
            ],
            "total": 1,
            "addableTotal": 1,
            "qualityCounts": {
                "discovered": 1,
                "draftRunnable": 1,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
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
            "addableTotal": 0,
            "qualityCounts": {
                "discovered": 1,
                "draftRunnable": 0,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
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
            "addableTotal": 1,
            "qualityCounts": {
                "discovered": 1,
                "draftRunnable": 1,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
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
    assert catalog["addableDraftCounts"] == {
        "condaPackages": 1,
        "snakemakeWrappers": 0,
        "toolProfiles": 1,
        "total": 2,
    }
    assert catalog["qualityCounts"] == {
        "discovered": 3,
        "draftRunnable": 2,
        "workflowReady": 0,
        "productionEnabled": 0,
    }
    assert catalog["total"] == 3


def test_unified_tool_candidate_catalog_uses_source_totals(monkeypatch) -> None:
    from apps.api import tool_candidate_catalog

    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_conda_package_candidates",
        lambda *, query, target_platform, page, page_size: {
            "items": [{"candidateId": "bioconda::fastp", "candidateKind": "conda-package"}],
            "total": 20,
            "addableTotal": 20,
            "qualityCounts": {
                "discovered": 20,
                "draftRunnable": 0,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_snakemake_wrappers",
        lambda *, query, page, page_size: {
            "items": [{"candidateId": "snakemake-wrapper::v9.8.0/bio/fastp", "candidateKind": "snakemake-wrapper"}],
            "total": 500,
            "addableTotal": 100,
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
            "addableTotal": 12,
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
    assert catalog["addableDraftCounts"] == {
        "condaPackages": 20,
        "snakemakeWrappers": 100,
        "toolProfiles": 12,
        "total": 132,
    }
    assert catalog["total"] == 532
    assert catalog["hasMore"] is True
    assert catalog["qualityCounts"] == {
        "discovered": 532,
        "draftRunnable": 112,
        "workflowReady": 36,
        "productionEnabled": 6,
    }


def test_unified_tool_candidate_catalog_uses_local_bioconda_index_for_empty_query(monkeypatch) -> None:
    from apps.api import tool_candidate_catalog

    source = (ROOT / "apps/api/tool_candidate_catalog.py").read_text(encoding="utf-8")
    assert "search_tool_capabilities" not in source

    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_snakemake_wrappers",
        lambda *, query, page, page_size: {
            "items": [],
            "total": 0,
            "addableTotal": 0,
            "qualityCounts": {
                "discovered": 0,
                "draftRunnable": 0,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "items": [],
            "total": 0,
            "addableTotal": 0,
            "qualityCounts": {
                "discovered": 0,
                "draftRunnable": 0,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_catalog,
        "search_bioconda_index_page",
        lambda query, *, page, page_size, cache_dir: {
            "items": [
                {
                    "name": "catalog-only-tool",
                    "summary": "Catalog-only package",
                    "latestVersion": "2.1.3",
                    "versions": ["2.1.3"],
                    "platforms": ["linux-64", "noarch"],
                }
            ],
            "total": 12398,
            "page": page,
            "pageSize": page_size,
            "hasMore": True,
            "indexAvailable": True,
        },
    )
    monkeypatch.setattr(tool_candidate_catalog, "find_snakemake_wrappers_for_tool", lambda name: [])

    catalog = tool_candidate_catalog.search_tool_candidates("", target_platform="linux-64", page=1, page_size=10)

    assert catalog["sourceCounts"] == {"condaPackages": 12398, "snakemakeWrappers": 0, "toolProfiles": 0}
    assert catalog["addableDraftCounts"] == {
        "condaPackages": 12398,
        "snakemakeWrappers": 0,
        "toolProfiles": 0,
        "total": 12398,
    }
    assert catalog["qualityCounts"]["discovered"] == 12398
    assert catalog["total"] == 12398
    assert catalog["hasMore"] is True
    item = catalog["items"][0]
    assert item["candidateId"] == "bioconda::catalog-only-tool"
    assert item["candidateKind"] == "conda-package"
    assert item["qualityTier"] == "discovered"
    assert item["sourceRef"] == {
        "type": "conda-package",
        "channel": "bioconda",
        "name": "catalog-only-tool",
        "url": "https://anaconda.org/bioconda/catalog-only-tool",
    }
    assert item["packageSpec"] == "bioconda::catalog-only-tool=2.1.3"
    assert item["targetPlatformSupported"] is True


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
    assert fastqc["candidate"]["contractState"] == "SnakemakeRenderable"
    assert fastqc["candidate"]["snakemakeWrapperCount"] >= 1
    assert fastqc["candidate"]["snakemakeWrappers"][0]["wrapperPath"] == "bio/fastqc"
    assert fastqc["executionGate"] == {
        "currentState": "SnakemakeRenderable",
        "requiredState": "WorkflowReady",
        "canAddStep": False,
        "nextAction": "prepare-tool",
        "reason": "WORKFLOW_TOOL_NOT_READY",
        "sourceOfTruth": "registeredTool.toolContract",
    }
    assert fastqc["validationPlan"]["requiredState"] == "WorkflowReady"
    assert fastqc["validationPlan"]["submit"]["path"] == "/api/v1/tools/prepare-jobs"
    assert fastqc["validationPlan"]["successCriteria"][-1] == {"toolContractField": "workflowReady", "value": True}
    assert fastqc["preparePayload"]["id"] == "bioconda::fastqc"
    assert fastqc["preparePayload"]["name"] == "fastqc"
    assert fastqc["preparePayload"]["source"] == "bioconda"
    assert fastqc["preparePayload"]["packageSpec"] == "bioconda::fastqc"
    assert fastqc["preparePayload"]["targetPlatform"] == "linux-64"
    assert fastqc["preparePayload"]["targetPlatformSupported"] is True
    assert fastqc["preparePayload"]["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
    assert fastqc["preparePayload"]["ruleSpecDraft"]["requiresUserCompletion"] is False
    assert fastqc["preparePayload"]["snakemakeWrappers"][0]["wrapperPath"] == "bio/fastqc"
    assert fastqc["preparePayload"]["ruleSpecDraft"]["lock"]["matchedWrapper"]["wrapperPath"] == "bio/fastqc"
    assert fastqc["preparePayload"]["ruleTemplate"] == fastqc["preparePayload"]["ruleSpecDraft"]["ruleTemplate"]
    assert "端口方向 output -> input" in fastqc["hardChecks"]
    assert any("kind" in value for value in fastqc["evidence"])


def test_semantic_tool_recommendations_match_edam_format_only() -> None:
    from apps.api.tool_candidate_recommendations import recommend_tool_candidates

    catalog = recommend_tool_candidates(
        output_port={"format": EDAM_FASTQ},
        page=1,
        page_size=20,
    )

    fastqc = next(
        item
        for item in catalog["items"]
        if item["candidate"]["candidateId"] == "h2ometa-tool-profile::fastqc"
    )
    assert fastqc["matchedFields"] == ["format"]
    assert fastqc["inputPort"]["format"] == EDAM_FASTQ
    assert fastqc["preparePayload"]["ruleTemplate"]["inputs"][0]["format"] == EDAM_FASTQ
    assert fastqc["preparePayload"]["ruleTemplate"] == fastqc["preparePayload"]["ruleSpecDraft"]["ruleTemplate"]
    assert any(f"format matches: {EDAM_FASTQ}" == value for value in fastqc["evidence"])


def test_semantic_tool_recommendations_allow_registered_workflow_ready_tools() -> None:
    from apps.api.tool_candidate_recommendations import recommend_tool_candidates

    catalog = recommend_tool_candidates(
        output_port={"kind": "sequence_reads", "mimeType": "text/plain"},
        page=1,
        page_size=20,
        registered_tools=[
            {
                "id": "bioconda::fastqc",
                "toolRevisionId": "bioconda::fastqc@1.0.0",
                "name": "fastqc",
                "toolContract": {
                    "state": "WorkflowReady",
                    "workflowReady": True,
                },
            }
        ],
    )

    fastqc = next(item for item in catalog["items"] if item["candidate"]["candidateId"] == "h2ometa-tool-profile::fastqc")

    assert fastqc["executionGate"] == {
        "currentState": "WorkflowReady",
        "requiredState": "WorkflowReady",
        "canAddStep": True,
        "nextAction": "add-step",
        "reason": "WORKFLOW_TOOL_READY",
        "sourceOfTruth": "registeredTool.toolContract",
        "toolRevisionId": "bioconda::fastqc@1.0.0",
        "toolId": "bioconda::fastqc",
    }
    assert "validationPlan" not in fastqc
    assert "preparePayload" not in fastqc


def test_tool_recommendation_service_hydrates_registered_tools(monkeypatch) -> None:
    from apps.api import tool_capability_service

    captured: dict[str, object] = {}
    registered_tool = {
        "id": "bioconda::fastqc",
        "toolRevisionId": "bioconda::fastqc@1.0.0",
        "name": "fastqc",
        "toolContract": {"state": "WorkflowReady", "workflowReady": True},
    }

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": [registered_tool]}}

    def fake_recommend_tool_candidates(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total": 0}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(tool_capability_service, "recommend_tool_candidates", fake_recommend_tool_candidates)

    result = asyncio.run(
        tool_capability_service.recommend_tool_candidates_from_request(
            q="fastqc",
            output_port={"kind": "sequence_reads"},
            page=1,
            page_size=5,
        )
    )

    assert result == {"data": {"items": [], "total": 0}}
    assert captured["registered_tools"] == [registered_tool]
