from __future__ import annotations

import pytest

from apps.api.workflow_scenario_pack_service import (
    SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION,
    SCENARIO_PACK_CATALOG_SCHEMA_VERSION,
    SCENARIO_PACK_SCHEMA_VERSION,
    SCENARIO_SAMPLE_DATA_HANDOFF_SCHEMA_VERSION,
    WorkflowScenarioPackCatalogError,
    _scenario_definitions,
    _validate_scenario_definitions,
    list_workflow_scenario_packs,
)


REQUIRED_SCENARIO_PACK_FIELDS = {
    "schemaVersion",
    "packId",
    "scenarioId",
    "name",
    "vertical",
    "summary",
    "status",
    "priority",
    "operatorActionRequired",
    "noAutomaticExecution",
    "pipelineId",
    "firstRunPath",
    "workflowPath",
    "sampleData",
    "sampleDataHandoff",
    "requiredWorkflowReadyTools",
    "requiredDatabases",
    "databaseHandoff",
    "resultEvidence",
    "readinessChecks",
    "nextActions",
    "externalPracticeAnchors",
}


def test_workflow_scenario_pack_catalog_publishes_three_product_scenarios() -> None:
    payload = list_workflow_scenario_packs()["data"]
    items = payload["items"]

    assert payload["schemaVersion"] == SCENARIO_PACK_CATALOG_SCHEMA_VERSION
    assert [item["scenarioId"] for item in items] == [
        "moving-pictures-16s",
        "taxonomy-classification",
        "amr-annotation",
    ]
    for item in items:
        assert set(item) == REQUIRED_SCENARIO_PACK_FIELDS
        assert item["schemaVersion"] == SCENARIO_PACK_SCHEMA_VERSION
        assert item["noAutomaticExecution"] is True
        assert item["requiredWorkflowReadyTools"]
        assert 3 <= len(item["requiredWorkflowReadyTools"]) <= 5
        assert item["sampleDataHandoff"]["schemaVersion"] == SCENARIO_SAMPLE_DATA_HANDOFF_SCHEMA_VERSION
        assert item["sampleDataHandoff"]["noAutomaticExecution"] is True
        assert item["sampleDataHandoff"]["excludedActions"] == [
            "automatic-download",
            "automatic-fixture-generation",
            "unverified-example-data",
        ]
        assert item["databaseHandoff"]["schemaVersion"] == SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION
        assert item["databaseHandoff"]["noAutomaticExecution"] is True
        assert item["databaseHandoff"]["excludedActions"] == [
            "automatic-download",
            "automatic-extract",
            "automatic-install",
        ]
        for tool in item["requiredWorkflowReadyTools"]:
            assert {"toolId", "name", "kind", "role", "contractState", "acceptanceEvidence"} <= set(tool)
            assert "count" not in tool
            assert tool["contractState"] in {"planned", "workflow_ready"}
            assert "bioconda" not in tool["toolId"].lower()
        assert item["resultEvidence"]
        assert item["readinessChecks"]
        assert all(check["code"] and check["status"] in {"passed", "blocked"} for check in item["readinessChecks"])
        assert all(anchor.startswith("https://") for anchor in item["externalPracticeAnchors"])


