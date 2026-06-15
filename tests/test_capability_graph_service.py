from __future__ import annotations

import asyncio
import pytest


def test_capability_bundle_contract_fails_loudly_on_missing_required_field() -> None:
    from core.contracts.capability_bundle import validate_capability_bundle_contract

    with pytest.raises(ValueError, match="CAPABILITY_BUNDLE_FIELD_REQUIRED: approval"):
        validate_capability_bundle_contract(
            {
                "capabilityBundleVersion": "capability-bundle-v1",
                "capabilityId": "capability-bundle-v1:demo",
                "toolRevisionId": "bioconda::fastqc@0.12.1",
                "source": "bioconda",
                "version": "0.12.1",
                "inputs": [],
                "outputs": [],
                "parameters": {},
                "environmentLock": {},
                "risk": {},
                "permissions": {},
                "validationEvidence": {},
                "selectionSummary": {},
            }
        )


def test_capability_graph_service_marks_workflow_ready_profiles_agent_selectable() -> None:
    from apps.api.capability_graph_service import CapabilityGraphService
    from apps.api.tool_candidate_catalog import search_tool_candidates

    catalog = search_tool_candidates("fastqc", target_platform="linux-64", page=1, page_size=10)
    snapshot = CapabilityGraphService().snapshot(
        query="fastqc",
        target_platform="linux-64",
        registered_tools=[
            _ready_tool("fastqc", "0.12.1"),
        ],
        catalog=catalog,
    )

    assert snapshot["contractVersion"] == "capability-graph-snapshot-v1"
    assert snapshot["capabilityBundleVersion"] == "capability-bundle-v1"
    assert snapshot["selectionPolicy"]["canAddStepStates"] == ["WorkflowReady", "ProductionEnabled"]
    assert snapshot["selectionPolicy"]["bundleSourceOfTruth"] == "capability-bundle-v1"
    assert "fastqc" in snapshot["agentSelectableProfileIds"]
    fastqc = next(
        node
        for node in snapshot["semanticGraph"]["nodes"]
        if node.get("kind") == "ToolProfile" and node.get("profileId") == "fastqc"
    )
    assert fastqc["agentSelectable"] is True
    assert fastqc["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert fastqc["capabilityBundle"]["capabilityBundleVersion"] == "capability-bundle-v1"
    assert fastqc["capabilityBundle"]["capabilityId"]
    assert snapshot["registeredTools"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert snapshot["registeredTools"][0]["capabilityBundle"]["validationEvidence"]["status"] == "passed"
    assert snapshot["agentSelectableTools"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert snapshot["agentSelectableTools"][0]["capabilityBundle"]["environmentLock"]["dependencies"] == [
        "bioconda::fastqc=0.12.1"
    ]
    assert snapshot["selectionPolicy"]["sourceOfTruth"] == "CapabilityGraphSnapshot"
    assert snapshot["selectionPolicy"]["readinessSourceOfTruth"] == "registeredTool.toolContract"
    assert snapshot["capabilityBundleGate"]["selectable"] == 1
    assert snapshot["capabilityBundleGate"]["blocked"] == 0


def test_capability_graph_rejects_workflow_ready_tool_without_bundle_evidence() -> None:
    from apps.api.capability_graph_service import CapabilityGraphService

    missing_evidence = _ready_tool("fastqc", "0.12.1")
    missing_evidence.pop("validationSummary")
    missing_evidence["toolContract"] = {"state": "WorkflowReady", "workflowReady": True}

    snapshot = CapabilityGraphService().snapshot(registered_tools=[missing_evidence], catalog=_empty_catalog())

    assert snapshot["agentSelectableTools"] == []
    assert snapshot["agentSelectableProfileIds"] == []
    status = snapshot["registeredTools"][0]["capabilityBundleStatus"]
    assert status["agentSelectable"] is False
    assert "VALIDATION_EVIDENCE_REQUIRED" in status["blockedReasons"]
    assert status["nextAction"] == "run-validation"
    assert snapshot["capabilityBundleGate"]["blocked"] == 1
    assert snapshot["capabilityBundleGate"]["blockedTools"][0]["nextAction"] == "run-validation"


def test_capability_graph_builds_three_fixture_backed_bundles() -> None:
    from apps.api.capability_graph_service import CapabilityGraphService

    snapshot = CapabilityGraphService().snapshot(
        registered_tools=[
            _ready_tool("fastqc", "0.12.1"),
            _ready_tool("fastp", "0.23.4"),
            _ready_tool("seqkit", "2.8.2", name="seqkit-stats"),
        ],
        catalog=_empty_catalog(),
    )

    bundles = snapshot["capabilityBundles"]
    assert {bundle["profileId"] for bundle in bundles} == {"fastqc", "fastp", "seqkit-stats"}
    assert all(bundle["capabilityBundleVersion"] == "capability-bundle-v1" for bundle in bundles)
    assert all(bundle["toolRevisionId"] for bundle in bundles)
    assert all(bundle["inputs"] and bundle["outputs"] for bundle in bundles)
    assert all(bundle["environmentLock"]["dependencies"] for bundle in bundles)
    assert all(bundle["validationEvidence"]["fixture"]["inputs"] for bundle in bundles)
    assert all(bundle["validationEvidence"]["fixture"]["expectedArtifacts"] for bundle in bundles)
    assert all(bundle["agentSelectable"] is True for bundle in bundles)


def test_capability_graph_requires_approval_for_risky_bundle_permissions() -> None:
    from apps.api.capability_graph_service import CapabilityGraphService

    bracken = _ready_tool("bracken", "2.9")
    snapshot = CapabilityGraphService().snapshot(registered_tools=[bracken], catalog=_empty_catalog())

    assert snapshot["agentSelectableTools"] == []
    status = snapshot["registeredTools"][0]["capabilityBundleStatus"]
    assert status["nextAction"] == "request-approval"
    assert "CAPABILITY_APPROVAL_REQUIRED" in status["blockedReasons"]
    blocked = snapshot["capabilityBundleGate"]["blockedTools"][0]
    assert blocked["nextAction"] == "request-approval"

    approved = _ready_tool("bracken", "2.9")
    approved["capabilityApproval"] = {
        "approved": True,
        "policyVersion": "capability-approval-v1",
        "reason": "database path reviewed",
    }
    approved_snapshot = CapabilityGraphService().snapshot(registered_tools=[approved], catalog=_empty_catalog())

    assert approved_snapshot["agentSelectableTools"][0]["capabilityBundle"]["approval"] == {
        "required": True,
        "approved": True,
        "policyVersion": "capability-approval-v1",
        "reason": "database path reviewed",
    }


def test_capability_graph_uses_validated_database_resource_as_admission_evidence() -> None:
    from apps.api.capability_graph_service import CapabilityGraphService

    bracken = _ready_tool("bracken", "2.9")
    snapshot = CapabilityGraphService().snapshot(
        registered_tools=[bracken],
        catalog=_empty_catalog(),
        databases=[_available_database("db_bracken", template_id="bracken")],
    )

    bundle = snapshot["agentSelectableTools"][0]["capabilityBundle"]
    assert snapshot["capabilityBundleGate"]["selectable"] == 1
    assert bundle["approval"] == {
        "required": True,
        "approved": True,
        "policyVersion": "capability-admission-v1",
        "reason": "validated-database-resource",
    }
    assert bundle["admissionEvidence"]["databaseResources"][0]["resourceKey"] == "bracken_db"
    assert bundle["admissionEvidence"]["databaseResources"][0]["databaseIds"] == ["db_bracken"]
    assert bundle["admissionEvidence"]["databaseResources"][0]["databases"][0]["templateId"] == "bracken"


def test_capability_graph_reports_missing_database_resource_before_manual_approval() -> None:
    from apps.api.capability_graph_service import CapabilityGraphService

    snapshot = CapabilityGraphService().snapshot(
        registered_tools=[_ready_tool("bracken", "2.9")],
        catalog=_empty_catalog(),
        databases=[],
    )

    assert snapshot["agentSelectableTools"] == []
    status = snapshot["registeredTools"][0]["capabilityBundleStatus"]
    assert status["blockedReasons"] == ["DATABASE_RESOURCE_REQUIRED"]
    assert status["nextAction"] == "add-database"
    blocked = snapshot["capabilityBundleGate"]["blockedTools"][0]
    assert blocked["blockedReasons"] == ["DATABASE_RESOURCE_REQUIRED"]
    assert blocked["nextAction"] == "add-database"
    assert blocked["admissionEvidence"]["missingResources"][0]["resourceKey"] == "bracken_db"
    assert blocked["admissionEvidence"]["missingResources"][0]["acceptedTemplates"] == ["bracken"]


def test_capability_graph_snapshot_endpoint_uses_remote_tool_index(monkeypatch) -> None:
    from apps.api import tool_capability_service

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_databases(self) -> dict[str, object]:
            return {"data": {"items": []}}

        def list_tool_index(
            self,
            *,
            query: str = "",
            limit: int = 50,
            offset: int = 0,
            source: str | None = None,
            state: str | None = None,
        ) -> dict[str, object]:
            item = {
                "toolId": "bioconda::fastqc",
                "latestStableRevisionId": "bioconda::fastqc@0.12.1",
                "name": "fastqc",
                "state": state or "WorkflowReady",
                "source": "bioconda",
                "packageSpec": "bioconda::fastqc=0.12.1",
                "validationSummary": {
                    "latestResultId": "toolval_fastqc",
                    "latestStatus": "passed",
                    "evidenceId": "evid_fastqc",
                    "updatedAt": "2026-06-14T00:00:00Z",
                },
            }
            if state == "ProductionEnabled":
                return {"data": {"items": [], "total": 0, "hasMore": False}}
            if state == "WorkflowReady":
                return {"data": {"items": [item], "total": 1, "hasMore": False}}
            return {"data": {"items": [item], "total": 1, "hasMore": False}}

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            return {"data": {"byToolId": {}}}

        def list_tool_prepare_job_queue(
            self,
            *,
            status: str = "",
            limit: int = 50,
            offset: int = 0,
        ) -> dict[str, object]:
            return {
                "data": {
                    "items": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "statusCounts": {},
                }
            }

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "items": [],
            "query": query,
            "total": 0,
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "sourceCounts": {"condaPackages": 0, "snakemakeWrappers": 0, "toolProfiles": 0},
            "addableDraftCounts": {"condaPackages": 0, "snakemakeWrappers": 0, "toolProfiles": 0, "total": 0},
            "qualityCounts": {"discovered": 0, "draftRunnable": 0, "workflowReady": 0, "productionEnabled": 0},
        },
    )

    result = asyncio.run(
        tool_capability_service.get_capability_graph_snapshot_from_request(
            q="fastqc",
            target_platform="linux-64",
            page=1,
            page_size=10,
            agent_selectable_only=True,
        )
    )

    snapshot = result["data"]
    assert snapshot["catalog"]["sourceCounts"]["registeredToolIndex"] == 1
    assert snapshot["registeredToolCounts"]["workflowReady"] == 1
    assert snapshot["registeredTools"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert snapshot["agentSelectableTools"][0]["toolRevisionId"] == "bioconda::fastqc@0.12.1"
    assert snapshot["agentSelectableTools"][0]["capabilityBundle"]["capabilityId"]
    assert snapshot["agentSelectableProfileIds"] == ["fastqc"]
    assert snapshot["targetAcceptance"]["catalog"]["registeredToolCounts"]["workflowReady"] == 1
    assert snapshot["validationQueue"]["target"] == "workflowReady"
    assert snapshot["prepareJobQueue"]["total"] == 0
    assert {node["profileId"] for node in snapshot["semanticGraph"]["nodes"] if node["kind"] == "ToolProfile"} == {"fastqc"}


def test_capability_graph_snapshot_endpoint_admits_database_backed_tool_from_runtime_state(monkeypatch) -> None:
    from apps.api import tool_capability_service

    class Runtime:
        def list_tools(self) -> dict[str, object]:
            return {"data": {"items": [_ready_tool("bracken", "2.9")]}}

        def list_databases(self) -> dict[str, object]:
            return {"data": {"items": [_available_database("db_bracken", template_id="bracken")]}}

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

        def list_latest_tool_prepare_jobs(self, tool_ids: list[str]) -> dict[str, object]:
            return {"data": {"byToolId": {}}}

        def list_tool_prepare_job_queue(
            self,
            *,
            status: str = "",
            limit: int = 50,
            offset: int = 0,
        ) -> dict[str, object]:
            return {
                "data": {
                    "items": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "statusCounts": {},
                }
            }

    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: Runtime())
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: _empty_catalog(),
    )

    result = asyncio.run(
        tool_capability_service.get_capability_graph_snapshot_from_request(
            q="bracken",
            target_platform="linux-64",
            page=1,
            page_size=10,
            agent_selectable_only=True,
        )
    )

    snapshot = result["data"]
    assert snapshot["agentSelectableProfileIds"] == ["bracken"]
    assert snapshot["agentSelectableTools"][0]["capabilityBundle"]["approval"]["reason"] == "validated-database-resource"
    assert snapshot["capabilityBundleGate"]["blocked"] == 0


