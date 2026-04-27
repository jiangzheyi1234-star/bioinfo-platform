"""Mock workflow template contracts for the modular workflow UI."""

from __future__ import annotations

import time
import uuid
from copy import deepcopy
from typing import Any


WORKFLOW_TEMPLATES: list[dict[str, Any]] = [
    {
        "templateId": "metagenome-qc-v1",
        "name": "Metagenome QC",
        "version": "0.1.0",
        "category": "Quality Control",
        "description": "Quality control, optional host removal, and an HTML summary for paired or single-end reads.",
        "engine": "snakemake",
        "entrypoint": "workflow/Snakefile",
        "status": "draft",
        "tags": ["fastq", "quality-control", "host-removal"],
        "inputs": [
            {
                "key": "reads",
                "label": "Sequencing reads",
                "type": "file",
                "accept": [".fastq", ".fq", ".fastq.gz", ".fq.gz"],
                "required": True,
                "multiple": True,
            }
        ],
        "outputs": [
            {"key": "qc_report", "label": "QC report", "type": "html"},
            {"key": "summary_table", "label": "Summary table", "type": "table"},
            {"key": "clean_reads", "label": "Clean reads", "type": "file"},
        ],
        "modules": [
            {
                "moduleId": "raw_fastqc",
                "name": "Raw read quality check",
                "description": "Inspect raw FASTQ quality before trimming.",
                "kind": "analysis",
                "required": True,
                "enabled": True,
                "tool": "fastqc",
                "inputs": ["reads"],
                "outputs": ["raw_qc_report"],
                "params": [],
            },
            {
                "moduleId": "trim_reads",
                "name": "Read trimming",
                "description": "Trim adapters and low-quality bases.",
                "kind": "analysis",
                "required": True,
                "enabled": True,
                "tool": "fastp",
                "inputs": ["reads"],
                "outputs": ["clean_reads", "trim_report"],
                "params": [
                    {
                        "key": "min_length",
                        "label": "Minimum read length",
                        "type": "integer",
                        "default": 50,
                        "min": 20,
                        "max": 300,
                    },
                    {
                        "key": "quality_cutoff",
                        "label": "Quality cutoff",
                        "type": "integer",
                        "default": 20,
                        "min": 0,
                        "max": 40,
                    },
                ],
            },
            {
                "moduleId": "host_removal",
                "name": "Host removal",
                "description": "Remove host reads before downstream profiling.",
                "kind": "analysis",
                "required": False,
                "enabled": True,
                "tool": "bowtie2",
                "inputs": ["clean_reads"],
                "outputs": ["non_host_reads", "host_removal_report"],
                "params": [
                    {
                        "key": "reference",
                        "label": "Host reference",
                        "type": "select",
                        "default": "human_grch38",
                        "options": [
                            {"value": "human_grch38", "label": "Human GRCh38"},
                            {"value": "mouse_mm39", "label": "Mouse GRCm39"},
                        ],
                    }
                ],
            },
            {
                "moduleId": "qc_report",
                "name": "Report generation",
                "description": "Collect module metrics into a single report.",
                "kind": "report",
                "required": True,
                "enabled": True,
                "tool": "multiqc",
                "inputs": ["raw_qc_report", "trim_report"],
                "optionalInputs": ["host_removal_report"],
                "outputs": ["qc_report", "summary_table"],
                "params": [
                    {
                        "key": "export_intermediate",
                        "label": "Export intermediate files",
                        "type": "boolean",
                        "default": False,
                    }
                ],
            },
        ],
        "layout": {
            "nodes": [
                {"moduleId": "raw_fastqc", "x": 80, "y": 80},
                {"moduleId": "trim_reads", "x": 80, "y": 220},
                {"moduleId": "host_removal", "x": 360, "y": 220},
                {"moduleId": "qc_report", "x": 640, "y": 150},
            ],
            "edges": [
                {"from": "raw_fastqc", "to": "qc_report", "output": "raw_qc_report"},
                {"from": "trim_reads", "to": "host_removal", "output": "clean_reads"},
                {"from": "trim_reads", "to": "qc_report", "output": "trim_report"},
                {"from": "host_removal", "to": "qc_report", "output": "host_removal_report"},
            ],
        },
    },
    {
        "templateId": "taxonomic-profiling-v1",
        "name": "Taxonomic Profiling",
        "version": "0.1.0",
        "category": "Taxonomy",
        "description": "Profile microbial composition with selectable classifier modules.",
        "engine": "snakemake",
        "entrypoint": "workflow/Snakefile",
        "status": "planned",
        "tags": ["taxonomy", "kraken2", "metaphlan"],
        "inputs": [
            {
                "key": "clean_reads",
                "label": "Clean reads",
                "type": "file",
                "accept": [".fastq.gz", ".fq.gz"],
                "required": True,
                "multiple": True,
            }
        ],
        "outputs": [
            {"key": "taxonomy_table", "label": "Taxonomy table", "type": "table"},
            {"key": "taxonomy_report", "label": "Taxonomy report", "type": "html"},
        ],
        "modules": [
            {
                "moduleId": "taxonomy_classifier",
                "name": "Taxonomy classifier",
                "description": "Classify reads against a selected taxonomy database.",
                "kind": "analysis",
                "required": True,
                "enabled": True,
                "tool": "kraken2",
                "alternatives": ["metaphlan", "centrifuge"],
                "inputs": ["clean_reads"],
                "outputs": ["taxonomy_table"],
                "params": [
                    {
                        "key": "database",
                        "label": "Database",
                        "type": "select",
                        "default": "standard",
                        "options": [
                            {"value": "standard", "label": "Standard"},
                            {"value": "pluspf", "label": "PlusPF"},
                        ],
                    }
                ],
            },
            {
                "moduleId": "taxonomy_report",
                "name": "Taxonomy report",
                "description": "Render abundance charts and summary tables.",
                "kind": "report",
                "required": True,
                "enabled": True,
                "tool": "custom-report",
                "inputs": ["taxonomy_table"],
                "outputs": ["taxonomy_report"],
                "params": [],
            },
        ],
        "layout": {
            "nodes": [
                {"moduleId": "taxonomy_classifier", "x": 120, "y": 120},
                {"moduleId": "taxonomy_report", "x": 420, "y": 120},
            ],
            "edges": [
                {"from": "taxonomy_classifier", "to": "taxonomy_report", "output": "taxonomy_table"}
            ],
        },
    },
]


