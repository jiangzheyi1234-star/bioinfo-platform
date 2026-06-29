"""Product-level workflow scenario pack catalog."""

from __future__ import annotations

from typing import Any

from apps.api.workflow_catalog_service import list_bundled_pipeline_manifests
from apps.api.workflow_sample_data_service import MOVING_PICTURES_PIPELINE_ID


SCENARIO_PACK_SCHEMA_VERSION = "h2ometa.workflow-scenario-pack.v1"
SCENARIO_PACK_CATALOG_SCHEMA_VERSION = "h2ometa.workflow-scenario-pack-catalog.v1"
SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION = "h2ometa.workflow-scenario-database-handoff.v1"
SCENARIO_SAMPLE_DATA_HANDOFF_SCHEMA_VERSION = "h2ometa.workflow-scenario-sample-data-handoff.v1"
_ALLOWED_ACTION_TARGETS = {
    "/workflows/first-run",
    "/workflows/tools",
    "/workflows/databases",
}
_KNOWN_DATABASE_TEMPLATES = {
    "card_rgi",
    "centrifuge",
    "eggnog_mapper",
    "gtdbtk",
    "interproscan",
    "kaiju",
    "silva_qiime",
}
_SCENARIO_TOOL_SLICE_MIN = 3
_SCENARIO_TOOL_SLICE_MAX = 5
_SCENARIO_TOOL_CONTRACT_STATES = {"planned", "workflow_ready"}
_VERTICAL_SCENARIO_REQUIRED_BLOCKED_GATES = {
    "taxonomy-classification": {
        "SCENARIO_TOOL_SLICE_READY",
        "SCENARIO_DATABASE_HANDOFF_READY",
        "SCENARIO_SAMPLE_DATA_READY",
    },
    "amr-annotation": {
        "SCENARIO_TOOL_SLICE_READY",
        "SCENARIO_DATABASE_HANDOFF_READY",
        "SCENARIO_SAMPLE_DATA_READY",
    },
}


class WorkflowScenarioPackCatalogError(ValueError):
    pass


def list_workflow_scenario_packs() -> dict[str, Any]:
    pipelines = {
        str(item.get("pipelineId") or ""): item
        for item in list_bundled_pipeline_manifests()
    }
    definitions = _scenario_definitions()
    _validate_scenario_definitions(definitions, pipelines)
    items = [_scenario_pack(definition, pipelines) for definition in definitions]
    return {
        "data": {
            "schemaVersion": SCENARIO_PACK_CATALOG_SCHEMA_VERSION,
            "items": items,
        }
    }