def test_capability_graph_database_admission_accepts_every_database_template() -> None:
    from apps.api.capability_graph_service import CapabilityGraphService
    from apps.remote_runner.database_templates import DATABASE_TEMPLATES, database_template_capabilities

    registered_tools = []
    databases = []
    for template_id, template in DATABASE_TEMPLATES.items():
        capabilities = database_template_capabilities(template)
        registered_tools.append(_ready_database_template_tool(template_id, capabilities=capabilities))
        databases.append(
            _available_database(
                f"db_{template_id}",
                template_id=template_id,
                capabilities=capabilities,
                db_type=str(template.get("type") or "reference"),
            )
        )

    snapshot = CapabilityGraphService().snapshot(
        registered_tools=registered_tools,
        catalog=_empty_catalog(),
        databases=databases,
    )

    assert snapshot["capabilityBundleGate"]["total"] == len(DATABASE_TEMPLATES)
    assert snapshot["capabilityBundleGate"]["selectable"] == len(DATABASE_TEMPLATES)
    assert snapshot["capabilityBundleGate"]["blocked"] == 0
    bundles_by_template = {
        bundle["profileId"].removeprefix("template-"): bundle
        for bundle in snapshot["capabilityBundles"]
    }
    assert set(bundles_by_template) == set(DATABASE_TEMPLATES)
    for template_id, bundle in bundles_by_template.items():
        assert bundle["approval"]["reason"] == "validated-database-resource"
        resource = bundle["admissionEvidence"]["databaseResources"][0]
        assert resource["resourceKey"] == "db"
        assert resource["databaseIds"] == [f"db_{template_id}"]
        assert resource["databases"][0]["templateId"] == template_id