_DRAFTS: dict[str, dict[str, Any]] = {}


def list_workflow_templates() -> dict[str, Any]:
    return {
        "data": {
            "items": [
                _template_summary(template)
                for template in WORKFLOW_TEMPLATES
            ]
        }
    }


def get_workflow_template(template_id: str) -> dict[str, Any]:
    return {"data": deepcopy(_require_template(template_id))}


def list_workflow_modules() -> dict[str, Any]:
    modules: dict[str, dict[str, Any]] = {}
    for template in WORKFLOW_TEMPLATES:
        for module in template["modules"]:
            item = deepcopy(module)
            item["sourceTemplateId"] = template["templateId"]
            modules.setdefault(item["moduleId"], item)
    return {"data": {"items": list(modules.values())}}


def validate_workflow_draft(payload: dict[str, Any]) -> dict[str, Any]:
    template = _require_template(str(payload.get("templateId") or ""))
    draft_modules = _compose_draft_modules(template, payload.get("modules"))
    issues = _validate_modules(template, draft_modules)
    run_spec = _build_run_spec(template, draft_modules)
    return {
        "data": {
            "ok": not any(issue["severity"] == "error" for issue in issues),
            "issues": issues,
            "runSpecPreview": run_spec,
        }
    }


def create_workflow_draft(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_workflow_draft(payload)["data"]
    if not validation["ok"]:
        return {
            "data": {
                "draftId": None,
                "saved": False,
                "validation": validation,
            }
        }
    draft_id = f"draft_{uuid.uuid4().hex[:12]}"
    draft = {
        "draftId": draft_id,
        "templateId": str(payload.get("templateId")),
        "name": str(payload.get("name") or "Untitled workflow"),
        "modules": _compose_draft_modules(
            _require_template(str(payload.get("templateId"))),
            payload.get("modules"),
        ),
        "createdAt": time.time(),
        "updatedAt": time.time(),
        "validation": validation,
    }
    _DRAFTS[draft_id] = draft
    return {"data": draft}


def list_workflow_drafts() -> dict[str, Any]:
    return {
        "data": {
            "items": [
                {
                    "draftId": draft["draftId"],
                    "templateId": draft["templateId"],
                    "name": draft["name"],
                    "updatedAt": draft["updatedAt"],
                    "valid": draft["validation"]["ok"],
                }
                for draft in sorted(_DRAFTS.values(), key=lambda item: item["updatedAt"], reverse=True)
            ]
        }
    }


def _template_summary(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "templateId": template["templateId"],
        "name": template["name"],
        "version": template["version"],
        "category": template["category"],
        "description": template["description"],
        "engine": template["engine"],
        "status": template["status"],
        "tags": template["tags"],
        "moduleCount": len(template["modules"]),
        "inputCount": len(template["inputs"]),
        "outputCount": len(template["outputs"]),
    }


def _require_template(template_id: str) -> dict[str, Any]:
    normalized = str(template_id or "").strip()
    for template in WORKFLOW_TEMPLATES:
        if template["templateId"] == normalized:
            return template
    raise ValueError(f"Workflow template not found: {template_id}")


def _compose_draft_modules(template: dict[str, Any], modules: Any) -> list[dict[str, Any]]:
    by_id = {module["moduleId"]: deepcopy(module) for module in template["modules"]}
    if not isinstance(modules, list):
        return list(by_id.values())
    for patch in modules:
        if not isinstance(patch, dict):
            continue
        module_id = str(patch.get("moduleId") or "")
        if module_id not in by_id:
            continue
        current = by_id[module_id]
        if "enabled" in patch:
            current["enabled"] = bool(patch["enabled"])
        if "tool" in patch:
            current["tool"] = str(patch["tool"])
        if isinstance(patch.get("paramValues"), dict):
            current["paramValues"] = dict(patch["paramValues"])
    return list(by_id.values())


def _validate_modules(template: dict[str, Any], modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    available = {item["key"] for item in template["inputs"]}
    enabled_modules = [module for module in modules if bool(module.get("enabled"))]
    for module in modules:
        if module.get("required") and not module.get("enabled"):
            issues.append(
                _issue(
                    "error",
                    module["moduleId"],
                    "REQUIRED_MODULE_DISABLED",
                    "Required module is disabled.",
                )
            )
    for module in enabled_modules:
        missing = [name for name in module.get("inputs", []) if name not in available]
        if missing:
            issues.append(
                _issue(
                    "error",
                    module["moduleId"],
                    "MODULE_INPUT_MISSING",
                    f"Missing required input(s): {', '.join(missing)}.",
                )
            )
        for param in module.get("params", []):
            _validate_param(module, param, issues)
        available.update(module.get("outputs", []))
    return issues


def _validate_param(module: dict[str, Any], param: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    values = module.get("paramValues") if isinstance(module.get("paramValues"), dict) else {}
    value = values.get(param["key"], param.get("default"))
    param_type = param.get("type")
    if param_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            issues.append(
                _issue(
                    "error",
                    module["moduleId"],
                    "PARAM_TYPE_INVALID",
                    f"{param['key']} must be an integer.",
                )
            )
            return
        if "min" in param and value < int(param["min"]):
            issues.append(_issue("error", module["moduleId"], "PARAM_TOO_SMALL", f"{param['key']} is below minimum."))
        if "max" in param and value > int(param["max"]):
            issues.append(_issue("error", module["moduleId"], "PARAM_TOO_LARGE", f"{param['key']} is above maximum."))
    if param_type == "boolean" and not isinstance(value, bool):
        issues.append(_issue("error", module["moduleId"], "PARAM_TYPE_INVALID", f"{param['key']} must be boolean."))
    if param_type == "select":
        options = {str(option["value"]) for option in param.get("options", [])}
        if str(value) not in options:
            issues.append(
                _issue(
                    "error",
                    module["moduleId"],
                    "PARAM_OPTION_INVALID",
                    f"{param['key']} has an invalid option.",
                )
            )


def _build_run_spec(template: dict[str, Any], modules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "templateId": template["templateId"],
        "engine": template["engine"],
        "entrypoint": template["entrypoint"],
        "modules": [
            {
                "moduleId": module["moduleId"],
                "enabled": bool(module.get("enabled")),
                "tool": module.get("tool"),
                "params": {
                    param["key"]: (module.get("paramValues") or {}).get(param["key"], param.get("default"))
                    for param in module.get("params", [])
                },
            }
            for module in modules
        ],
    }


def _issue(severity: str, module_id: str, code: str, message: str) -> dict[str, str]:
    return {
        "severity": severity,
        "moduleId": module_id,
        "code": code,
        "message": message,
    }
