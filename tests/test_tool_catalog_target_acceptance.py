from __future__ import annotations

import asyncio


def test_bio_agent_catalog_target_acceptance_reports_current_gates(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 466,
                "toolProfiles": 20,
            },
            "addableDraftCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 0,
                "toolProfiles": 20,
                "total": 12418,
            },
            "qualityCounts": {
                "discovered": 12884,
                "draftRunnable": 20,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 20,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(20)],
        },
    )

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(target_platform="linux-64")

    assert report["targetPlatform"] == "linux-64"
    assert report["complete"] is False
    assert report["targets"]["discovered"] == {
        "target": 500,
        "actual": 12884,
        "passed": True,
        "remaining": 0,
    }
    assert report["targets"]["addableDraft"] == {
        "target": 100,
        "actual": 12418,
        "passed": True,
        "remaining": 0,
    }
    assert report["targets"]["snakemakeRenderable"] == {
        "target": 30,
        "actual": 20,
        "passed": False,
        "remaining": 10,
    }
    assert report["targets"]["workflowReady"] == {
        "target": 30,
        "actual": 0,
        "passed": False,
        "remaining": 30,
    }
    assert report["targets"]["productionEnabled"] == {
        "target": 10,
        "actual": 0,
        "passed": False,
        "remaining": 10,
    }
    assert report["blockedTargets"] == ["snakemakeRenderable", "workflowReady", "productionEnabled"]
    assert report["nextActions"] == [
        {
            "target": "snakemakeRenderable",
            "remaining": 10,
            "action": "expand-catalog-source-coverage",
            "requiredState": "snakemakeRenderable",
            "evidence": "Catalog source counts and candidate quality counts",
        },
        {
            "target": "workflowReady",
            "remaining": 30,
            "action": "prepare-and-validate-tool-contracts",
            "requiredState": "WorkflowReady",
            "evidence": "Snakemake dry-run, smoke run, and output validation evidence",
        },
        {
            "target": "productionEnabled",
            "remaining": 10,
            "action": "promote-workflow-ready-tools-with-production-evidence",
            "requiredState": "ProductionEnabled",
            "evidence": "Scoped production attestation for tool revision, platform, environment, data scope, and policy",
        },
    ]
    assert report["catalog"]["sourceCounts"]["snakemakeWrappers"] == 466


def test_target_acceptance_uses_unified_catalog_draft_runnable_count(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 30},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 100, "toolProfiles": 30, "total": 12528},
            "qualityCounts": {"discovered": 12884, "draftRunnable": 112, "workflowReady": 0, "productionEnabled": 0},
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

    assert report["targets"]["snakemakeRenderable"] == {
        "target": 30,
        "actual": 112,
        "passed": True,
        "remaining": 0,
    }
    assert "snakemakeRenderable" not in report["blockedTargets"]