def _scenario_pack(definition: dict[str, Any], pipelines: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pipeline_id = str(definition["pipelineId"])
    pipeline = pipelines.get(pipeline_id)
    pipeline_ready = bool(pipeline and pipeline.get("enabled", True))
    readiness = _readiness_checks(definition, pipeline_ready=pipeline_ready)
    status = "ready" if all(item["status"] == "passed" for item in readiness) else "blocked"
    return {
        "schemaVersion": SCENARIO_PACK_SCHEMA_VERSION,
        "packId": definition["packId"],
        "scenarioId": definition["scenarioId"],
        "name": definition["name"],
        "vertical": definition["vertical"],
        "summary": definition["summary"],
        "status": status,
        "priority": definition["priority"],
        "operatorActionRequired": status != "ready",
        "noAutomaticExecution": True,
        "pipelineId": pipeline_id,
        "firstRunPath": definition["firstRunPath"] if status == "ready" else "",
        "workflowPath": f"/workflows/detail?workflow={pipeline_id}" if pipeline_ready else "",
        "sampleData": definition["sampleData"],
        "sampleDataHandoff": _sample_data_handoff(definition),
        "requiredWorkflowReadyTools": definition["requiredWorkflowReadyTools"],
        "requiredDatabases": definition["requiredDatabases"],
        "databaseHandoff": _database_handoff(definition),
        "resultEvidence": definition["resultEvidence"],
        "readinessChecks": readiness,
        "nextActions": _next_actions(definition, readiness),
        "externalPracticeAnchors": definition["externalPracticeAnchors"],
    }


def _validate_scenario_definitions(
    definitions: list[dict[str, Any]],
    pipelines: dict[str, dict[str, Any]],
) -> None:
    pack_ids: set[str] = set()
    scenario_ids: set[str] = set()
    for definition in definitions:
        pack_id = _required_text(definition, "packId", "SCENARIO_PACK_ID_REQUIRED")
        scenario_id = _required_text(definition, "scenarioId", "SCENARIO_ID_REQUIRED")
        if pack_id in pack_ids:
            raise WorkflowScenarioPackCatalogError(f"SCENARIO_PACK_ID_DUPLICATE: {pack_id}")
        if scenario_id in scenario_ids:
            raise WorkflowScenarioPackCatalogError(f"SCENARIO_ID_DUPLICATE: {scenario_id}")
        pack_ids.add(pack_id)
        scenario_ids.add(scenario_id)
        _validate_scenario_definition(definition, pipelines)


def _validate_scenario_definition(
    definition: dict[str, Any],
    pipelines: dict[str, dict[str, Any]],
) -> None:
    for field in ("name", "vertical", "summary", "pipelineId"):
        _required_text(definition, field, f"SCENARIO_{field.upper()}_REQUIRED")
    priority = definition.get("priority")
    if not isinstance(priority, int) or priority < 1:
        raise WorkflowScenarioPackCatalogError("SCENARIO_PRIORITY_INVALID")
    if definition.get("firstRunPath") and definition["firstRunPath"] != "/workflows/first-run":
        raise WorkflowScenarioPackCatalogError("SCENARIO_FIRST_RUN_PATH_UNSUPPORTED")
    for target in _next_action_targets(definition):
        if target not in _ALLOWED_ACTION_TARGETS:
            raise WorkflowScenarioPackCatalogError(f"SCENARIO_ACTION_TARGET_UNSUPPORTED: {target}")
    for anchor in definition.get("externalPracticeAnchors") or []:
        if not str(anchor or "").startswith("https://"):
            raise WorkflowScenarioPackCatalogError(f"SCENARIO_EXTERNAL_ANCHOR_UNSAFE: {anchor}")
    if not definition.get("requiredWorkflowReadyTools"):
        raise WorkflowScenarioPackCatalogError("SCENARIO_TOOL_SLICE_REQUIRED")
    if not definition.get("resultEvidence"):
        raise WorkflowScenarioPackCatalogError("SCENARIO_RESULT_EVIDENCE_REQUIRED")
    _validate_sample_data_handoff(definition)
    _validate_database_handoff(definition)
    pipeline_id = str(definition.get("pipelineId") or "")
    pipeline_ready = bool(pipeline_id in pipelines and pipelines[pipeline_id].get("enabled", True))
    _validate_gate_contract(definition, pipeline_ready=pipeline_ready)
    _validate_tool_slice(definition)
    _validate_database_templates(definition)
    _validate_ready_scenario_pipeline(definition, pipelines)


def _validate_tool_slice(definition: dict[str, Any]) -> None:
    tools = definition.get("requiredWorkflowReadyTools")
    if not isinstance(tools, list) or not tools:
        raise WorkflowScenarioPackCatalogError("SCENARIO_TOOL_SLICE_REQUIRED")
    if not (_SCENARIO_TOOL_SLICE_MIN <= len(tools) <= _SCENARIO_TOOL_SLICE_MAX):
        raise WorkflowScenarioPackCatalogError("SCENARIO_TOOL_SLICE_SIZE_INVALID")
    tool_ids: set[str] = set()
    for item in tools:
        if not isinstance(item, dict):
            raise WorkflowScenarioPackCatalogError("SCENARIO_TOOL_SLICE_ITEM_INVALID")
        tool_id = _required_text(item, "toolId", "SCENARIO_TOOL_ID_REQUIRED")
        if tool_id in tool_ids:
            raise WorkflowScenarioPackCatalogError(f"SCENARIO_TOOL_ID_DUPLICATE: {tool_id}")
        tool_ids.add(tool_id)
        for field in ("name", "kind", "role", "contractState", "acceptanceEvidence"):
            _required_text(item, field, f"SCENARIO_TOOL_{field.upper()}_REQUIRED")
        contract_state = str(item.get("contractState") or "").strip()
        if contract_state not in _SCENARIO_TOOL_CONTRACT_STATES:
            raise WorkflowScenarioPackCatalogError(f"SCENARIO_TOOL_CONTRACT_STATE_INVALID: {contract_state}")
        _reject_generic_bioconda_tool(item)
    tool_gate_passed = _gate_passed(definition, "SCENARIO_TOOL_SLICE_READY")
    if tool_gate_passed and any(str(item.get("contractState") or "") != "workflow_ready" for item in tools):
        raise WorkflowScenarioPackCatalogError("SCENARIO_TOOL_SLICE_GATE_MISMATCH")


def _reject_generic_bioconda_tool(item: dict[str, Any]) -> None:
    forbidden_fields = ("packageSpec", "packageQuery", "biocondaQuery")
    if any(item.get(field) for field in forbidden_fields):
        raise WorkflowScenarioPackCatalogError("SCENARIO_TOOL_SLICE_GENERIC_BIOCONDA_UNSUPPORTED")
    generic_values = [
        str(item.get("toolId") or ""),
        str(item.get("source") or ""),
        str(item.get("name") or ""),
    ]
    if any(value.strip().lower() in {"bioconda", "all-bioconda", "bioconda::*"} for value in generic_values):
        raise WorkflowScenarioPackCatalogError("SCENARIO_TOOL_SLICE_GENERIC_BIOCONDA_UNSUPPORTED")


def _validate_gate_contract(definition: dict[str, Any], *, pipeline_ready: bool) -> None:
    gates = definition.get("gates")
    if not isinstance(gates, list) or not gates:
        raise WorkflowScenarioPackCatalogError("SCENARIO_GATES_REQUIRED")
    gate_codes = {str(item.get("code") or "") for item in gates if isinstance(item, dict)}
    if not gate_codes:
        raise WorkflowScenarioPackCatalogError("SCENARIO_GATES_REQUIRED")
    next_targets = definition.get("nextActionTargets") if isinstance(definition.get("nextActionTargets"), dict) else {}
    gates_passed = all(bool(item.get("passed")) for item in gates if isinstance(item, dict))
    if not gates_passed and not pipeline_ready and not str(next_targets.get("SCENARIO_PIPELINE_WORKFLOW_READY") or "").strip():
        raise WorkflowScenarioPackCatalogError("SCENARIO_BLOCKED_GATE_ACTION_REQUIRED: SCENARIO_PIPELINE_WORKFLOW_READY")
    for item in gates:
        code = str(item.get("code") or "") if isinstance(item, dict) else ""
        if not code:
            raise WorkflowScenarioPackCatalogError("SCENARIO_GATE_CODE_REQUIRED")
        if not bool(item.get("passed")) and not str(next_targets.get(code) or "").strip():
            raise WorkflowScenarioPackCatalogError(f"SCENARIO_BLOCKED_GATE_ACTION_REQUIRED: {code}")
    required_blocked = _VERTICAL_SCENARIO_REQUIRED_BLOCKED_GATES.get(str(definition.get("scenarioId") or ""))
    if required_blocked and not required_blocked <= gate_codes:
        raise WorkflowScenarioPackCatalogError("SCENARIO_VERTICAL_GATE_REQUIRED")
    if required_blocked:
        blocked_codes = {str(item.get("code") or "") for item in gates if isinstance(item, dict) and not bool(item.get("passed"))}
        if not required_blocked <= blocked_codes:
            raise WorkflowScenarioPackCatalogError("SCENARIO_VERTICAL_GATE_MUST_BLOCK_UNTIL_ACCEPTED")


def _gate_passed(definition: dict[str, Any], code: str) -> bool:
    for item in definition.get("gates") or []:
        if isinstance(item, dict) and item.get("code") == code:
            return bool(item.get("passed"))
    return False


def _validate_database_templates(definition: dict[str, Any]) -> None:
    for item in definition.get("requiredDatabases") or []:
        templates = item.get("templates") if isinstance(item, dict) else None
        for template_id in templates or []:
            if str(template_id or "") not in _KNOWN_DATABASE_TEMPLATES:
                raise WorkflowScenarioPackCatalogError(f"SCENARIO_DATABASE_TEMPLATE_UNKNOWN: {template_id}")


def _validate_sample_data_handoff(definition: dict[str, Any]) -> None:
    handoff = _sample_data_handoff(definition)
    if handoff["schemaVersion"] != SCENARIO_SAMPLE_DATA_HANDOFF_SCHEMA_VERSION:
        raise WorkflowScenarioPackCatalogError("SCENARIO_SAMPLE_DATA_HANDOFF_SCHEMA_INVALID")
    gate_codes = {str(item.get("code") or "") for item in definition.get("gates") or [] if isinstance(item, dict)}
    if "SCENARIO_SAMPLE_DATA_READY" not in gate_codes:
        raise WorkflowScenarioPackCatalogError("SCENARIO_SAMPLE_DATA_HANDOFF_GATE_REQUIRED")
    if not handoff["noAutomaticExecution"]:
        raise WorkflowScenarioPackCatalogError("SCENARIO_SAMPLE_DATA_HANDOFF_MANUAL_REQUIRED")
    if handoff["status"] == "operator_required" and not handoff["operatorActionRequired"]:
        raise WorkflowScenarioPackCatalogError("SCENARIO_SAMPLE_DATA_HANDOFF_MANUAL_REQUIRED")
    if handoff["status"] == "ready" and handoff["operatorActionRequired"]:
        raise WorkflowScenarioPackCatalogError("SCENARIO_SAMPLE_DATA_HANDOFF_MANUAL_REQUIRED")
    checklist_codes = {item["code"] for item in handoff["checklist"]}
    required_codes = {
        "SELECT_FIXTURE",
        "DECLARE_INPUT_ROLES",
        "VERIFY_CHECKSUMS",
        "RECORD_SOURCE",
        "RUN_ACCEPTANCE",
    }
    if not required_codes <= checklist_codes:
        raise WorkflowScenarioPackCatalogError("SCENARIO_SAMPLE_DATA_HANDOFF_CHECKLIST_INCOMPLETE")
    if any(item["status"] not in {"operator_required", "passed"} for item in handoff["checklist"]):
        raise WorkflowScenarioPackCatalogError("SCENARIO_SAMPLE_DATA_HANDOFF_STATUS_INVALID")
    if set(handoff["excludedActions"]) != {"automatic-download", "automatic-fixture-generation", "unverified-example-data"}:
        raise WorkflowScenarioPackCatalogError("SCENARIO_SAMPLE_DATA_HANDOFF_EXCLUSIONS_INVALID")


def _validate_database_handoff(definition: dict[str, Any]) -> None:
    handoff = _database_handoff(definition)
    if handoff["schemaVersion"] != SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION:
        raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_SCHEMA_INVALID")
    if definition.get("requiredDatabases"):
        gate_codes = {str(item.get("code") or "") for item in definition.get("gates") or [] if isinstance(item, dict)}
        if "SCENARIO_DATABASE_HANDOFF_READY" not in gate_codes:
            raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_GATE_REQUIRED")
        if handoff["mode"] != "manual_external":
            raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_MODE_INVALID")
        if handoff["status"] == "operator_required" and not handoff["operatorActionRequired"]:
            raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_MANUAL_REQUIRED")
        if handoff["status"] == "ready" and handoff["operatorActionRequired"]:
            raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_MANUAL_REQUIRED")
        if not handoff["noAutomaticExecution"]:
            raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_MANUAL_REQUIRED")
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
            raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_CHECKLIST_INCOMPLETE")
        if any(item["status"] not in {"operator_required", "passed"} for item in handoff["checklist"]):
            raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_STATUS_INVALID")
        if set(handoff["excludedActions"]) != {"automatic-download", "automatic-extract", "automatic-install"}:
            raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_EXCLUSIONS_INVALID")
    elif handoff["status"] != "not_required" or handoff["checklist"]:
        raise WorkflowScenarioPackCatalogError("SCENARIO_DATABASE_HANDOFF_NOT_REQUIRED_INVALID")


def _validate_ready_scenario_pipeline(
    definition: dict[str, Any],
    pipelines: dict[str, dict[str, Any]],
) -> None:
    passed_gates = all(bool(item.get("passed")) for item in definition.get("gates") or [])
    pipeline_id = str(definition.get("pipelineId") or "")
    if passed_gates and pipeline_id not in pipelines:
        raise WorkflowScenarioPackCatalogError(f"SCENARIO_READY_PIPELINE_MISSING: {pipeline_id}")
    if passed_gates and not bool(pipelines[pipeline_id].get("enabled", True)):
        raise WorkflowScenarioPackCatalogError(f"SCENARIO_READY_PIPELINE_DISABLED: {pipeline_id}")


def _next_action_targets(definition: dict[str, Any]) -> list[str]:
    raw = definition.get("nextActionTargets") if isinstance(definition.get("nextActionTargets"), dict) else {}
    return [str(target or "") for target in raw.values()]


def _required_text(definition: dict[str, Any], field: str, code: str) -> str:
    value = str(definition.get(field) or "").strip()
    if not value:
        raise WorkflowScenarioPackCatalogError(code)
    return value


def _readiness_checks(definition: dict[str, Any], *, pipeline_ready: bool) -> list[dict[str, str]]:
    checks = [
        _check(
            "SCENARIO_PIPELINE_WORKFLOW_READY",
            pipeline_ready,
            definition["pipelineId"],
            "Scenario pipeline must be bundled and enabled.",
        ),
    ]
    for item in definition["gates"]:
        checks.append(
            _check(
                str(item["code"]),
                bool(item["passed"]),
                str(item["passedDetail"] if item["passed"] else item["blockedDetail"]),
                str(item["requirement"]),
            )
        )
    return checks


def _check(code: str, passed: bool, detail: str, requirement: str) -> dict[str, str]:
    return {
        "code": code,
        "status": "passed" if passed else "blocked",
        "detail": detail,
        "requirement": requirement,
    }


def _next_actions(definition: dict[str, Any], readiness: list[dict[str, str]]) -> list[dict[str, str]]:
    actions = []
    for item in readiness:
        if item["status"] == "passed":
            continue
        actions.append(
            {
                "code": item["code"],
                "label": _action_label(item["code"]),
                "target": str(definition["nextActionTargets"][item["code"]]),
            }
        )
    return actions


def _action_label(code: str) -> str:
    labels = {
        "SCENARIO_PIPELINE_WORKFLOW_READY": "建立 WorkflowReady 场景 pipeline",
        "SCENARIO_SAMPLE_DATA_READY": "准备可审计样例数据",
        "SCENARIO_DATABASE_HANDOFF_READY": "完成数据库手动安装陪跑",
        "SCENARIO_TOOL_SLICE_READY": "收敛 3-5 个 WorkflowReady 工具",
    }
    return labels.get(code, "补齐场景准入条件")


def _sample_data_handoff(definition: dict[str, Any]) -> dict[str, Any]:
    ready = _gate_passed(definition, "SCENARIO_SAMPLE_DATA_READY")
    sample_data = definition.get("sampleData") or {}
    mode = str(sample_data.get("mode") or "").strip()
    if mode == "bundled-loader":
        handoff_mode = "bundled_loader"
    else:
        handoff_mode = "operator_provided"
    return {
        "schemaVersion": SCENARIO_SAMPLE_DATA_HANDOFF_SCHEMA_VERSION,
        "mode": handoff_mode,
        "status": "ready" if ready else "operator_required",
        "operatorActionRequired": not ready,
        "noAutomaticExecution": True,
        "inputOptions": _sample_data_input_options(definition),
        "checklist": _sample_data_handoff_checklist(ready=ready),
        "evidencePolicy": {
            "requiresChecksum": True,
            "requiresSource": True,
            "requiresInputRoles": True,
            "requiresSmallFixture": True,
            "requiresResultValidationCard": True,
        },
        "excludedActions": ["automatic-download", "automatic-fixture-generation", "unverified-example-data"],
    }


def _sample_data_input_options(definition: dict[str, Any]) -> list[dict[str, Any]]:
    scenario_id = str(definition.get("scenarioId") or "")
    if scenario_id == "moving-pictures-16s":
        return [
            {"role": "metadata", "formats": ["tsv"], "required": True},
            {"role": "barcodes", "formats": ["fastq.gz"], "required": True},
            {"role": "sequences", "formats": ["fastq.gz"], "required": True},
        ]
    if scenario_id == "taxonomy-classification":
        return [
            {"role": "reads", "formats": ["fastq.gz"], "required": False},
            {"role": "contigs", "formats": ["fna", "fasta"], "required": False},
        ]
    if scenario_id == "amr-annotation":
        return [
            {"role": "contigs", "formats": ["fna", "fasta"], "required": False},
            {"role": "proteins", "formats": ["faa", "fasta"], "required": False},
        ]
    return [{"role": "input", "formats": [str(item) for item in (definition.get("sampleData") or {}).get("items") or []], "required": True}]


def _sample_data_handoff_checklist(*, ready: bool) -> list[dict[str, str]]:
    status = "passed" if ready else "operator_required"
    return [
        {
            "code": "SELECT_FIXTURE",
            "label": "选择小型真实 fixture",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "fixture source and scope recorded",
        },
        {
            "code": "DECLARE_INPUT_ROLES",
            "label": "声明输入角色和格式",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "input roles match scenario inputOptions",
        },
        {
            "code": "VERIFY_CHECKSUMS",
            "label": "记录文件 checksum",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "sha256 manifest for every fixture file",
        },
        {
            "code": "RECORD_SOURCE",
            "label": "记录来源和许可",
            "status": status,
            "target": "/workflows/tools",
            "evidence": "source URL, accession, or local custody note",
        },
        {
            "code": "RUN_ACCEPTANCE",
            "label": "用 fixture 跑出验证卡",
            "status": status,
            "target": "/workflows/results",
            "evidence": "completed run with validationCard and resultPackage",
        },
    ]


def _database_handoff(definition: dict[str, Any]) -> dict[str, Any]:
    required_databases = list(definition.get("requiredDatabases") or [])
    if not required_databases:
        return {
            "schemaVersion": SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION,
            "mode": "none",
            "status": "not_required",
            "operatorActionRequired": False,
            "noAutomaticExecution": True,
            "templateOptions": [],
            "checklist": [],
            "readyScan": {},
            "registration": {},
            "evidencePolicy": {},
            "excludedActions": ["automatic-download", "automatic-extract", "automatic-install"],
        }
    ready = _gate_passed(definition, "SCENARIO_DATABASE_HANDOFF_READY")
    return {
        "schemaVersion": SCENARIO_DATABASE_HANDOFF_SCHEMA_VERSION,
        "mode": "manual_external",
        "status": "ready" if ready else "operator_required",
        "operatorActionRequired": not ready,
        "noAutomaticExecution": True,
        "templateOptions": _database_template_options(required_databases),
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
        "excludedActions": ["automatic-download", "automatic-extract", "automatic-install"],
    }


def _database_template_options(required_databases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for item in required_databases:
        capability = str(item.get("capability") or "").strip()
        templates = [str(template_id or "").strip() for template_id in item.get("templates") or [] if str(template_id or "").strip()]
        options.append({"capability": capability, "templates": templates})
    return options


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


def _scenario_definitions() -> list[dict[str, Any]]:
    return [
        {
            "packId": "h2ometa-scenario-moving-pictures-16s",
            "scenarioId": "moving-pictures-16s",
            "name": "16S Moving Pictures 首跑",
            "vertical": "16S",
            "summary": "从 QIIME 2 Moving Pictures 三文件样例到报告、结果包和验证卡。",
            "priority": 1,
            "pipelineId": MOVING_PICTURES_PIPELINE_ID,
            "firstRunPath": "/workflows/first-run",
            "sampleData": {
                "mode": "bundled-loader",
                "source": "QIIME 2 Moving Pictures tutorial",
                "items": ["sample-metadata.tsv", "barcodes.fastq.gz", "sequences.fastq.gz"],
            },
            "requiredWorkflowReadyTools": [
                {
                    "toolId": "moving-pictures::metadata-validation",
                    "name": "Sample metadata validation",
                    "kind": "metadata_validation",
                    "role": "input_qc",
                    "contractState": "workflow_ready",
                    "acceptanceEvidence": "bundled-moving-pictures-workflow-revision",
                },
                {
                    "toolId": "moving-pictures::demultiplex-and-qc",
                    "name": "Demultiplex and quality summary",
                    "kind": "demultiplexing",
                    "role": "sequence_qc",
                    "contractState": "workflow_ready",
                    "acceptanceEvidence": "bundled-moving-pictures-workflow-revision",
                },
                {
                    "toolId": "moving-pictures::feature-table",
                    "name": "Feature table summary",
                    "kind": "amplicon_summary",
                    "role": "feature_summary",
                    "contractState": "workflow_ready",
                    "acceptanceEvidence": "bundled-moving-pictures-workflow-revision",
                },
                {
                    "toolId": "moving-pictures::render-report",
                    "name": "Moving Pictures HTML report",
                    "kind": "report",
                    "role": "reporting",
                    "contractState": "workflow_ready",
                    "acceptanceEvidence": "bundled-moving-pictures-workflow-revision",
                },
            ],
            "requiredDatabases": [],
            "resultEvidence": ["resultPackage", "validationCard", "workflowRevision", "inputLineage", "outputChecksums"],
            "gates": [
                {
                    "code": "SCENARIO_SAMPLE_DATA_READY",
                    "passed": True,
                    "passedDetail": "bundled Moving Pictures loader is available",
                    "blockedDetail": "",
                    "requirement": "Scenario must provide audited example inputs.",
                },
                {
                    "code": "SCENARIO_TOOL_SLICE_READY",
                    "passed": True,
                    "passedDetail": "scenario pipeline uses a curated four-step slice",
                    "blockedDetail": "",
                    "requirement": "Scenario must be a small WorkflowReady slice, not an open tool ocean.",
                },
            ],
            "nextActionTargets": {},
            "externalPracticeAnchors": [
                "https://docs.qiime2.org/2024.10/tutorials/moving-pictures/",
                "https://www.researchobject.org/workflow-run-crate/",
            ],
        },
        {
            "packId": "h2ometa-scenario-taxonomy-classification",
            "scenarioId": "taxonomy-classification",
            "name": "Taxonomy classification 场景",
            "vertical": "taxonomy",
            "summary": "FASTQ/FASTA 输入到分类报告，要求小工具切片、参考库登记和结果证据。",
            "priority": 2,
            "pipelineId": "taxonomy-classification-scenario-v1",
            "firstRunPath": "",
            "sampleData": {
                "mode": "required",
                "source": "operator-provided audited FASTQ/FASTA fixture",
                "items": ["reads.fastq.gz or contigs.fna"],
            },
            "requiredWorkflowReadyTools": [
                {
                    "toolId": "taxonomy::input-normalizer",
                    "name": "FASTQ/FASTA input normalizer",
                    "kind": "sequence_reads",
                    "role": "input_qc",
                    "contractState": "planned",
                    "acceptanceEvidence": "pending-workflow-ready-acceptance",
                },
                {
                    "toolId": "taxonomy::classifier",
                    "name": "Selected taxonomy classifier",
                    "kind": "taxonomy_classification",
                    "role": "classification",
                    "contractState": "planned",
                    "acceptanceEvidence": "pending-workflow-ready-acceptance",
                },
                {
                    "toolId": "taxonomy::classification-report",
                    "name": "Taxonomy report renderer",
                    "kind": "taxonomy_report",
                    "role": "reporting",
                    "contractState": "planned",
                    "acceptanceEvidence": "pending-workflow-ready-acceptance",
                },
            ],
            "requiredDatabases": [
                {"capability": "taxonomy_database", "templates": ["centrifuge", "kaiju", "gtdbtk", "silva_qiime"]},
            ],
            "resultEvidence": ["workflowRevision", "databaseCheck", "resultPackage", "validationCard"],
            "gates": [
                {
                    "code": "SCENARIO_TOOL_SLICE_READY",
                    "passed": False,
                    "passedDetail": "",
                    "blockedDetail": "requires one selected classifier plus reporting tools to be WorkflowReady",
                    "requirement": "Scenario must name 3-5 WorkflowReady tools.",
                },
                {
                    "code": "SCENARIO_DATABASE_HANDOFF_READY",
                    "passed": False,
                    "passedDetail": "",
                    "blockedDetail": "requires manual database pack checklist, checksum, ready scan, and registration",
                    "requirement": "Database installation must be audited and manually confirmed.",
                },
                {
                    "code": "SCENARIO_SAMPLE_DATA_READY",
                    "passed": False,
                    "passedDetail": "",
                    "blockedDetail": "requires a small audited taxonomy fixture",
                    "requirement": "Scenario must provide audited example inputs.",
                },
            ],
            "nextActionTargets": {
                "SCENARIO_PIPELINE_WORKFLOW_READY": "/workflows/tools",
                "SCENARIO_TOOL_SLICE_READY": "/workflows/tools",
                "SCENARIO_DATABASE_HANDOFF_READY": "/workflows/databases",
                "SCENARIO_SAMPLE_DATA_READY": "/workflows/tools",
            },
            "externalPracticeAnchors": [
                "https://nf-co.re/taxprofiler",
                "https://usegalaxy.org/workflows/list_published",
            ],
        },
        {
            "packId": "h2ometa-scenario-amr-annotation",
            "scenarioId": "amr-annotation",
            "name": "AMR / annotation 场景",
            "vertical": "AMR",
            "summary": "组装/蛋白输入到 AMR 或功能注释报告，要求 CARD/annotation 数据库手动验收。",
            "priority": 3,
            "pipelineId": "amr-annotation-scenario-v1",
            "firstRunPath": "",
            "sampleData": {
                "mode": "required",
                "source": "operator-provided audited contig/protein fixture",
                "items": ["contigs.fna or proteins.faa"],
            },
            "requiredWorkflowReadyTools": [
                {
                    "toolId": "amr::input-normalizer",
                    "name": "Contig/protein input normalizer",
                    "kind": "assembly_contigs",
                    "role": "input_qc",
                    "contractState": "planned",
                    "acceptanceEvidence": "pending-workflow-ready-acceptance",
                },
                {
                    "toolId": "amr::card-rgi-report",
                    "name": "CARD RGI report",
                    "kind": "amr_report",
                    "role": "amr_detection",
                    "contractState": "planned",
                    "acceptanceEvidence": "pending-workflow-ready-acceptance",
                },
                {
                    "toolId": "amr::annotation-table",
                    "name": "Annotation table builder",
                    "kind": "annotation_table",
                    "role": "annotation",
                    "contractState": "planned",
                    "acceptanceEvidence": "pending-workflow-ready-acceptance",
                },
            ],
            "requiredDatabases": [
                {"capability": "amr_database", "templates": ["card_rgi"]},
                {"capability": "annotation_database", "templates": ["eggnog_mapper", "interproscan"]},
            ],
            "resultEvidence": ["workflowRevision", "databaseCheck", "resultPackage", "validationCard"],
            "gates": [
                {
                    "code": "SCENARIO_TOOL_SLICE_READY",
                    "passed": False,
                    "passedDetail": "",
                    "blockedDetail": "requires RGI and one annotation/reporting path to be WorkflowReady",
                    "requirement": "Scenario must name 3-5 WorkflowReady tools.",
                },
                {
                    "code": "SCENARIO_DATABASE_HANDOFF_READY",
                    "passed": False,
                    "passedDetail": "",
                    "blockedDetail": "requires manual CARD/annotation database checklist and ready scan",
                    "requirement": "Database installation must be audited and manually confirmed.",
                },
                {
                    "code": "SCENARIO_SAMPLE_DATA_READY",
                    "passed": False,
                    "passedDetail": "",
                    "blockedDetail": "requires a small audited contig/protein fixture",
                    "requirement": "Scenario must provide audited example inputs.",
                },
            ],
            "nextActionTargets": {
                "SCENARIO_PIPELINE_WORKFLOW_READY": "/workflows/tools",
                "SCENARIO_TOOL_SLICE_READY": "/workflows/tools",
                "SCENARIO_DATABASE_HANDOFF_READY": "/workflows/databases",
                "SCENARIO_SAMPLE_DATA_READY": "/workflows/tools",
            },
            "externalPracticeAnchors": [
                "https://card.mcmaster.ca/analyze/rgi",
                "https://github.com/eggnogdb/eggnog-mapper/wiki",
            ],
        },
    ]