def test_only_moving_pictures_scenario_is_ready_until_vertical_packs_have_real_gates() -> None:
    items = {item["scenarioId"]: item for item in list_workflow_scenario_packs()["data"]["items"]}

    first_run = items["moving-pictures-16s"]
    assert first_run["status"] == "ready"
    assert first_run["operatorActionRequired"] is False
    assert first_run["firstRunPath"] == "/workflows/first-run"
    assert first_run["requiredDatabases"] == []
    assert first_run["sampleDataHandoff"]["mode"] == "bundled_loader"
    assert first_run["sampleDataHandoff"]["status"] == "ready"
    assert first_run["sampleDataHandoff"]["operatorActionRequired"] is False
    assert {item["status"] for item in first_run["sampleDataHandoff"]["checklist"]} == {"passed"}
    assert first_run["databaseHandoff"]["mode"] == "none"
    assert first_run["databaseHandoff"]["status"] == "not_required"
    assert first_run["databaseHandoff"]["operatorActionRequired"] is False
    assert first_run["databaseHandoff"]["checklist"] == []
    assert {check["status"] for check in first_run["readinessChecks"]} == {"passed"}
    assert {tool["contractState"] for tool in first_run["requiredWorkflowReadyTools"]} == {"workflow_ready"}

    taxonomy = items["taxonomy-classification"]
    assert taxonomy["status"] == "blocked"
    assert taxonomy["operatorActionRequired"] is True
    assert taxonomy["firstRunPath"] == ""
    assert taxonomy["sampleDataHandoff"]["mode"] == "operator_provided"
    assert taxonomy["sampleDataHandoff"]["status"] == "operator_required"
    assert taxonomy["sampleDataHandoff"]["operatorActionRequired"] is True
    assert taxonomy["sampleDataHandoff"]["inputOptions"] == [
        {"role": "reads", "formats": ["fastq.gz"], "required": False},
        {"role": "contigs", "formats": ["fna", "fasta"], "required": False},
    ]
    assert {item["code"] for item in taxonomy["sampleDataHandoff"]["checklist"]} == {
        "SELECT_FIXTURE",
        "DECLARE_INPUT_ROLES",
        "VERIFY_CHECKSUMS",
        "RECORD_SOURCE",
        "RUN_ACCEPTANCE",
    }
    assert {item["status"] for item in taxonomy["sampleDataHandoff"]["checklist"]} == {"operator_required"}
    assert "taxonomy_database" in {item["capability"] for item in taxonomy["requiredDatabases"]}
    assert taxonomy["databaseHandoff"]["mode"] == "manual_external"
    assert taxonomy["databaseHandoff"]["status"] == "operator_required"
    assert taxonomy["databaseHandoff"]["operatorActionRequired"] is True
    assert taxonomy["databaseHandoff"]["readyScan"] == {
        "label": "Ready scan",
        "method": "POST",
        "path": "/api/v1/database-pack-ready-scans",
        "mutatesRegistry": False,
        "requiresOperatorReadyPath": True,
    }
    assert taxonomy["databaseHandoff"]["registration"] == {
        "label": "手动登记",
        "method": "POST",
        "path": "/api/v1/databases",
        "requiresReadyScan": True,
        "prefillSource": "database-pack-ready-scan.registrationPrefill",
    }
    assert {item["code"] for item in taxonomy["databaseHandoff"]["checklist"]} == {
        "SELECT_TEMPLATE",
        "VERIFY_CHECKSUM",
        "READY_SCAN",
        "REGISTER_DATABASE",
        "BIND_DATABASE",
        "REAL_DATABASE_ACCEPTANCE",
    }
    assert {item["status"] for item in taxonomy["databaseHandoff"]["checklist"]} == {"operator_required"}
    assert {"SCENARIO_TOOL_SLICE_READY", "SCENARIO_DATABASE_HANDOFF_READY", "SCENARIO_SAMPLE_DATA_READY"} <= {
        item["code"] for item in taxonomy["nextActions"]
    }
    assert {tool["contractState"] for tool in taxonomy["requiredWorkflowReadyTools"]} == {"planned"}

    amr = items["amr-annotation"]
    assert amr["status"] == "blocked"
    assert amr["operatorActionRequired"] is True
    assert amr["firstRunPath"] == ""
    assert amr["sampleDataHandoff"]["inputOptions"] == [
        {"role": "contigs", "formats": ["fna", "fasta"], "required": False},
        {"role": "proteins", "formats": ["faa", "fasta"], "required": False},
    ]
    assert amr["sampleDataHandoff"]["evidencePolicy"] == {
        "requiresChecksum": True,
        "requiresSource": True,
        "requiresInputRoles": True,
        "requiresSmallFixture": True,
        "requiresResultValidationCard": True,
    }
    assert {"amr_database", "annotation_database"} <= {item["capability"] for item in amr["requiredDatabases"]}
    assert amr["databaseHandoff"]["templateOptions"] == [
        {"capability": "amr_database", "templates": ["card_rgi"]},
        {"capability": "annotation_database", "templates": ["eggnog_mapper", "interproscan"]},
    ]
    assert amr["databaseHandoff"]["evidencePolicy"] == {
        "acceptedEvidenceType": "real-database-acceptance",
        "requiresRegisteredStatus": "available",
        "requiresRunResourceBinding": True,
        "rejectsCatalogLayerAsEvidence": True,
        "validationFixtureAccepted": False,
    }
    assert {"SCENARIO_TOOL_SLICE_READY", "SCENARIO_DATABASE_HANDOFF_READY", "SCENARIO_SAMPLE_DATA_READY"} <= {
        item["code"] for item in amr["nextActions"]
    }
    assert {tool["contractState"] for tool in amr["requiredWorkflowReadyTools"]} == {"planned"}


