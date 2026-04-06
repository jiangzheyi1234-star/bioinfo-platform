"""Workbench runtime helpers extracted from RuntimeService."""

from __future__ import annotations

from typing import Any

from core.execution.tool_bridge_service import ToolBridgeService


def _bridge(runtime: Any) -> ToolBridgeService:
    bridge = getattr(runtime, "_tool_bridge_service", None)
    if bridge is None:
        bridge = ToolBridgeService(
            service_locator=runtime._service_locator,
            plugin_registry=runtime._service_locator.plugin_registry,
        )
        runtime._tool_bridge_service = bridge
    return bridge


def list_workbench_tools(runtime: Any, *, project_id: str) -> list[dict[str, Any]]:
    runtime._ensure_project_open(project_id)
    tools = _bridge(runtime).get_tools()
    if not isinstance(tools, list):
        raise RuntimeError("workbench tools payload is invalid")
    return tools


def get_workbench_config(runtime: Any, *, project_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    config = _bridge(runtime).get_integrated_workbench_config()
    if not isinstance(config, dict):
        raise RuntimeError("workbench config payload is invalid")
    return config


def get_workbench_history(runtime: Any, *, project_id: str) -> list[dict[str, Any]]:
    runtime._ensure_project_open(project_id)
    history = _bridge(runtime).get_execution_history()
    if not isinstance(history, list):
        raise RuntimeError("workbench history payload is invalid")
    return history


def get_workbench_result(runtime: Any, *, project_id: str, execution_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    normalized_execution_id = str(execution_id or "").strip()
    if not normalized_execution_id:
        raise ValueError("execution_id is required")
    payload = _bridge(runtime).get_results_for_execution(normalized_execution_id)
    if not isinstance(payload, dict):
        raise RuntimeError("workbench result payload is invalid")
    if str(payload.get("status") or "") != "ok":
        raise RuntimeError(str(payload.get("message") or "failed to load execution result"))
    return payload


def get_workbench_remote_status(runtime: Any, *, project_id: str, execution_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    normalized_execution_id = str(execution_id or "").strip()
    if not normalized_execution_id:
        raise ValueError("execution_id is required")
    payload = _bridge(runtime).get_execution_remote_status(normalized_execution_id)
    if not isinstance(payload, dict):
        raise RuntimeError("workbench remote status payload is invalid")
    if str(payload.get("status") or "") == "error":
        raise RuntimeError(str(payload.get("message") or "failed to query remote status"))
    return payload


def run_workbench_tool(
    runtime: Any,
    *,
    project_id: str,
    task_id: str | None,
    tool_id: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    normalized_tool_id = str(tool_id or "").strip()
    if not normalized_tool_id:
        raise ValueError("tool_id is required")
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    result = _bridge(runtime).execute_tool(normalized_tool_id, params, task_id=task_id)
    payload = {
        "status": str(getattr(result, "status", "") or ""),
        "execution_id": str(getattr(result, "execution_id", "") or ""),
        "sample_id": str(getattr(result, "sample_id", "") or ""),
        "message": str(getattr(result, "message", "") or ""),
    }
    if payload["status"] != "ok":
        raise RuntimeError(payload["message"] or "workbench run failed")
    return payload


def get_workbench_remote_primer_results(
    runtime: Any,
    *,
    project_id: str,
    remote_result_dir: str,
) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    normalized_dir = str(remote_result_dir or "").strip()
    if not normalized_dir:
        raise ValueError("remote_result_dir is required")
    payload = _bridge(runtime).get_remote_primer_results(normalized_dir)
    if not isinstance(payload, dict):
        raise RuntimeError("remote primer payload is invalid")
    if str(payload.get("status") or "") != "ok":
        raise RuntimeError(str(payload.get("message") or "failed to load remote primer results"))
    return payload
