from __future__ import annotations

import os
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .config import RemoteRunnerConfig, inspect_runtime_layout, inspect_workflow_runtime
from .errors import RemoteRunnerReadinessError
from .pipeline import inspect_pipeline_registry


_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class WorkflowRuntimeInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    message: str
    snakemakeVersion: str = ""
    workflowProfileConfigured: bool = False
    workflowProfileOk: bool = True
    workflowProfileMessage: str = ""
    workflowProfileDir: str = ""
    workflowProfileName: str = ""
    workflowProfilePath: str = ""


class PipelineRegistryInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    message: str
    count: int = Field(ge=0)
    items: list[dict[str, Any]] = Field(default_factory=list)


def build_health_startup_payload(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    checks = inspect_runtime_layout(cfg)
    status = "ok" if all(checks.values()) else "failed"
    return _build_health_payload(status, checks, cfg)


def build_health_live_payload(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    checks = {"process": True, "pid": bool(os.getpid())}
    return _build_health_payload("ok", checks, cfg)


def build_health_ready_payload(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    checks = inspect_runtime_layout(cfg)
    workflow = _workflow_runtime_inspection(cfg)
    registry = _pipeline_registry_inspection(cfg)
    checks["auth"] = bool(cfg.token)
    checks["workflow_runtime"] = workflow.ok
    checks["workflow_profile"] = workflow.workflowProfileOk
    checks["pipeline_registry"] = registry.ok
    status = "ok" if all(checks.values()) else "failed"
    payload = _build_health_payload(status, checks, cfg)
    payload["workflowRuntime"] = _workflow_runtime_payload(workflow, cfg)
    payload["pipelineRegistry"] = registry.model_dump()
    return payload


def ensure_submission_ready(cfg: RemoteRunnerConfig) -> None:
    workflow = _workflow_runtime_inspection(cfg)
    registry = _pipeline_registry_inspection(cfg)
    detail_parts: list[str] = []
    reason_code = ""
    if not workflow.ok:
        reason_code = "WORKFLOW_RUNTIME_NOT_READY"
        detail_parts.append(workflow.message or "Workflow runtime is not ready.")
    if not registry.ok:
        if not reason_code:
            reason_code = "PIPELINE_REGISTRY_NOT_READY"
        detail_parts.append(registry.message or "Pipeline registry is not ready.")
    if detail_parts:
        raise RemoteRunnerReadinessError(f"{reason_code}: {'; '.join(detail_parts)}")


def _build_health_payload(status: str, checks: dict[str, bool], cfg: RemoteRunnerConfig) -> dict[str, Any]:
    return {
        "status": status,
        "service": "h2ometa-remote",
        "version": cfg.version,
        "startedAt": _STARTED_AT,
        "mode": cfg.mode,
        "checks": checks,
    }


def _workflow_runtime_inspection(cfg: RemoteRunnerConfig) -> WorkflowRuntimeInspection:
    return WorkflowRuntimeInspection.model_validate(inspect_workflow_runtime(cfg))


def _pipeline_registry_inspection(cfg: RemoteRunnerConfig) -> PipelineRegistryInspection:
    return PipelineRegistryInspection.model_validate(inspect_pipeline_registry(cfg))


def _workflow_runtime_payload(
    workflow: WorkflowRuntimeInspection,
    cfg: RemoteRunnerConfig,
) -> dict[str, Any]:
    return {
        "ok": workflow.ok,
        "message": workflow.message,
        "provider": cfg.workflow_runtime_provider,
        "source": cfg.workflow_runtime_source,
        "version": cfg.workflow_runtime_version,
        "snakemakeCommand": cfg.snakemake_command,
        "snakemakeVersion": workflow.snakemakeVersion or cfg.snakemake_version or "",
        "workflowProfileConfigured": workflow.workflowProfileConfigured,
        "workflowProfileOk": workflow.workflowProfileOk,
        "workflowProfileMessage": workflow.workflowProfileMessage,
        "workflowProfileDir": workflow.workflowProfileDir or cfg.workflow_profile_dir or "",
        "workflowProfileName": workflow.workflowProfileName or cfg.workflow_profile_name or "",
        "workflowProfilePath": workflow.workflowProfilePath,
    }