def test_workflow_scenario_pack_api_is_read_only_and_registered() -> None:
    route_source = _source("apps/api/workflow_scenario_pack_routes.py")
    main_source = _source("apps/api/main.py")
    service_source = _source("apps/api/workflow_scenario_pack_service.py")

    assert '@router.get("/api/v1/workflow-scenario-packs")' in route_source
    assert "@router.post" not in route_source
    assert "@router.patch" not in route_source
    assert "@router.delete" not in route_source
    assert "workflow_scenario_pack_router" in main_source
    assert "runtime_service()." not in service_source
    assert "list_reference_databases" not in service_source
    assert "add_database_from_request" not in service_source
    assert "scan_database_pack_ready_from_request" not in service_source
    assert "noAutomaticExecution" in service_source
    assert "automatic-fixture-generation" in service_source
    assert "unverified-example-data" in service_source
    assert "automatic-download" in service_source
    assert "automatic-extract" in service_source
    assert "automatic-install" in service_source
    assert 'or "/workflows/tools"' not in service_source


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda definitions: definitions[1].update({"packId": definitions[0]["packId"]}),
            "SCENARIO_PACK_ID_DUPLICATE",
        ),
        (
            lambda definitions: definitions[1].update({"scenarioId": definitions[0]["scenarioId"]}),
            "SCENARIO_ID_DUPLICATE",
        ),
        (
            lambda definitions: definitions[1].update({"priority": 0}),
            "SCENARIO_PRIORITY_INVALID",
        ),
        (
            lambda definitions: definitions[1]["nextActionTargets"].update({"SCENARIO_TOOL_SLICE_READY": "https://example.com"}),
            "SCENARIO_ACTION_TARGET_UNSUPPORTED",
        ),
        (
            lambda definitions: definitions[1]["externalPracticeAnchors"].append("http://example.com"),
            "SCENARIO_EXTERNAL_ANCHOR_UNSAFE",
        ),
        (
            lambda definitions: definitions[1]["requiredDatabases"][0]["templates"].append("unknown_db"),
            "SCENARIO_DATABASE_TEMPLATE_UNKNOWN",
        ),
        (
            lambda definitions: definitions[0].update({"pipelineId": "missing-ready-pipeline-v1"}),
            "SCENARIO_READY_PIPELINE_MISSING",
        ),
        (
            lambda definitions: definitions[0].update({"requiredWorkflowReadyTools": definitions[0]["requiredWorkflowReadyTools"][:2]}),
            "SCENARIO_TOOL_SLICE_SIZE_INVALID",
        ),
        (
            lambda definitions: definitions[0]["requiredWorkflowReadyTools"][0].pop("toolId"),
            "SCENARIO_TOOL_ID_REQUIRED",
        ),
        (
            lambda definitions: definitions[0]["requiredWorkflowReadyTools"][1].update(
                {"toolId": definitions[0]["requiredWorkflowReadyTools"][0]["toolId"]}
            ),
            "SCENARIO_TOOL_ID_DUPLICATE",
        ),
        (
            lambda definitions: definitions[0]["requiredWorkflowReadyTools"][0].update({"contractState": "installed"}),
            "SCENARIO_TOOL_CONTRACT_STATE_INVALID",
        ),
        (
            lambda definitions: definitions[0]["requiredWorkflowReadyTools"][0].update({"packageSpec": "bioconda::kraken2=2.1.3"}),
            "SCENARIO_TOOL_SLICE_GENERIC_BIOCONDA_UNSUPPORTED",
        ),
        (
            lambda definitions: definitions[0]["requiredWorkflowReadyTools"][0].update({"contractState": "planned"}),
            "SCENARIO_TOOL_SLICE_GATE_MISMATCH",
        ),
        (
            lambda definitions: definitions[1]["nextActionTargets"].pop("SCENARIO_SAMPLE_DATA_READY"),
            "SCENARIO_BLOCKED_GATE_ACTION_REQUIRED",
        ),
        (
            lambda definitions: definitions[1].update(
                {"gates": [gate for gate in definitions[1]["gates"] if gate["code"] != "SCENARIO_SAMPLE_DATA_READY"]}
            ),
            "SCENARIO_SAMPLE_DATA_HANDOFF_GATE_REQUIRED",
        ),
        (
            lambda definitions: definitions[1]["gates"].pop(0),
            "SCENARIO_VERTICAL_GATE_REQUIRED",
        ),
        (
            lambda definitions: definitions[1].update(
                {"gates": [gate for gate in definitions[1]["gates"] if gate["code"] != "SCENARIO_DATABASE_HANDOFF_READY"]}
            ),
            "SCENARIO_DATABASE_HANDOFF_GATE_REQUIRED",
        ),
        (
            lambda definitions: definitions[1]["gates"][0].update({"passed": True}),
            "SCENARIO_VERTICAL_GATE_MUST_BLOCK_UNTIL_ACCEPTED",
        ),
    ],
)
def test_workflow_scenario_pack_catalog_rejects_invalid_definitions(mutate, expected_code: str) -> None:
    definitions = _scenario_definitions()
    mutate(definitions)

    with pytest.raises(WorkflowScenarioPackCatalogError, match=expected_code):
        _validate_scenario_definitions(
            definitions,
            {"moving-pictures-16s-rulegraph-v1": {"enabled": True}},
        )


def test_workflow_scenario_pack_catalog_requires_pipeline_readiness_action_when_pipeline_missing() -> None:
    definitions = _scenario_definitions()
    definitions[1]["nextActionTargets"].pop("SCENARIO_PIPELINE_WORKFLOW_READY")

    with pytest.raises(WorkflowScenarioPackCatalogError, match="SCENARIO_BLOCKED_GATE_ACTION_REQUIRED"):
        _validate_scenario_definitions(
            definitions,
            {
                "moving-pictures-16s-rulegraph-v1": {"enabled": True},
                "amr-annotation-scenario-v1": {"enabled": True},
            },
        )


def _source(path: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
