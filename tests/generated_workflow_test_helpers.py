from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig
from apps.remote_runner.generated_workflow import GeneratedWorkflow, prepare_generated_tool_workflow
from apps.remote_runner.generated_workflow_graph import GENERATED_WORKFLOW_RULE_CONTRACT_VERSION
from apps.remote_runner.storage import upsert_tool
from apps.remote_runner.tool_revisions import publish_tool_revision
from apps.remote_runner.tools import normalize_rule_template
from apps.remote_runner.workflow_design_contract import workflow_design_to_generated_run_spec
from apps.remote_runner.workflow_design_storage import create_workflow_design_draft


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

_TEST_TOOL_REVISIONS: dict[str, str] = {}


def test_tool_revision_id(tool_id: str) -> str:
    return _TEST_TOOL_REVISIONS.get(tool_id, tool_id)


def generated_workflow_node(
    tool_id: str,
    *,
    node_id: str = "run_tool",
    inputs: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {"id": node_id, "toolRevisionId": _TEST_TOOL_REVISIONS.get(tool_id, tool_id)}
    if inputs is not None:
        node["inputs"] = inputs
    if params is not None:
        node["params"] = params
    if runtime is not None:
        node["runtime"] = runtime
    return node


def generated_workflow_graph(
    nodes: list[dict[str, Any]],
    *,
    edges: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    graph: dict[str, Any] = {
        "contractVersion": GENERATED_WORKFLOW_RULE_CONTRACT_VERSION,
        "nodes": nodes,
        "edges": edges or [],
    }
    if outputs is not None:
        graph["outputs"] = outputs
    return graph


def generated_workflow_run_spec(
    tool_id: str,
    *,
    input_name: str = "primary",
    input_role: str = "input",
    node_id: str = "run_tool",
    project_id: str | None = None,
    resource_bindings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_spec: dict[str, Any] = {
        "pipelineId": "generated-tool-run-v1",
        "workflow": generated_workflow_graph(
            [
                generated_workflow_node(
                    tool_id,
                    node_id=node_id,
                    inputs={input_name: {"fromInput": input_role}},
                )
            ],
        ),
    }
    if project_id is not None:
        run_spec["projectId"] = project_id
    if resource_bindings is not None:
        run_spec["resourceBindings"] = resource_bindings
    return run_spec


def workflow_design_run_spec_from_graph(
    cfg: RemoteRunnerConfig,
    graph: dict[str, Any],
    *,
    upload_id: str,
    project_id: str = "proj_demo",
    input_role: str = "input",
    input_filename: str = "reads.txt",
    draft_name: str = "Generated workflow",
) -> dict[str, Any]:
    saved = create_workflow_design_draft(
        cfg,
        {
            "contractVersion": "workflow-design-draft-v1",
            "engine": "snakemake",
            "metadata": {"name": draft_name, "description": "", "projectId": project_id, "tags": []},
            "inputs": [
                {
                    "id": input_role,
                    "role": input_role,
                    "path": f"inputs/{input_filename}",
                    "filename": input_filename,
                    "mimeType": "text/plain",
                }
            ],
            "nodes": [_workflow_design_node_from_graph_node(node) for node in graph.get("nodes", [])],
            "edges": list(graph.get("edges") or []),
            "resources": {"bindings": {}, "metadata": {}},
            "outputs": list(graph.get("outputs") or []),
            "provenance": {},
        },
    )
    run_spec = workflow_design_to_generated_run_spec(saved["draft"], draft_id=saved["draftId"], revision=saved["revision"])
    run_spec["inputs"] = [{"uploadId": upload_id, "filename": input_filename, "role": input_role}]
    return run_spec


def _workflow_design_node_from_graph_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(node.get("id") or "run_tool"),
        "toolRevisionId": str(node.get("toolRevisionId") or ""),
        "inputs": dict(node.get("inputs") or {}),
        "params": dict(node.get("params") or {}),
        "runtime": dict(node.get("runtime") or {}),
        "resources": {},
        "outputs": {},
        "metadata": {},
        "provenance": {},
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
    published = publish_tool_revision(cfg, manifest)
    published["status"] = "published"
    saved = upsert_tool(cfg, published)
    _TEST_TOOL_REVISIONS[str(saved.get("id") or "")] = str(saved.get("toolRevisionId") or "")
    return saved


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
