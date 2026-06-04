from __future__ import annotations

import time
from typing import Any


def build_runner_ensure_failure_snapshot(
    *,
    server_id: str,
    detail: str,
) -> dict[str, Any]:
    reason_code, ready_message, live_message, workflow_runtime, pipeline_registry = classify_runner_ensure_failure(detail)
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "serverId": server_id,
        "startup": {"ok": False, "message": ready_message},
        "live": {"ok": False, "message": live_message},
        "ready": {"ok": False, "message": ready_message},
        "workflowRuntime": workflow_runtime,
        "pipelineRegistry": pipeline_registry,
        "reasonCode": reason_code,
        "checkedAt": checked_at,
    }


def classify_runner_ensure_failure(detail: str) -> tuple[str, str, str, dict[str, Any], dict[str, Any]]:
    message = str(detail or "").strip() or "remote runner ensure failed"
    lowered = message.lower()
    workflow_runtime: dict[str, Any] = {}
    pipeline_registry: dict[str, Any] = {}
    if (
        "verify workflow runtime prerequisites" in lowered
        or "workflow runtime" in lowered
        or "conda/mamba is required" in lowered
        or "micromamba" in lowered
        or "snakemake command not configured" in lowered
    ):
        ready_message = f"Remote workflow runtime is unavailable: {message}"
        workflow_runtime = {"ok": False, "message": ready_message}
        return "WORKFLOW_RUNTIME_MISSING", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
    if "pipeline registry" in lowered or "registered pipeline snakefile is missing" in lowered:
        ready_message = f"Remote pipeline registry is unavailable: {message}"
        pipeline_registry = {"ok": False, "message": ready_message}
        return "PIPELINE_REGISTRY_NOT_READY", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
    if "bootstrap canary failed" in lowered or "canary failed" in lowered:
        ready_message = f"Remote runner bootstrap canary failed: {message}"
        return "RUNNER_CANARY_FAILED", ready_message, "Remote runner process failed post-start validation.", workflow_runtime, pipeline_registry
    if "rollback did not restore previous release" in lowered or "rollback failed" in lowered:
        ready_message = f"Remote runner rollback failed after activation error: {message}"
        return "RUNNER_ROLLBACK_FAILED", ready_message, "Remote runner process failed during rollback recovery.", workflow_runtime, pipeline_registry
    if "python3 required" in lowered:
        ready_message = f"Remote host is missing python3 required for runner setup: {message}"
        return "REMOTE_PYTHON_MISSING", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
    if "install remote runner dependencies" in lowered:
        if "python3" in lowered and (
            "not found" in lowered or "command not found" in lowered or "no such file" in lowered
        ):
            ready_message = f"Remote host is missing python3 required for runner setup: {message}"
            return "REMOTE_PYTHON_MISSING", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
        ready_message = (
            "Remote runner dependency installation failed while setting up the Python environment: "
            f"{message}"
        )
        return "SERVICE_RUNTIME_SETUP_FAILED", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
    if "start remote runner service" in lowered or "service failed to start" in lowered:
        ready_message = f"Remote runner service failed to start: {message}"
        return "SERVICE_START_FAILED", ready_message, "Remote runner process failed to stay alive.", workflow_runtime, pipeline_registry
    if "python3" in lowered and ("not found" in lowered or "command not found" in lowered):
        ready_message = f"Remote host is missing python3 required for runner setup: {message}"
        return "REMOTE_PYTHON_MISSING", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
    ready_message = f"Remote runner setup failed: {message}"
    return "RUNNER_SETUP_FAILED", ready_message, "Remote runner process is not running.", workflow_runtime, pipeline_registry
