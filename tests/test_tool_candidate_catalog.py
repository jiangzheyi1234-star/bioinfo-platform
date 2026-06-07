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


def test_conda_package_candidate_exposes_contract_state(monkeypatch) -> None:
    from apps.api import tool_candidate_catalog

    monkeypatch.setattr(tool_candidate_catalog, "find_snakemake_wrappers_for_tool", lambda name: [])
    monkeypatch.setattr(
        tool_candidate_catalog.DEFAULT_TOOL_CONTRACT_RESOLVER,
        "resolve_dependency",
        lambda hit, *, wrappers: {
            "requiresUserCompletion": False,
            "status": "ready-for-validation",
            "ruleTemplate": {"commandTemplate": "fastqc {input.reads}"},
        },
    )

    candidate = tool_candidate_catalog._conda_candidate_from_index_record(
        {
            "name": "fastqc",
            "summary": "Read QC",
            "latestVersion": "0.12.1",
            "versions": ["0.12.1"],
            "platforms": ["linux-64"],
        },
        target_platform="linux-64",
    )

    assert candidate["qualityTier"] == "draft-runnable"
    assert candidate["contractState"] == "SnakemakeRenderable"


def test_wrapper_candidate_exposes_contract_state() -> None:
    from apps.api.tool_candidate_model import snakemake_wrapper_candidate_fields

    fields = snakemake_wrapper_candidate_fields(
        {
            "wrapperRepository": "snakemake/snakemake-wrappers",
            "wrapperRef": "v9.8.0",
            "wrapperPath": "bio/fastqc",
            "wrapperIdentifier": "v9.8.0/bio/fastqc",
            "ruleSpecDraft": {"requiresUserCompletion": False},
        }
    )
    incomplete = snakemake_wrapper_candidate_fields(
        {
            "wrapperRepository": "snakemake/snakemake-wrappers",
            "wrapperRef": "v9.8.0",
            "wrapperPath": "bio/custom",
            "wrapperIdentifier": "v9.8.0/bio/custom",
            "ruleSpecDraft": {"requiresUserCompletion": True},
        }
    )

    assert fields["qualityTier"] == "draft-runnable"
    assert fields["contractState"] == "SnakemakeRenderable"
    assert incomplete["qualityTier"] == "discovered"
    assert incomplete["contractState"] == "Discovered"


def test_curated_tool_profile_catalog_attaches_snakemake_wrapper_evidence() -> None:
    from apps.api.tool_profile_catalog import catalog_tool_profiles

    catalog = catalog_tool_profiles(query="fastqc", page=1, page_size=10)

    fastqc = next(item for item in catalog["items"] if item["profileId"] == "fastqc")
    assert fastqc["snakemakeWrapperCount"] >= 1
    assert fastqc["snakemakeWrappers"][0]["wrapperPath"] == "bio/fastqc"
    assert fastqc["snakemakeWrappers"][0]["wrapperRepository"] == "snakemake/snakemake-wrappers"
    assert fastqc["snakemakeWrappers"][0]["sourceRef"]["type"] == "snakemake-wrapper"


def test_curated_tool_profile_wrapper_evidence_preserves_contract_hints(monkeypatch) -> None:
    from apps.api import tool_profile_external_refs
    from apps.api.tool_profile_catalog import catalog_tool_profiles

    monkeypatch.setattr(
        tool_profile_external_refs,
        "find_snakemake_wrappers_for_tool",
        lambda _tool_name: [
            {
                "wrapperRepository": "snakemake/snakemake-wrappers",
                "wrapperRef": "v9.8.0",
                "wrapperPath": "bio/fastqc",
                "wrapperIdentifier": "v9.8.0/bio/fastqc",
                "sourceRef": {"type": "snakemake-wrapper"},
                "wrapperContractHints": {
                    "description": "FastQC wrapper metadata",
                    "environment": {
                        "conda": {
                            "channels": ["conda-forge", "bioconda"],
                            "dependencies": ["fastqc =0.12.1"],
                        }
                    },
                },
            }
        ],
    )

    catalog = catalog_tool_profiles(query="fastqc", page=1, page_size=10)

    fastqc = next(item for item in catalog["items"] if item["profileId"] == "fastqc")
    assert fastqc["snakemakeWrappers"][0]["wrapperContractHints"] == {
        "description": "FastQC wrapper metadata",
        "environment": {
            "conda": {
                "channels": ["conda-forge", "bioconda"],
                "dependencies": ["fastqc =0.12.1"],
            }
        },
    }


