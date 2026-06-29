from __future__ import annotations

import pytest

from apps.api.workflow_scenario_pack_service import (
    SCENARIO_PACK_CATALOG_SCHEMA_VERSION,
    SCENARIO_PACK_SCHEMA_VERSION,
    SCENARIO_SAMPLE_DATA_HANDOFF_SCHEMA_VERSION,
    WorkflowScenarioPackCatalogError,
    _scenario_definitions,
    _validate_scenario_definitions,
    list_workflow_scenario_packs,
)
from apps.api.workflow_scenario_pack_database_handoff import (
    SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION,
    WorkflowScenarioDatabaseHandoffError,
    validate_database_handoff,
)
from apps.remote_runner.database_pack_catalog import list_downloadable_database_packs
from apps.api.workflow_scenario_pack_tool_slice import SCENARIO_TOOL_SLICE_HANDOFF_SCHEMA_VERSION
from apps.api.workflow_scenario_pack_tool_slice import (
    WorkflowScenarioToolSliceHandoffError,
    validate_tool_slice_handoff,
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
    "toolSliceHandoff",
    "requiredDatabases",
    "databaseHandoff",
    "resultEvidence",
    "pilotReadinessPlan",
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
        assert item["toolSliceHandoff"]["schemaVersion"] == SCENARIO_TOOL_SLICE_HANDOFF_SCHEMA_VERSION
        assert item["toolSliceHandoff"]["requiredState"] == "WorkflowReady"
        assert item["toolSliceHandoff"]["noAutomaticExecution"] is True
        assert item["toolSliceHandoff"]["excludedActions"] == [
            "generic-bioconda-import",
            "request-side-rulespec",
            "unvalidated-tool-selection",
        ]
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
        for tool in item["toolSliceHandoff"]["toolOptions"]:
            assert set(tool) == {"toolId", "name", "kind", "role", "contractState", "acceptanceEvidence"}
            assert {"ruleSpecDraft", "ruleTemplate", "commandTemplate", "packageSpec", "preparePayload"}.isdisjoint(tool)
        assert item["resultEvidence"]
        assert item["readinessChecks"]
        assert all(check["code"] and check["status"] in {"passed", "blocked"} for check in item["readinessChecks"])
        assert all(action["target"].startswith("/workflows") for action in item["nextActions"])
        assert all(entry["target"].startswith("/workflows") for entry in item["sampleDataHandoff"]["checklist"])
        assert all(entry["target"].startswith("/workflows") for entry in item["toolSliceHandoff"]["checklist"])
        assert all(entry["target"].startswith("/workflows") for entry in item["databaseHandoff"]["checklist"])
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
    assert first_run["toolSliceHandoff"]["status"] == "ready"
    assert first_run["toolSliceHandoff"]["operatorActionRequired"] is False
    assert first_run["toolSliceHandoff"]["sliceSize"] == {"min": 3, "max": 5, "actual": 4}
    assert {item["status"] for item in first_run["toolSliceHandoff"]["checklist"]} == {"passed"}
    assert first_run["databaseHandoff"]["mode"] == "none"
    assert first_run["databaseHandoff"]["status"] == "not_required"
    assert first_run["databaseHandoff"]["operatorActionRequired"] is False
    assert first_run["databaseHandoff"]["checklist"] == []
    assert first_run["databaseHandoff"]["packOptions"] == []
    assert "evidenceBundle" in first_run["resultEvidence"]
    assert first_run["pilotReadinessPlan"]["status"] == "ready"
    assert first_run["pilotReadinessPlan"]["noAutomaticExecution"] is True
    assert first_run["pilotReadinessPlan"]["blockingGateCodes"] == []
    assert first_run["pilotReadinessPlan"]["acceptanceEvidence"] == first_run["resultEvidence"]
    assert first_run["databaseHandoff"]["missingPackTemplates"] == []
    assert {check["status"] for check in first_run["readinessChecks"]} == {"passed"}
    assert {tool["contractState"] for tool in first_run["requiredWorkflowReadyTools"]} == {"workflow_ready"}

    taxonomy = items["taxonomy-classification"]
    assert taxonomy["status"] == "blocked"
    assert taxonomy["operatorActionRequired"] is True
    assert taxonomy["firstRunPath"] == ""
    assert taxonomy["sampleDataHandoff"]["mode"] == "operator_provided"
    assert taxonomy["sampleDataHandoff"]["status"] == "operator_required"
    assert taxonomy["sampleDataHandoff"]["operatorActionRequired"] is True
    assert taxonomy["toolSliceHandoff"]["status"] == "operator_required"
    assert taxonomy["toolSliceHandoff"]["operatorActionRequired"] is True
    assert taxonomy["toolSliceHandoff"]["sliceSize"] == {"min": 3, "max": 5, "actual": 3}
    assert {item["code"] for item in taxonomy["toolSliceHandoff"]["checklist"]} == {
        "CURATE_TOOL_SLICE",
        "LOCK_TOOL_REVISION",
        "CONFIRM_RULE_SPEC",
        "LOCK_ENVIRONMENT",
        "RUN_SMOKE_FIXTURE",
        "VALIDATE_OUTPUTS",
    }
    assert {item["status"] for item in taxonomy["toolSliceHandoff"]["checklist"]} == {"operator_required"}
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
    assert taxonomy["databaseHandoff"]["packOptions"] == [
        {
            "packId": "h2ometa-gtdbtk-r232-official",
            "templateId": "gtdbtk",
            "name": "GTDB-Tk R232 official reference pack",
            "version": "R232",
            "capabilities": ["taxonomy_database"],
            "checksum": "md5:25a59e0352b1fd150c589f56559767d4",
            "sourceUrl": (
                "https://data.gtdb.aau.ecogenomic.org/releases/release232/232.0/"
                "auxillary_files/gtdbtk_package/full_package/gtdbtk_r232_data.tar.gz"
            ),
            "readyDirHint": "/home/zyserver/databases/gtdbtk-r232-official/extracted/release",
            "registrationScriptPath": "scripts/register_gtdbtk_r232_database.py",
            "installedLayer": "production_full",
        }
    ]
    assert taxonomy["databaseHandoff"]["missingPackTemplates"] == ["centrifuge", "kaiju", "silva_qiime"]
    assert {item["code"] for item in taxonomy["databaseHandoff"]["checklist"]} == {
        "SELECT_TEMPLATE",
        "VERIFY_CHECKSUM",
        "READY_SCAN",
        "REGISTER_DATABASE",
        "BIND_DATABASE",
        "REAL_DATABASE_ACCEPTANCE",
    }
    assert {item["status"] for item in taxonomy["databaseHandoff"]["checklist"]} == {"operator_required"}
    assert taxonomy["resultEvidence"] == [
        "workflowRevision",
        "databaseCheck",
        "resultPackage",
        "validationCard",
        "evidenceBundle",
        "inputLineage",
        "outputChecksums",
    ]
    assert taxonomy["pilotReadinessPlan"] == {
        "schemaVersion": "h2ometa.workflow-scenario-pilot-readiness-plan.v1",
        "mode": "human-reviewed-scenario-pilot",
        "status": "operator_required",
        "operatorActionRequired": True,
        "noAutomaticExecution": True,
        "minimumInputs": [
            {"role": "reads", "formats": ["fastq.gz"], "required": False},
            {"role": "contigs", "formats": ["fna", "fasta"], "required": False},
        ],
        "toolSlice": {"requiredState": "WorkflowReady", "min": 3, "max": 5, "actual": 3},
        "databaseCapabilities": ["taxonomy_database"],
        "acceptanceEvidence": taxonomy["resultEvidence"],
        "blockingGateCodes": [
            "SCENARIO_PIPELINE_WORKFLOW_READY",
            "SCENARIO_TOOL_SLICE_READY",
            "SCENARIO_DATABASE_HANDOFF_READY",
            "SCENARIO_SAMPLE_DATA_READY",
        ],
        "acceptanceChecklist": [
            {
                "code": "CURATE_SMALL_FIXTURE",
                "label": "准备小型真实 fixture",
                "status": "operator_required",
                "target": "/workflows/tools",
                "evidence": "input roles, source, license, and SHA-256 recorded",
            },
            {
                "code": "LOCK_WORKFLOW_READY_SLICE",
                "label": "锁定 3-5 个 WorkflowReady 工具",
                "status": "operator_required",
                "target": "/workflows/tools",
                "evidence": "toolRevisionId, RuleSpec, environment lock, and smoke fixture evidence",
            },
            {
                "code": "REGISTER_REQUIRED_DATABASES",
                "label": "完成数据库 ready scan 与登记",
                "status": "operator_required",
                "target": "/workflows/databases",
                "evidence": "checksum, ready scan, registration prefill, and run resource binding",
            },
            {
                "code": "RUN_SCENARIO_ACCEPTANCE",
                "label": "运行一次场景验收",
                "status": "operator_required",
                "target": "/workflows",
                "evidence": "completed run with validationCard, resultPackage, and evidenceBundle",
            },
            {
                "code": "EXPORT_PORTABLE_EVIDENCE",
                "label": "导出可分享证据包",
                "status": "operator_required",
                "target": "/workflows/results",
                "evidence": "portable evidence bundle kept with full result package",
            },
        ],
        "excludedActions": [
            "automatic-database-install",
            "automatic-fixture-generation",
            "generic-bioconda-import",
            "unverified-evidence-bundle",
        ],
    }
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
    assert amr["toolSliceHandoff"]["evidencePolicy"] == {
        "requiresToolRevisionId": True,
        "requiresCapabilityBundle": True,
        "requiresRuleSpec": True,
        "requiresEnvironmentLock": True,
        "requiresSmokeFixture": True,
        "requiresOutputValidation": True,
        "productionEvidenceOptional": True,
    }
    assert "evidenceBundle" in amr["resultEvidence"]
    assert amr["pilotReadinessPlan"]["databaseCapabilities"] == ["amr_database", "annotation_database"]
    assert amr["pilotReadinessPlan"]["blockingGateCodes"] == [
        "SCENARIO_PIPELINE_WORKFLOW_READY",
        "SCENARIO_TOOL_SLICE_READY",
        "SCENARIO_DATABASE_HANDOFF_READY",
        "SCENARIO_SAMPLE_DATA_READY",
    ]
    assert [item["role"] for item in amr["toolSliceHandoff"]["toolOptions"]] == [
        "input_qc",
        "amr_detection",
        "annotation",
    ]
    assert {"amr_database", "annotation_database"} <= {item["capability"] for item in amr["requiredDatabases"]}
    assert amr["databaseHandoff"]["templateOptions"] == [
        {"capability": "amr_database", "templates": ["card_rgi"]},
        {"capability": "annotation_database", "templates": ["eggnog_mapper", "interproscan"]},
    ]
    assert amr["databaseHandoff"]["packOptions"] == []
    assert amr["databaseHandoff"]["missingPackTemplates"] == ["card_rgi", "eggnog_mapper", "interproscan"]
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
    tool_slice_source = _source("apps/api/workflow_scenario_pack_tool_slice.py")
    database_handoff_source = _source("apps/api/workflow_scenario_pack_database_handoff.py")

    assert '@router.get("/api/v1/workflow-scenario-packs")' in route_source
    assert "@router.post" not in route_source
    assert "@router.patch" not in route_source
    assert "@router.delete" not in route_source
    assert "workflow_scenario_pack_router" in main_source
    assert "runtime_service()." not in service_source
    assert "list_reference_databases" not in service_source
    assert "add_database_from_request" not in service_source
    assert "scan_database_pack_ready_from_request" not in service_source
    assert "list_downloadable_database_packs" in database_handoff_source
    assert "runtime_service()." not in database_handoff_source
    assert "scan_database_pack_ready_from_request" not in database_handoff_source
    assert "add_database_from_request" not in database_handoff_source
    assert "noAutomaticExecution" in service_source
    assert "noAutomaticExecution" in database_handoff_source
    assert "automatic-fixture-generation" in service_source
    assert "unverified-example-data" in service_source
    assert "automatic-download" in database_handoff_source
    assert "automatic-extract" in database_handoff_source
    assert "automatic-install" in database_handoff_source
    assert "request-side-rulespec" in tool_slice_source
    assert "generic-bioconda-import" in tool_slice_source
    assert "capability-bundle-v1" in tool_slice_source
    assert "runtime_service()." not in tool_slice_source
    assert "prepare_tool" not in tool_slice_source
    assert "requestLocalApiJson" not in tool_slice_source
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


def test_scenario_handoff_checklist_targets_are_fail_closed(monkeypatch) -> None:
    definitions = _scenario_definitions()

    monkeypatch.setattr(
        "apps.api.workflow_scenario_pack_service._sample_data_handoff_checklist",
        lambda *, ready: _sample_data_checklist(target_override={"SELECT_FIXTURE": "https://example.com"}),
    )
    with pytest.raises(WorkflowScenarioPackCatalogError, match="SCENARIO_SAMPLE_DATA_HANDOFF_TARGET_UNSUPPORTED"):
        _validate_scenario_definitions(
            definitions,
            {"moving-pictures-16s-rulegraph-v1": {"enabled": True}},
        )

    monkeypatch.setattr(
        "apps.api.workflow_scenario_pack_tool_slice._tool_slice_checklist",
        lambda *, ready: _tool_slice_checklist(target_override={"CURATE_TOOL_SLICE": "/unknown"}),
    )
    with pytest.raises(WorkflowScenarioToolSliceHandoffError, match="SCENARIO_TOOL_SLICE_HANDOFF_TARGET_UNSUPPORTED"):
        validate_tool_slice_handoff(definitions[1])

    monkeypatch.setattr(
        "apps.api.workflow_scenario_pack_database_handoff._database_handoff_checklist",
        lambda *, ready: _database_checklist(target_override={"REAL_DATABASE_ACCEPTANCE": "https://example.com"}),
    )
    with pytest.raises(WorkflowScenarioDatabaseHandoffError, match="SCENARIO_DATABASE_HANDOFF_TARGET_UNSUPPORTED"):
        validate_database_handoff(definitions[1])


def test_scenario_database_handoff_uses_catalog_pack_options_without_installing() -> None:
    packs_by_template = {item["templateId"]: item for item in list_downloadable_database_packs()}
    taxonomy = {
        item["scenarioId"]: item for item in list_workflow_scenario_packs()["data"]["items"]
    }["taxonomy-classification"]
    gtdbtk_pack = packs_by_template["gtdbtk"]
    pack_option = taxonomy["databaseHandoff"]["packOptions"][0]

    assert pack_option["packId"] == gtdbtk_pack["packId"]
    assert pack_option["checksum"] == gtdbtk_pack["checksum"]
    assert pack_option["readyDirHint"] == gtdbtk_pack["manualInstall"]["readyDirHint"]
    assert pack_option["registrationScriptPath"] == gtdbtk_pack["registrationHandoff"]["scriptPath"]
    assert "operatorSteps" not in pack_option
    assert taxonomy["databaseHandoff"]["readyScan"]["mutatesRegistry"] is False
    assert taxonomy["databaseHandoff"]["registration"]["requiresReadyScan"] is True


def _sample_data_checklist(*, target_override: dict[str, str]) -> list[dict[str, str]]:
    targets = {
        "SELECT_FIXTURE": "/workflows/tools",
        "DECLARE_INPUT_ROLES": "/workflows/tools",
        "VERIFY_CHECKSUMS": "/workflows/tools",
        "RECORD_SOURCE": "/workflows/tools",
        "RUN_ACCEPTANCE": "/workflows/results",
    } | target_override
    return [_operator_required_item(code, target) for code, target in targets.items()]


def _tool_slice_checklist(*, target_override: dict[str, str]) -> list[dict[str, str]]:
    targets = {
        "CURATE_TOOL_SLICE": "/workflows/tools",
        "LOCK_TOOL_REVISION": "/workflows/tools",
        "CONFIRM_RULE_SPEC": "/workflows/tools",
        "LOCK_ENVIRONMENT": "/workflows/tools",
        "RUN_SMOKE_FIXTURE": "/workflows/tools",
        "VALIDATE_OUTPUTS": "/workflows/tools",
    } | target_override
    return [_operator_required_item(code, target) for code, target in targets.items()]


def _database_checklist(*, target_override: dict[str, str]) -> list[dict[str, str]]:
    targets = {
        "SELECT_TEMPLATE": "/workflows/databases",
        "VERIFY_CHECKSUM": "/workflows/databases",
        "READY_SCAN": "/workflows/databases",
        "REGISTER_DATABASE": "/workflows/databases",
        "BIND_DATABASE": "/workflows",
        "REAL_DATABASE_ACCEPTANCE": "/workflows/results",
    } | target_override
    return [_operator_required_item(code, target) for code, target in targets.items()]


def _operator_required_item(code: str, target: str) -> dict[str, str]:
    return {
        "code": code,
        "label": code.lower(),
        "status": "operator_required",
        "target": target,
        "evidence": "test evidence",
    }


def _source(path: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