def test_bio_agent_catalog_target_acceptance_counts_registered_tool_contracts(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 466,
                "toolProfiles": 20,
            },
            "addableDraftCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 0,
                "toolProfiles": 20,
                "total": 12418,
            },
            "qualityCounts": {
                "discovered": 12884,
                "draftRunnable": 20,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 20,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(20)],
        },
    )

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(
        target_platform="linux-64",
        registered_tools=[
            {"id": "bioconda::fastqc", "toolContract": {"state": "WorkflowReady", "workflowReady": True}},
            {"id": "bioconda::fastp", "toolContract": {"state": "WorkflowReady", "workflowReady": True}},
            {"id": "bioconda::multiqc", "toolContract": {"state": "ProductionEnabled", "workflowReady": True}},
            {"id": "bioconda::draft", "toolContract": {"state": "SnakemakeRenderable", "workflowReady": False}},
        ],
    )

    assert report["targets"]["workflowReady"] == {
        "target": 30,
        "actual": 3,
        "passed": False,
        "remaining": 27,
    }
    assert report["targets"]["productionEnabled"] == {
        "target": 10,
        "actual": 1,
        "passed": False,
        "remaining": 9,
    }
    assert report["catalog"]["registeredToolCounts"] == {
        "total": 4,
        "workflowReady": 3,
        "productionEnabled": 1,
    }
    queue = report["validationQueue"]
    assert queue["target"] == "workflowReady"
    assert queue["requiredState"] == "WorkflowReady"
    assert queue["remaining"] == 27
    assert queue["available"] >= 1
    queued_ids = {item["candidateId"] for item in queue["items"]}
    assert "h2ometa-tool-profile::fastqc" not in queued_ids
    first_item = queue["items"][0]
    assert first_item["action"] == "prepare-tool"
    assert first_item["currentState"] == "SnakemakeRenderable"
    assert first_item["preparePayload"]["source"] == "bioconda"
    assert first_item["preparePayload"]["targetPlatformSupported"] is True
    assert first_item["preparePayload"]["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
    assert first_item["preparePayload"]["ruleSpecDraft"]["requiresUserCompletion"] is False

    production_queue = report["productionQueue"]
    assert production_queue["target"] == "productionEnabled"
    assert production_queue["requiredState"] == "ProductionEnabled"
    assert production_queue["remaining"] == 9
    assert production_queue["available"] == 2
    assert [item["toolId"] for item in production_queue["items"]] == ["bioconda::fastp", "bioconda::fastqc"]
    first_production_item = production_queue["items"][0]
    assert first_production_item["currentState"] == "WorkflowReady"
    assert first_production_item["requiredState"] == "ProductionEnabled"
    assert first_production_item["action"] == "submit-production-evidence"
    assert first_production_item["executionGate"] == {
        "currentState": "WorkflowReady",
        "requiredState": "ProductionEnabled",
        "canPromote": False,
        "nextAction": "submit-production-evidence",
        "reason": "PRODUCTION_EVIDENCE_REQUIRED",
        "sourceOfTruth": "registeredTool.toolContract",
    }
    assert first_production_item["productionPlan"]["submit"]["pathTemplate"] == "/api/v1/tools/{toolId}/production"
    assert "runId" in first_production_item["productionPlan"]["requiredEvidenceFields"]
    assert "real-data-acceptance" in first_production_item["productionPlan"]["acceptedEvidenceTypes"]


def test_validation_queue_prioritizes_wrapper_evidence_and_semantic_ports(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 20},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 0, "toolProfiles": 20, "total": 12418},
            "qualityCounts": {"discovered": 12884, "draftRunnable": 20, "workflowReady": 0, "productionEnabled": 0},
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 20,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(20)],
        },
    )

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(target_platform="linux-64")

    items = report["validationQueue"]["items"]
    assert len(items) >= 2
    assert all(items[index]["priority"]["score"] >= items[index + 1]["priority"]["score"] for index in range(len(items) - 1))

    fastqc = next(item for item in items if item["profileId"] == "fastqc")
    assert "snakemake-wrapper-evidence" in fastqc["priority"]["reasons"]
    assert "edam-port-semantics" in fastqc["priority"]["reasons"]
    assert "ready-prepare-payload" in fastqc["priority"]["reasons"]
    assert fastqc["evidence"]["snakemakeWrapperCount"] >= 1
    assert {"data", "format"}.issubset(set(fastqc["evidence"]["semanticPortFields"]))
    assert fastqc["evidence"]["semanticFormats"]
    assert fastqc["priority"]["score"] >= 80


def test_validation_queue_prioritizes_self_contained_profiles_before_required_resources(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 30},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 0, "toolProfiles": 30, "total": 12428},
            "qualityCounts": {"discovered": 12884, "draftRunnable": 30, "workflowReady": 0, "productionEnabled": 0},
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
    profile_ids = [str(item.get("profileId") or "") for item in report["validationQueue"]["items"]]

    assert profile_ids.index("bcftools-stats") < profile_ids.index("bowtie2-align")
    assert profile_ids.index("cutadapt") < profile_ids.index("bowtie2-align")
    bcftools = next(item for item in report["validationQueue"]["items"] if item["profileId"] == "bcftools-stats")
    bedtools = next(item for item in report["validationQueue"]["items"] if item["profileId"] == "bedtools-bamtobed")
    bowtie2 = next(item for item in report["validationQueue"]["items"] if item["profileId"] == "bowtie2-align")
    assert "self-contained-smoke" in bcftools["priority"]["reasons"]
    assert "self-contained-smoke" in bedtools["priority"]["reasons"]
    assert "smoke-fixture-placeholder" not in bedtools["priority"]["reasons"]
    assert bedtools["evidence"]["smokeFixtureQuality"] == "materialized"
    assert bedtools["preparePayload"]["ruleTemplate"]["inputs"][0]["kind"] == "alignment_sam"
    assert "samtools view -bS" in bedtools["preparePayload"]["ruleTemplate"]["commandTemplate"]
    assert "required-resources-pending" in bowtie2["priority"]["reasons"]
    assert bowtie2["evidence"]["requiredResourceKeys"] == ["bowtie2_index"]


