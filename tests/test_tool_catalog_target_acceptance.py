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
        "updatedAt": "2026-06-07T00:00:00Z",
        "workflowReady": True,
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
        "updatedAt": "2026-06-07T00:00:00Z",
        "resultState": "",
        "workflowReady": False,
        "productionEnabled": False,
    }
    assert report["targets"]["workflowReady"]["actual"] == 0
    assert report["targets"]["productionEnabled"]["actual"] == 0


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

    def fake_acceptance(**kwargs):
        captured.update(kwargs)
        return {"complete": False}

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(tool_capability_service, "bio_agent_catalog_target_acceptance", fake_acceptance)

    result = asyncio.run(tool_capability_service.get_tool_candidate_target_acceptance_from_request(target_platform="linux-64"))

    assert result == {"data": {"complete": False}}
    assert captured["registered_tools"] == [registered_tool]
    assert "bioconda::multiqc" in captured_tool_ids
    assert captured["latest_prepare_jobs_by_tool_id"] == {
        "bioconda::multiqc": {
            "jobId": "toolprep_multiqc",
            "toolId": "bioconda::multiqc",
            "status": "queued",
        }
    }


def test_prepare_validation_queue_enqueues_candidates_and_skips_active_jobs(monkeypatch) -> None:
    from apps.api import tool_capability_service

    class Runtime:
        def __init__(self) -> None:
            self.created_payloads: list[dict[str, object]] = []
            self.active_tool_id = ""

        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            assert tool_ids
            self.active_tool_id = tool_ids[0]
            return {
                "data": {
                    "byToolId": {
                        self.active_tool_id: {
                            "jobId": "toolprep_active",
                            "toolId": self.active_tool_id,
                            "status": "running",
                            "stage": "dry_run",
                        }
                    }
                }
            }

        def create_tool_prepare_job(self, payload: dict[str, object]) -> dict[str, object]:
            self.created_payloads.append(payload)
            return {
                "data": {
                    "jobId": f"toolprep_{payload['name']}",
                    "toolId": payload["id"],
                    "status": "queued",
                    "stage": "queued",
                }
            }

    runtime = Runtime()
    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: runtime)

    result = asyncio.run(
        tool_capability_service.prepare_tool_validation_queue_from_request(
            target_platform="linux-64",
            max_items=50,
        )
    )

    data = result["data"]
    assert data["targetPlatform"] == "linux-64"
    assert data["requested"] == 30
    assert data["consideredCount"] == 30
    assert data["activeStatuses"] == ["queued", "running"]
    assert data["terminalStatuses"] == ["cancelled", "failed", "succeeded", "waiting_resource"]
    assert data["queuedCount"] == 29
    assert data["skippedCount"] == 1
    assert [item["toolId"] for item in data["queued"]] == [payload["id"] for payload in runtime.created_payloads]
    assert all(item["status"] == "queued" for item in data["queued"])
    assert all(item["workflowReady"] is False for item in data["queued"])
    assert all(item["resultState"] == "" for item in data["queued"])
    assert all(item["pollPath"] == f"/api/v1/tools/prepare-jobs/{item['jobId']}" for item in data["queued"])
    assert data["skipped"] == [
        {
            "candidateId": data["skipped"][0]["candidateId"],
            "profileId": data["skipped"][0]["profileId"],
            "toolId": runtime.active_tool_id,
            "reason": "ACTIVE_PREPARE_JOB",
            "latestPrepareJob": {
                "jobId": "toolprep_active",
                "toolId": runtime.active_tool_id,
                "status": "running",
                "stage": "dry_run",
                "message": "",
                "errorCode": "",
                "updatedAt": "",
                "resultState": "",
                "workflowReady": False,
                "productionEnabled": False,
            },
        }
    ]
    assert data["targets"]["workflowReady"]["actual"] == 0
    assert data["remainingWorkflowReady"] == data["targets"]["workflowReady"]["remaining"]
