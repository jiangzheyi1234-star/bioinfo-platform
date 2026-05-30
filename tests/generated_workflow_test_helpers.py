from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.generated_workflow import GeneratedWorkflow, prepare_generated_tool_workflow
from apps.remote_runner.storage import upsert_tool
from apps.remote_runner.tools import normalize_rule_template


READY_CONTRACT_STATUS = {
    "dryRun": {
        "status": "passed",
        "message": "test fixture dry-run passed",
        "checkedAt": "2026-01-01T00:00:00Z",
    },
    "smokeRun": {
        "status": "passed",
        "message": "test fixture smoke passed",
        "checkedAt": "2026-01-01T00:00:00Z",
    },
    "outputValidation": {
        "status": "passed",
        "message": "test fixture outputs validated",
        "checkedAt": "2026-01-01T00:00:00Z",
    },
    "production": {"status": "not_run", "message": ""},
}


def prepare_unchecked_generated_tool_workflow(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    run_spec: dict[str, Any],
    resolved_inputs: list[dict[str, Any]],
    work_dir: Path,
    result_dir: Path,
) -> GeneratedWorkflow:
    return prepare_generated_tool_workflow(
        cfg,
        run_id=run_id,
        request_id=request_id,
        run_spec=run_spec,
        resolved_inputs=resolved_inputs,
        work_dir=work_dir,
        result_dir=result_dir,
        require_workflow_ready=False,
    )


def upsert_ready_tool(cfg: RemoteRunnerConfig, tool: dict[str, Any]) -> dict[str, Any]:
    manifest = deepcopy(tool)
    manifest.setdefault("targetPlatform", "linux-64")
    manifest.setdefault("targetPlatformSupported", True)
    manifest.setdefault("status", "declared")
    manifest.setdefault("message", "Tool declared.")

    template = manifest.get("ruleTemplate")
    if isinstance(template, dict) and template:
        completed_template = _complete_rule_template_for_ready_contract(template, manifest)
        manifest["ruleTemplate"] = normalize_rule_template(completed_template, required=True)

    manifest["contractStatus"] = deepcopy(READY_CONTRACT_STATUS)
    return upsert_tool(cfg, manifest)


def _complete_rule_template_for_ready_contract(
    rule_template: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    template = deepcopy(rule_template)
    template.setdefault("params", {})
    if not _has_threads(template):
        template["threads"] = 1
    if not _has_scheduler_resources(template):
        template["schedulerResources"] = {"mem_mb": 128}
    template.setdefault("log", "logs/tool.log")
    template.setdefault("environment", _default_environment(manifest))
    template.setdefault("smokeTest", {"inputs": _default_smoke_inputs(template)})
    return template


def _default_environment(manifest: dict[str, Any]) -> dict[str, Any]:
    source = str(manifest.get("source") or "").strip()
    package_spec = str(manifest.get("packageSpec") or "").strip()
    channels = ["conda-forge", "bioconda"] if source == "bioconda" else ["conda-forge"]
    return {"conda": {"channels": channels, "dependencies": [package_spec]}}


def _default_smoke_inputs(rule_template: dict[str, Any]) -> dict[str, dict[str, str]]:
    smoke_inputs: dict[str, dict[str, str]] = {}
    inputs = rule_template.get("inputs") if isinstance(rule_template.get("inputs"), list) else []
    for index, item in enumerate(inputs):
        if not isinstance(item, dict) or not bool(item.get("required", True)):
            continue
        name = str(item.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        if name:
            smoke_inputs[name] = {
                "filename": f"{name}.txt",
                "mimeType": "text/plain",
                "content": "fixture\n",
            }
    return smoke_inputs


def _has_threads(rule_template: dict[str, Any]) -> bool:
    if rule_template.get("threads") not in (None, ""):
        return True
    resources = rule_template.get("resources")
    return isinstance(resources, dict) and resources.get("threads") not in (None, "")


def _has_scheduler_resources(rule_template: dict[str, Any]) -> bool:
    if rule_template.get("schedulerResources") not in (None, {}):
        return True
    if rule_template.get("runtimeResources") not in (None, {}):
        return True
    resources = rule_template.get("resources")
    if not isinstance(resources, dict):
        return False
    return any(key != "threads" for key in resources)