def test_validation_evidence_summarizes_wrapper_contract_hints(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance
    from apps.api.tool_profile_sources import all_tool_profiles

    profile = next(profile for profile in all_tool_profiles() if profile.profile_id == "fastqc")
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "profile_snakemake_wrappers",
        lambda _profile: [
            {
                "wrapperPath": "bio/fastqc",
                "wrapperContractHints": {
                    "description": "FastQC wrapper metadata",
                    "input": ["FASTQ reads"],
                    "output": ["HTML report"],
                    "environment": {
                        "conda": {
                            "channels": ["conda-forge", "bioconda"],
                            "dependencies": ["fastqc =0.12.1", "snakemake-wrapper-utils =0.8.0"],
                        }
                    },
                },
            }
        ],
    )

    evidence = tool_candidate_target_acceptance._validation_evidence(
        profile=profile,
        prepare_payload={"ruleTemplate": profile.rule_template},
    )

    assert evidence["wrapperContractHintCount"] == 1
    assert evidence["wrapperContractHintFields"] == ["description", "environment", "input", "output"]
    assert evidence["wrapperCondaDependencies"] == ["fastqc =0.12.1", "snakemake-wrapper-utils =0.8.0"]


def test_validation_queue_item_includes_prepare_job_validation_plan(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 20},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 0, "toolProfiles": 20, "total": 12418},
            "qualityCounts": {"discovered": 12884, "draftRunnable": 20, "workflowReady": 0, "productionEnabled": 0},
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 20,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(20)],
        },
    )

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(target_platform="linux-64")

    fastqc = next(item for item in report["validationQueue"]["items"] if item["profileId"] == "fastqc")
    plan = fastqc["validationPlan"]
    assert plan["planVersion"] == "tool-validation-plan-v1"
    assert plan["requiredState"] == "WorkflowReady"
    assert plan["submit"] == {
        "method": "POST",
        "path": "/api/v1/tools/prepare-jobs",
        "payloadRef": "preparePayload",
    }
    assert plan["poll"] == {
        "method": "GET",
        "pathTemplate": "/api/v1/tools/prepare-jobs/{jobId}",
        "jobIdField": "jobId",
    }
    assert plan["terminalStatuses"]["success"] == ["succeeded"]
    assert plan["terminalStatuses"]["waiting"] == ["waiting_resource"]
    assert plan["terminalStatuses"]["failure"] == ["failed", "cancelled"]
    assert [stage["id"] for stage in plan["stages"]] == [
        "profile_schema_validation",
        "static_rulespec_validation",
        "dry_run",
        "smoke_run",
        "output_validation",
        "published",
    ]
    assert plan["successCriteria"] == [
        {"contractStatusKey": "dryRun", "status": "passed"},
        {"contractStatusKey": "smokeRun", "status": "passed"},
        {"contractStatusKey": "outputValidation", "status": "passed"},
        {"toolContractField": "workflowReady", "value": True},
    ]
    assert "prepare job succeeds" in plan["readinessBoundary"]


def test_validation_queue_item_exposes_execution_gate_without_marking_ready(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 20},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 0, "toolProfiles": 20, "total": 12418},
            "qualityCounts": {"discovered": 12884, "draftRunnable": 20, "workflowReady": 0, "productionEnabled": 0},
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 20,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(20)],
        },
    )

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(target_platform="linux-64")

    fastqc = next(item for item in report["validationQueue"]["items"] if item["profileId"] == "fastqc")
    assert fastqc["currentState"] == "SnakemakeRenderable"
    assert fastqc["executionGate"] == {
        "currentState": "SnakemakeRenderable",
        "requiredState": "WorkflowReady",
        "canAddStep": False,
        "nextAction": "prepare-tool",
        "reason": "WORKFLOW_TOOL_NOT_READY",
        "sourceOfTruth": "registeredTool.toolContract",
    }
    assert fastqc["executionGate"]["canAddStep"] is False
    assert report["targets"]["workflowReady"]["actual"] == 0