def _ready_tool(profile_id: str, version: str, *, name: str | None = None) -> dict[str, object]:
    tool_name = name or profile_id
    package_name = "seqkit" if profile_id == "seqkit" else profile_id
    package_spec = f"bioconda::{package_name}={version}"
    return {
        "id": f"bioconda::{package_name}",
        "name": tool_name,
        "source": "bioconda",
        "version": version,
        "packageSpec": package_spec,
        "targetPlatform": "linux-64",
        "toolRevisionId": f"bioconda::{package_name}@{version}",
        "validationSummary": {
            "latestResultId": f"toolval_{package_name}",
            "latestStatus": "passed",
            "evidenceId": f"evid_{package_name}",
            "updatedAt": "2026-06-14T00:00:00Z",
        },
        "toolContract": {
            "state": "WorkflowReady",
            "workflowReady": True,
            "package": {
                "packageSpec": package_spec,
                "source": "bioconda",
                "version": version,
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
            },
            "validation": {
                "dryRun": {"status": "passed"},
                "smokeRun": {"status": "passed"},
                "outputValidation": {"status": "passed"},
            },
        },
    }


def _ready_database_template_tool(template_id: str, *, capabilities: list[str]) -> dict[str, object]:
    tool = _ready_tool(f"template-{template_id}", "1.0")
    tool["ruleTemplate"] = {
        "commandTemplate": "printf ok > {output.report:q}",
        "inputs": [
            {
                "name": "reads",
                "type": "file",
                "kind": "sequence_reads",
                "mimeType": "text/plain",
                "required": True,
            }
        ],
        "outputs": [
            {
                "name": "report",
                "path": f"results/{template_id}.txt",
                "kind": "report",
                "mimeType": "text/plain",
            }
        ],
        "params": {},
        "resources": {
            "threads": {"default": 1},
            "mem_mb": {"default": 128},
            "db": {
                "type": "database",
                "required": True,
                "acceptedTemplates": [template_id],
                "acceptedCapabilities": capabilities,
                "configKey": "db",
            },
        },
        "environment": {
            "conda": {
                "channels": ["conda-forge", "bioconda"],
                "dependencies": ["{packageSpec}"],
            }
        },
        "smokeTest": {
            "inputs": {
                "reads": {
                    "filename": "reads.fastq",
                    "content": "@smoke\nACGT\n+\nFFFF\n",
                    "mimeType": "text/plain",
                }
            },
            "timeoutSeconds": 60,
        },
    }
    return tool


def _available_database(
    database_id: str,
    *,
    template_id: str,
    capabilities: list[str] | None = None,
    db_type: str = "taxonomy",
) -> dict[str, object]:
    return {
        "id": database_id,
        "name": f"{template_id} database",
        "type": db_type,
        "version": "2026.06",
        "path": f"/data/{template_id}",
        "status": "available",
        "lastCheckedAt": "2026-06-15T00:00:00Z",
        "metadata": {
            "templateId": template_id,
            "capabilities": capabilities or ["taxonomy_database"],
            "pathMode": "directory",
            "availableReadLengths": [100, 150] if template_id == "bracken" else [],
        },
    }


def _empty_catalog() -> dict[str, object]:
    return {
        "items": [],
        "query": "",
        "total": 0,
        "page": 1,
        "pageSize": 10,
        "hasMore": False,
        "sourceCounts": {"condaPackages": 0, "snakemakeWrappers": 0, "toolProfiles": 0},
        "addableDraftCounts": {"condaPackages": 0, "snakemakeWrappers": 0, "toolProfiles": 0, "total": 0},
        "qualityCounts": {"discovered": 0, "draftRunnable": 0, "workflowReady": 0, "productionEnabled": 0},
    }
