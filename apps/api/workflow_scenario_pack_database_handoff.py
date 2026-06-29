"""Scenario-level database installation handoff contract."""

from __future__ import annotations

from typing import Any

from apps.api.workflow_scenario_pack_targets import SCENARIO_PRODUCT_TARGETS
from apps.remote_runner.database_pack_catalog import list_downloadable_database_packs
from apps.remote_runner.database_template_definitions import DATABASE_TEMPLATES


SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION = "h2ometa.workflow-scenario-database-handoff.v1"
SCENARIO_DATABASE_HANDOFF_EXCLUDED_ACTIONS = [
    "automatic-download",
    "automatic-extract",
    "automatic-install",
]


class WorkflowScenarioDatabaseHandoffError(ValueError):
    pass


def database_handoff(definition: dict[str, Any]) -> dict[str, Any]:
    required_databases = list(definition.get("requiredDatabases") or [])
    if not required_databases:
        return {
            "schemaVersion": SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION,
            "mode": "none",
            "status": "not_required",
            "operatorActionRequired": False,
            "noAutomaticExecution": True,
            "templateOptions": [],
            "packOptions": [],
            "missingPackTemplates": [],
            "checklist": [],
            "readyScan": {},
            "registration": {},
            "evidencePolicy": {},
            "excludedActions": SCENARIO_DATABASE_HANDOFF_EXCLUDED_ACTIONS,
        }
    ready = _gate_passed(definition, "SCENARIO_DATABASE_HANDOFF_READY")
    return {
        "schemaVersion": SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION,
        "mode": "manual_external",
        "status": "ready" if ready else "operator_required",
        "operatorActionRequired": not ready,
        "noAutomaticExecution": True,
        "templateOptions": _database_template_options(required_databases),
        "packOptions": _database_pack_options(required_databases),
        "missingPackTemplates": _missing_pack_templates(required_databases),
        "checklist": _database_handoff_checklist(ready=ready),
        "readyScan": {
            "label": "Ready scan",
            "method": "POST",
            "path": "/api/v1/database-pack-ready-scans",
            "mutatesRegistry": False,
            "requiresOperatorReadyPath": True,
        },
        "registration": {
            "label": "手动登记",
            "method": "POST",
            "path": "/api/v1/databases",
            "requiresReadyScan": True,
            "prefillSource": "database-pack-ready-scan.registrationPrefill",
        },
        "evidencePolicy": {
            "acceptedEvidenceType": "real-database-acceptance",
            "requiresRegisteredStatus": "available",
            "requiresRunResourceBinding": True,
            "rejectsCatalogLayerAsEvidence": True,
            "validationFixtureAccepted": False,
        },
        "excludedActions": SCENARIO_DATABASE_HANDOFF_EXCLUDED_ACTIONS,
    }


def validate_database_handoff(definition: dict[str, Any]) -> None:
    handoff = database_handoff(definition)
    if handoff["schemaVersion"] != SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION:
        raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_SCHEMA_INVALID")
    required_databases = list(definition.get("requiredDatabases") or [])
    if required_databases:
        _validate_required_database_templates(required_databases)
        gate_codes = {str(item.get("code") or "") for item in definition.get("gates") or [] if isinstance(item, dict)}
        if "SCENARIO_DATABASE_HANDOFF_READY" not in gate_codes:
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_GATE_REQUIRED")
        if handoff["mode"] != "manual_external":
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_MODE_INVALID")
        if handoff["status"] == "operator_required" and not handoff["operatorActionRequired"]:
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_MANUAL_REQUIRED")
        if handoff["status"] == "ready" and handoff["operatorActionRequired"]:
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_MANUAL_REQUIRED")
        if not handoff["noAutomaticExecution"]:
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_MANUAL_REQUIRED")
        checklist_codes = {item["code"] for item in handoff["checklist"]}
        required_codes = {
            "SELECT_TEMPLATE",
            "VERIFY_CHECKSUM",
            "READY_SCAN",
            "REGISTER_DATABASE",
            "BIND_DATABASE",
            "REAL_DATABASE_ACCEPTANCE",
        }
        if not required_codes <= checklist_codes:
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_CHECKLIST_INCOMPLETE")
        if any(item["status"] not in {"operator_required", "passed"} for item in handoff["checklist"]):
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_STATUS_INVALID")
        _validate_checklist_targets(handoff["checklist"])
        if handoff["excludedActions"] != SCENARIO_DATABASE_HANDOFF_EXCLUDED_ACTIONS:
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_EXCLUSIONS_INVALID")
        _validate_pack_options(required_databases, handoff)
    elif handoff["status"] != "not_required" or handoff["checklist"]:
        raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_NOT_REQUIRED_INVALID")


def _validate_required_database_templates(required_databases: list[dict[str, Any]]) -> None:
    known_templates = {str(template_id) for template_id in DATABASE_TEMPLATES}
    for item in required_databases:
        capability = str(item.get("capability") or "").strip()
        if not capability:
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_CAPABILITY_REQUIRED")
        templates = [str(template_id or "").strip() for template_id in item.get("templates") or [] if str(template_id or "").strip()]
        if not templates:
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_TEMPLATE_REQUIRED")
        for template_id in templates:
            if template_id not in known_templates:
                raise WorkflowScenarioDatabaseHandoffError(f"SCENARIO_DATABASE_TEMPLATE_UNKNOWN: {template_id}")