def test_validation_queue_item_includes_latest_prepare_job_without_counting_it_ready(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 20},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 0, "toolProfiles": 20, "total": 12418},
            "qualityCounts": {"discovered": 12884, "draftRunnable": 20, "workflowReady": 0, "productionEnabled": 0},
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 20,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(20)],
        },
    )
    latest_job = {
        "jobId": "toolprep_fastqc",
        "toolId": "bioconda::fastqc",
        "status": "waiting_resource",
        "stage": "waiting_resource",
        "message": "Required database resource binding is missing: db",
        "errorCode": "WORKFLOW_RESOURCE_BINDING_REQUIRED",
        "updatedAt": "2099-06-07T00:00:00Z",
        "workflowReady": True,
        "validationResultId": "toolval_fastqc",
        "evidenceId": "evid_fastqc",
    }

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(
        target_platform="linux-64",
        latest_prepare_jobs_by_tool_id={"bioconda::fastqc": latest_job},
    )

    fastqc = next(item for item in report["validationQueue"]["items"] if item["profileId"] == "fastqc")
    assert fastqc["latestPrepareJob"] == {
        "jobId": "toolprep_fastqc",
        "toolId": "bioconda::fastqc",
        "status": "waiting_resource",
        "stage": "waiting_resource",
        "message": "Required database resource binding is missing: db",
        "errorCode": "WORKFLOW_RESOURCE_BINDING_REQUIRED",
        "updatedAt": "2099-06-07T00:00:00Z",
        "resultState": "",
        "workflowReady": False,
        "productionEnabled": False,
        "validationResultId": "toolval_fastqc",
        "evidenceId": "evid_fastqc",
    }
    assert report["targets"]["workflowReady"]["actual"] == 0
    assert report["targets"]["productionEnabled"]["actual"] == 0


def test_validation_queue_item_waits_on_active_prepare_job(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 20},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 0, "toolProfiles": 20, "total": 12418},
            "qualityCounts": {"discovered": 12884, "draftRunnable": 20, "workflowReady": 0, "productionEnabled": 0},
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 20,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(20)],
        },
    )

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(
        target_platform="linux-64",
        latest_prepare_jobs_by_tool_id={
            "bioconda::fastqc": {
                "jobId": "toolprep_fastqc",
                "toolId": "bioconda::fastqc",
                "status": "running",
                "stage": "dry_run",
            }
        },
    )

    fastqc = next(item for item in report["validationQueue"]["items"] if item["profileId"] == "fastqc")
    assert fastqc["action"] == "wait-for-tool-validation"
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


def test_target_acceptance_service_hydrates_registered_tools(monkeypatch) -> None:
    from apps.api import tool_capability_service

    captured: dict[str, object] = {}
    captured_tool_ids: list[str] = []
    registered_tool = {
        "id": "bioconda::fastqc",
        "toolContract": {"state": "WorkflowReady", "workflowReady": True},
    }

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": [registered_tool]}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            captured_tool_ids.extend(tool_ids)
            return {
                "data": {
                    "byToolId": {
                        "bioconda::multiqc": {
                            "jobId": "toolprep_multiqc",
                            "toolId": "bioconda::multiqc",
                            "status": "queued",
                        }
                    }
                }
            }

        def list_tool_prepare_job_queue(
            self,
            *,
            status: str = "",
            limit: int = 50,
            offset: int = 0,
        ) -> dict[str, object]:
            return _empty_prepare_job_queue(limit=limit, offset=offset)

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

    def fake_acceptance(**kwargs):
        captured.update(kwargs)
        return {"complete": False}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(tool_capability_service, "bio_agent_catalog_target_acceptance", fake_acceptance)

    result = asyncio.run(_capability_graph_target_acceptance(tool_capability_service))

    assert result["complete"] is False
    assert result["prepareJobQueue"]["total"] == 0
    assert captured["registered_tools"] == [registered_tool]
    assert "bioconda::multiqc" in captured_tool_ids
    assert captured["latest_prepare_jobs_by_tool_id"] == {
        "bioconda::multiqc": {
            "jobId": "toolprep_multiqc",
            "toolId": "bioconda::multiqc",
            "status": "queued",
        }
    }