def test_curated_tool_profile_catalog_exposes_external_registry_refs() -> None:
    from apps.api.tool_profile_catalog import catalog_tool_profiles

    catalog = catalog_tool_profiles(query="fastqc", page=1, page_size=10)

    fastqc = next(item for item in catalog["items"] if item["profileId"] == "fastqc")
    refs = fastqc["externalRefs"]
    refs_by_type = {ref["type"]: ref for ref in refs}

    assert refs_by_type["bioconda-package"] == {
        "type": "bioconda-package",
        "channel": "bioconda",
        "name": "fastqc",
        "url": "https://anaconda.org/bioconda/fastqc",
        "verified": True,
    }
    assert refs_by_type["biocontainers-container"] == {
        "type": "biocontainers-container",
        "registry": "quay.io",
        "namespace": "biocontainers",
        "name": "fastqc",
        "image": "quay.io/biocontainers/fastqc",
        "registryUrl": "https://biocontainers.pro/",
        "verified": False,
        "derivation": "bioconda-package-name",
    }
    assert refs_by_type["bio.tools-entry"] == {
        "type": "bio.tools-entry",
        "biotoolsId": "fastqc",
        "url": "https://bio.tools/fastqc",
        "verified": False,
        "derivation": "tool-name-normalized",
    }
    wrapper_refs = [ref for ref in refs if ref["type"] == "snakemake-wrapper"]
    assert wrapper_refs[0]["repository"] == "snakemake/snakemake-wrappers"
    assert wrapper_refs[0]["path"] == "bio/fastqc"
    assert wrapper_refs[0]["verified"] is True


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
    assert fastqc["preparePayload"]["packageSpec"] == "bioconda::fastqc=0.12.1"
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


def test_semantic_tool_recommendations_wait_on_active_prepare_jobs() -> None:
    from apps.api.tool_candidate_recommendations import recommend_tool_candidates

    catalog = recommend_tool_candidates(
        output_port={"kind": "sequence_reads", "mimeType": "text/plain"},
        page=1,
        page_size=20,
        latest_prepare_jobs_by_tool_id={
            "bioconda::fastqc": {
                "jobId": "toolprep_fastqc",
                "toolId": "bioconda::fastqc",
                "status": "running",
                "stage": "dry_run",
                "message": "Validating Snakemake workflow.",
                "errorCode": "",
                "updatedAt": "2026-06-07T00:00:00Z",
                "resultState": "",
                "workflowReady": False,
                "productionEnabled": False,
            }
        },
    )

    fastqc = next(item for item in catalog["items"] if item["candidate"]["candidateId"] == "h2ometa-tool-profile::fastqc")
    assert fastqc["latestPrepareJob"] == {
        "jobId": "toolprep_fastqc",
        "toolId": "bioconda::fastqc",
        "status": "running",
        "stage": "dry_run",
        "message": "Validating Snakemake workflow.",
        "errorCode": "",
        "updatedAt": "2026-06-07T00:00:00Z",
        "resultState": "",
        "workflowReady": False,
        "productionEnabled": False,
    }
    assert fastqc["executionGate"] == {
        "currentState": "SnakemakeRenderable",
        "requiredState": "WorkflowReady",
        "canAddStep": False,
        "nextAction": "wait-for-tool-validation",
        "reason": "TOOL_PREPARE_JOB_ACTIVE",
        "sourceOfTruth": "toolPrepareJob",
        "jobId": "toolprep_fastqc",
        "toolId": "bioconda::fastqc",
    }
    assert "preparePayload" not in fastqc
    assert fastqc["validationPlan"]["poll"]["pathTemplate"] == "/api/v1/tools/prepare-jobs/{jobId}"


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

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert tool_ids
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