def _validate_pack_options(required_databases: list[dict[str, Any]], handoff: dict[str, Any]) -> None:
    wanted_templates = _wanted_template_ids(required_databases)
    pack_templates = {str(item.get("templateId") or "") for item in handoff["packOptions"]}
    missing_templates = set(handoff["missingPackTemplates"])
    if not pack_templates <= wanted_templates:
        raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_PACK_TEMPLATE_UNREQUESTED")
    if pack_templates & missing_templates:
        raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_PACK_TEMPLATE_CONFLICT")
    if wanted_templates != pack_templates | missing_templates:
        raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_PACK_COVERAGE_INVALID")
    for item in handoff["packOptions"]:
        required = {
            "packId",
            "templateId",
            "name",
            "version",
            "capabilities",
            "checksum",
            "sourceUrl",
            "readyDirHint",
            "registrationScriptPath",
            "installedLayer",
        }
        if not required <= set(item):
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_PACK_OPTION_INCOMPLETE")


def _database_template_options(required_databases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for item in required_databases:
        capability = str(item.get("capability") or "").strip()
        templates = [str(template_id or "").strip() for template_id in item.get("templates") or [] if str(template_id or "").strip()]
        options.append({"capability": capability, "templates": templates})
    return options


def _validate_checklist_targets(checklist: list[dict[str, str]]) -> None:
    for item in checklist:
        target = str(item.get("target") or "").strip()
        if not target:
            raise WorkflowScenarioDatabaseHandoffError("SCENARIO_DATABASE_HANDOFF_TARGET_REQUIRED")
        if target not in SCENARIO_PRODUCT_TARGETS:
            raise WorkflowScenarioDatabaseHandoffError(f"SCENARIO_DATABASE_HANDOFF_TARGET_UNSUPPORTED: {target}")


def _database_pack_options(required_databases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted_templates = _wanted_template_ids(required_databases)
    packs = [
        _pack_option(pack)
        for pack in list_downloadable_database_packs()
        if str(pack.get("templateId") or "") in wanted_templates
    ]
    return sorted(packs, key=lambda item: (item["templateId"], item["packId"]))


def _pack_option(pack: dict[str, Any]) -> dict[str, Any]:
    manual_install = pack.get("manualInstall") if isinstance(pack.get("manualInstall"), dict) else {}
    registration = pack.get("registrationHandoff") if isinstance(pack.get("registrationHandoff"), dict) else {}
    return {
        "packId": str(pack.get("packId") or ""),
        "templateId": str(pack.get("templateId") or ""),
        "name": str(pack.get("name") or ""),
        "version": str(pack.get("version") or ""),
        "capabilities": [str(item) for item in pack.get("capabilities") or [] if str(item).strip()],
        "checksum": str(pack.get("checksum") or ""),
        "sourceUrl": str(pack.get("sourceUrl") or ""),
        "readyDirHint": str(manual_install.get("readyDirHint") or ""),
        "registrationScriptPath": str(registration.get("scriptPath") or ""),
        "installedLayer": str(pack.get("installedLayer") or ""),
    }


def _missing_pack_templates(required_databases: list[dict[str, Any]]) -> list[str]:
    wanted_templates = _wanted_template_ids(required_databases)
    covered_templates = {str(pack.get("templateId") or "") for pack in list_downloadable_database_packs()}
    return sorted(wanted_templates - covered_templates)


def _wanted_template_ids(required_databases: list[dict[str, Any]]) -> set[str]:
    return {
        str(template_id or "").strip()
        for item in required_databases
        for template_id in item.get("templates") or []
        if str(template_id or "").strip()
    }


def _database_handoff_checklist(*, ready: bool) -> list[dict[str, str]]:
    status = "passed" if ready else "operator_required"
    return [
        {
            "code": "SELECT_TEMPLATE",
            "label": "选择场景数据库模板",
            "status": status,
            "target": "/workflows/databases",
            "evidence": "requiredDatabases template option selected",
        },
        {
            "code": "VERIFY_CHECKSUM",
            "label": "外部下载后核对 checksum 和大小",
            "status": status,
            "target": "/workflows/databases",
            "evidence": "manual checksum verification recorded by operator",
        },
        {
            "code": "READY_SCAN",
            "label": "运行 ready scan",
            "status": status,
            "target": "/workflows/databases",
            "evidence": "database-pack-ready-scan ready response",
        },
        {
            "code": "REGISTER_DATABASE",
            "label": "使用预填信息手动登记",
            "status": status,
            "target": "/workflows/databases",
            "evidence": "available registered database record",
        },
        {
            "code": "BIND_DATABASE",
            "label": "在场景 runSpec 绑定数据库",
            "status": status,
            "target": "/workflows",
            "evidence": "resourceBindings include databaseId and templateId",
        },
        {
            "code": "REAL_DATABASE_ACCEPTANCE",
            "label": "生成 real-database-acceptance 证据",
            "status": status,
            "target": "/workflows/results",
            "evidence": "completed run with non-empty artifacts",
        },
    ]


def _gate_passed(definition: dict[str, Any], code: str) -> bool:
    for item in definition.get("gates") or []:
        if isinstance(item, dict) and item.get("code") == code:
            return bool(item.get("passed"))
    return False