def test_target_acceptance_service_counts_remote_tool_index(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance, tool_capability_service

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert tool_ids
            return {"data": {"byToolId": {}}}

        def list_tool_prepare_job_queue(
            self,
            *,
            status: str = "",
            limit: int = 50,
            offset: int = 0,
        ) -> dict[str, object]:
            return _empty_prepare_job_queue(limit=limit, offset=offset)

        def list_tool_index(
            self,
            *,
            query: str = "",
            limit: int = 50,
            offset: int = 0,
            source: str | None = None,
            state: str | None = None,
        ) -> dict[str, object]:
            totals = {"SnakemakeRenderable": 30, "WorkflowReady": 30, "ProductionEnabled": 10}
            if state:
                return {"data": {"items": [], "total": totals.get(state, 0), "hasMore": False}}
            return {"data": {"items": [], "total": 40, "hasMore": False}}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "items": [],
            "query": query,
            "total": 12884,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 20},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 0, "toolProfiles": 20, "total": 12418},
            "qualityCounts": {"discovered": 12884, "draftRunnable": 20, "workflowReady": 0, "productionEnabled": 0},
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

    result = asyncio.run(_capability_graph_target_acceptance(tool_capability_service))

    report = result
    assert report["targets"]["workflowReady"] == {"target": 30, "actual": 30, "passed": True, "remaining": 0}
    assert report["targets"]["productionEnabled"] == {"target": 10, "actual": 10, "passed": True, "remaining": 0}
    assert report["catalog"]["sourceCounts"]["registeredToolIndex"] == 40
    assert report["catalog"]["qualityCounts"]["workflowReady"] == 30
    assert report["catalog"]["qualityCounts"]["productionEnabled"] == 10


def test_target_acceptance_service_uses_tool_index_for_production_queue(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance, tool_capability_service

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert tool_ids
            return {"data": {"byToolId": {}}}

        def list_tool_prepare_job_queue(
            self,
            *,
            status: str = "",
            limit: int = 50,
            offset: int = 0,
        ) -> dict[str, object]:
            return _empty_prepare_job_queue(limit=limit, offset=offset)

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
            totals = {"SnakemakeRenderable": 30, "ProductionEnabled": 0}
            if state:
                return {"data": {"items": [], "total": totals.get(state, 0), "hasMore": False}}
            return {"data": {"items": [], "total": 1, "hasMore": False}}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "items": [],
            "query": query,
            "total": 12884,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "sourceCounts": {"condaPackages": 12398, "snakemakeWrappers": 466, "toolProfiles": 30},
            "addableDraftCounts": {"condaPackages": 12398, "snakemakeWrappers": 0, "toolProfiles": 30, "total": 12428},
            "qualityCounts": {"discovered": 12884, "draftRunnable": 30, "workflowReady": 0, "productionEnabled": 0},
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

    result = asyncio.run(_capability_graph_target_acceptance(tool_capability_service))

    production_queue = result["productionQueue"]
    assert production_queue["available"] == 1
    assert production_queue["items"][0]["toolId"] == "bioconda::fastqc"
    assert production_queue["items"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert production_queue["items"][0]["action"] == "submit-production-evidence"
    assert production_queue["items"][0]["executionGate"]["sourceOfTruth"] == "registeredTool.toolContract"


async def _capability_graph_target_acceptance(tool_capability_service):
    result = await tool_capability_service.get_capability_graph_snapshot_from_request(
        q="",
        target_platform="linux-64",
        page=1,
        page_size=100,
        agent_selectable_only=False,
    )
    return result["data"]["targetAcceptance"]


def _empty_prepare_job_queue(*, limit: int = 50, offset: int = 0) -> dict[str, object]:
    return {
        "data": {
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
            "statusCounts": {
                "cancelled": 0,
                "exhausted": 0,
                "failed": 0,
                "queued": 0,
                "running": 0,
                "succeeded": 0,
                "waiting_resource": 0,
            },
        }
    }