def test_tool_candidate_service_merges_remote_tool_index(monkeypatch) -> None:
    from apps.api import tool_capability_service

    index_calls: list[dict[str, object]] = []

    class Runtime:
        def list_tool_index(
            self,
            *,
            query: str = "",
            limit: int = 50,
            offset: int = 0,
            source: str | None = None,
            state: str | None = None,
        ) -> dict[str, object]:
            index_calls.append({"query": query, "limit": limit, "offset": offset, "source": source, "state": state})
            totals = {"WorkflowReady": 1, "ProductionEnabled": 1, "SnakemakeRenderable": 0}
            if state:
                return {"data": {"items": [], "total": totals.get(state, 0), "hasMore": False}}
            return {
                "data": {
                    "items": [
                        {
                            "toolId": "bioconda::fastqc",
                            "latestStableRevisionId": "bioconda::fastqc@0.12.1",
                            "name": "fastqc",
                            "source": "bioconda",
                            "packageSpec": "bioconda::fastqc=0.12.1",
                            "facets": {"state": "WorkflowReady"},
                            "validationSummary": {"latestStatus": "succeeded"},
                            "qualityScore": 80,
                        },
                        {
                            "toolId": "bioconda::multiqc",
                            "latestStableRevisionId": "bioconda::multiqc@1.25",
                            "name": "multiqc",
                            "source": "bioconda",
                            "packageSpec": "bioconda::multiqc=1.25",
                            "facets": {"state": "ProductionEnabled"},
                            "validationSummary": {"latestStatus": "succeeded"},
                            "qualityScore": 100,
                        },
                    ],
                    "total": 2,
                    "hasMore": False,
                }
            }

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda q, *, target_platform, page, page_size: {
            "items": [],
            "query": q,
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "sourceCounts": {"condaPackages": 0, "snakemakeWrappers": 0, "toolProfiles": 0},
            "addableDraftCounts": {"condaPackages": 0, "snakemakeWrappers": 0, "toolProfiles": 0, "total": 0},
            "qualityCounts": {"discovered": 0, "draftRunnable": 0, "workflowReady": 0, "productionEnabled": 0},
        },
    )

    response = asyncio.run(
        tool_capability_service.search_tool_candidates_from_request(
            q="fast",
            target_platform="linux-64",
            page=1,
            page_size=10,
        )
    )

    catalog = response["data"]
    assert catalog["total"] == 2
    assert catalog["sourceCounts"]["registeredToolIndex"] == 2
    assert catalog["addableDraftCounts"]["registeredToolIndex"] == 0
    assert catalog["qualityCounts"] == {
        "discovered": 2,
        "draftRunnable": 0,
        "workflowReady": 1,
        "productionEnabled": 1,
    }
    assert [item["candidateKind"] for item in catalog["items"]] == ["registered-tool-index", "registered-tool-index"]
    assert catalog["items"][0]["qualityTier"] == "workflow-ready"
    assert catalog["items"][0]["toolContract"] == {"state": "WorkflowReady", "workflowReady": True, "productionEnabled": False}
    assert index_calls == [
        {"query": "fast", "limit": 10, "offset": 0, "source": None, "state": None},
        {"query": "fast", "limit": 1, "offset": 0, "source": None, "state": "SnakemakeRenderable"},
        {"query": "fast", "limit": 1, "offset": 0, "source": None, "state": "WorkflowReady"},
        {"query": "fast", "limit": 1, "offset": 0, "source": None, "state": "ProductionEnabled"},
    ]


def test_tool_recommendation_service_hydrates_latest_prepare_jobs(monkeypatch) -> None:
    from apps.api import tool_capability_service

    captured: dict[str, object] = {}

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert "bioconda::fastqc" in tool_ids
            return {
                "data": {
                    "byToolId": {
                        "bioconda::fastqc": {
                            "jobId": "toolprep_fastqc",
                            "toolId": "bioconda::fastqc",
                            "status": "running",
                        }
                    }
                }
            }

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
    assert captured["latest_prepare_jobs_by_tool_id"] == {
        "bioconda::fastqc": {
            "jobId": "toolprep_fastqc",
            "toolId": "bioconda::fastqc",
            "status": "running",
        }
    }
