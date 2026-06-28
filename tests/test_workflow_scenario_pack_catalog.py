from __future__ import annotations

import pytest

from apps.api.workflow_scenario_pack_service import (
    SCENARIO_PACK_CATALOG_SCHEMA_VERSION,
    SCENARIO_PACK_SCHEMA_VERSION,
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
    "requiredWorkflowReadyTools",
    "requiredDatabases",
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
    assert {check["status"] for check in first_run["readinessChecks"]} == {"passed"}

    taxonomy = items["taxonomy-classification"]
    assert taxonomy["status"] == "blocked"
    assert taxonomy["operatorActionRequired"] is True
    assert taxonomy["firstRunPath"] == ""
    assert "taxonomy_database" in {item["capability"] for item in taxonomy["requiredDatabases"]}
    assert "SCENARIO_DATABASE_HANDOFF_READY" in {item["code"] for item in taxonomy["nextActions"]}

    amr = items["amr-annotation"]
    assert amr["status"] == "blocked"
    assert amr["operatorActionRequired"] is True
    assert amr["firstRunPath"] == ""
    assert {"amr_database", "annotation_database"} <= {item["capability"] for item in amr["requiredDatabases"]}
    assert "SCENARIO_TOOL_SLICE_READY" in {item["code"] for item in amr["nextActions"]}


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
    assert "noAutomaticExecution" in service_source


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


def _source(path: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
