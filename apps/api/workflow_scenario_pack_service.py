"""Product-level workflow scenario pack catalog."""

from __future__ import annotations

from typing import Any

from apps.api.workflow_catalog_service import list_bundled_pipeline_manifests
from apps.api.workflow_sample_data_service import MOVING_PICTURES_PIPELINE_ID


SCENARIO_PACK_SCHEMA_VERSION = "h2ometa.workflow-scenario-pack.v1"
SCENARIO_PACK_CATALOG_SCHEMA_VERSION = "h2ometa.workflow-scenario-pack-catalog.v1"
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
        "requiredWorkflowReadyTools": definition["requiredWorkflowReadyTools"],
        "requiredDatabases": definition["requiredDatabases"],
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
    _validate_database_templates(definition)
    _validate_ready_scenario_pipeline(definition, pipelines)


def _validate_database_templates(definition: dict[str, Any]) -> None:
    for item in definition.get("requiredDatabases") or []:
        templates = item.get("templates") if isinstance(item, dict) else None
        for template_id in templates or []:
            if str(template_id or "") not in _KNOWN_DATABASE_TEMPLATES:
                raise WorkflowScenarioPackCatalogError(f"SCENARIO_DATABASE_TEMPLATE_UNKNOWN: {template_id}")


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
                "target": str(definition["nextActionTargets"].get(item["code"]) or "/workflows/tools"),
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
                {"kind": "metadata_validation", "count": 1},
                {"kind": "demultiplexing", "count": 1},
                {"kind": "amplicon_summary", "count": 1},
                {"kind": "report", "count": 1},
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
                {"kind": "sequence_reads", "count": 1},
                {"kind": "taxonomy_classification", "count": 1},
                {"kind": "taxonomy_report", "count": 1},
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
                {"kind": "assembly_contigs", "count": 1},
                {"kind": "amr_report", "count": 1},
                {"kind": "annotation_table", "count": 1},
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
