from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / "config.py").exists() and (candidate / "core").is_dir():
            return candidate
    raise SystemExit("ERROR: run this script from inside the bio_ui repository")


def import_repo_script(module_name: str) -> Any:
    scripts_dir = find_repo_root() / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    return __import__(module_name)


def response_data(payload: dict[str, Any]) -> Any:
    data = payload["data"]
    if isinstance(data, dict) and set(data.keys()) == {"data"}:
        return data["data"]
    return data


def selected_server_id(api_base: str, *, timeout: float = 5.0) -> str:
    remote_smoke = import_repo_script("remote_smoke")
    ready, context = remote_smoke.check_local_api(api_base, timeout, bootstrap=False)
    if not ready or not context:
        raise RuntimeError("Local API did not return a ready server context.")
    server_id = str(context.get("serverId") or "").strip()
    if not server_id:
        raise RuntimeError("Local API server context did not include serverId.")
    return server_id


def build_workflow_design_draft(
    *,
    project_id: str,
    name: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
    resource_bindings: dict[str, Any] | None = None,
    input_role: str = "input",
    input_filename: str = "input.txt",
) -> dict[str, Any]:
    return {
        "contractVersion": "workflow-design-draft-v1",
        "engine": "snakemake",
        "metadata": {"name": name, "description": "", "projectId": project_id, "tags": ["smoke"]},
        "inputs": [
            {
                "id": input_role,
                "role": input_role,
                "path": f"inputs/{input_filename}",
                "filename": input_filename,
                "mimeType": "text/plain",
            }
        ],
        "nodes": _workflow_design_nodes(nodes),
        "edges": edges or [],
        "resources": {"bindings": resource_bindings or {}},
        "outputs": outputs or [],
        "provenance": {"createdBy": "remote-smoke"},
    }


def workflow_design_node(
    *,
    node_id: str,
    tool_revision_id: str,
    inputs: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "toolRevisionId": tool_revision_id,
        "inputs": inputs or {},
        "params": params or {},
        "runtime": {},
    }


def build_workflow_design_run_submit_payload(
    *,
    request_id: str,
    server_id: str,
    upload: dict[str, Any],
    plan: dict[str, Any],
    input_role: str = "input",
) -> dict[str, Any]:
    run_spec = dict(plan["runSpec"])
    run_spec["inputs"] = [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": input_role}]
    return {"serverId": server_id, "requestId": request_id, "runSpec": run_spec}


def build_upload_submit_payload(
    *,
    server_id: str,
    filename: str,
    content_base64: str,
    mime_type: str,
) -> dict[str, Any]:
    return {
        "serverId": server_id,
        "filename": filename,
        "contentBase64": content_base64,
        "mimeType": mime_type,
    }


def create_and_plan_workflow_design(
    *,
    api_base: str,
    http_json,
    server_id: str,
    draft: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    created = response_data(http_json(
        "POST",
        api_base,
        "/api/v1/workflow-design-drafts",
        payload={"serverId": server_id, "draft": draft},
        timeout=30,
    ))
    plan = response_data(http_json(
        "POST",
        api_base,
        f"/api/v1/workflow-design-drafts/{created['draftId']}/plan",
        payload={"serverId": server_id},
        timeout=timeout,
    ))
    if not plan.get("valid"):
        return plan
    compiled = response_data(http_json(
        "POST",
        api_base,
        f"/api/v1/workflow-design-drafts/{created['draftId']}/compile",
        payload={"serverId": server_id},
        timeout=timeout,
    ))
    return {**plan, **compiled, "valid": plan.get("valid")}


def prepare_tool_with_job(
    *,
    api_base: str,
    http_json,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    job = response_data(http_json("POST", api_base, "/api/v1/tools/prepare-jobs", payload=payload, timeout=30))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if job.get("status") == "succeeded":
            result = job.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("tool prepare job succeeded without a result payload")
            return result
        if job.get("status") in {"failed", "cancelled"}:
            raise RuntimeError(str(job.get("errorCode") or job.get("message") or "TOOL_PREPARE_JOB_FAILED"))
        time.sleep(1.5)
        job = response_data(http_json("GET", api_base, f"/api/v1/tools/prepare-jobs/{job['jobId']}", timeout=10))
    raise TimeoutError(f"tool prepare job timed out: {job.get('jobId')}")


def workflow_design_edge(
    *,
    from_node: str,
    from_port: str,
    to_node: str,
    to_port: str,
) -> dict[str, Any]:
    return {
        "from": {"nodeId": from_node, "port": from_port},
        "to": {"nodeId": to_node, "port": to_port},
    }


def _workflow_design_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        for input_name, binding in dict(node.get("inputs") or {}).items():
            if isinstance(binding, dict) and binding.get("fromStep") and binding.get("output"):
                raise ValueError(f"WORKFLOW_DESIGN_EDGE_REQUIRED: {node_id}.{input_name}")
        normalized.append(dict(node))
    return normalized
