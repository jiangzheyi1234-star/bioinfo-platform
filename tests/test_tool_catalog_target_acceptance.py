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
        "target": 20,
        "actual": 20,
        "passed": True,
        "remaining": 0,
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
    assert report["blockedTargets"] == ["workflowReady", "productionEnabled"]
    assert report["nextActions"] == [
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


def test_target_acceptance_service_hydrates_registered_tools(monkeypatch) -> None:
    from apps.api import tool_capability_service

    captured: dict[str, object] = {}
    registered_tool = {
        "id": "bioconda::fastqc",
        "toolContract": {"state": "WorkflowReady", "workflowReady": True},
    }

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": [registered_tool]}}

    def fake_acceptance(**kwargs):
        captured.update(kwargs)
        return {"complete": False}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(tool_capability_service, "bio_agent_catalog_target_acceptance", fake_acceptance)

    result = asyncio.run(tool_capability_service.get_tool_candidate_target_acceptance_from_request(target_platform="linux-64"))

    assert result == {"data": {"complete": False}}
    assert captured["registered_tools"] == [registered_tool]
