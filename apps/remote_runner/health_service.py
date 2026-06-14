from __future__ import annotations

import logging
import os
from pathlib import Path
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .config import RemoteRunnerConfig, inspect_runtime_layout, inspect_workflow_runtime
from .errors import RemoteRunnerReadinessError
from .execution_diagnostics import build_execution_diagnostics
from .pipeline import inspect_pipeline_registry


_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
LOGGER = logging.getLogger(__name__)


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
    payload = _build_health_payload("ok", checks, cfg)
    payload["workflowRuntime"] = _workflow_runtime_payload(workflow, cfg)
    payload["pipelineRegistry"] = registry.model_dump()
    _enrich_with_operational_metrics(payload, cfg)
    _enrich_with_execution_readiness(payload, cfg)
    checks.update(_operational_readiness_checks(payload))
    checks.update(_execution_readiness_checks(payload))
    payload["checks"] = checks
    payload["status"] = "ok" if all(checks.values()) else "failed"
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


def ensure_execution_admission_ready(cfg: RemoteRunnerConfig) -> None:
    diagnostics = build_execution_diagnostics(cfg)
    readiness = diagnostics["readiness"]
    if readiness["ok"]:
        return
    reason_code = readiness.get("reasonCode") or "EXECUTION_NOT_READY"
    LOGGER.warning(
        "execution admission rejected",
        extra={
            "event": "execution.admission.rejected",
            "decision": "reject",
            "reasonCode": reason_code,
            "blockingReasons": readiness.get("blockingReasons", []),
        },
    )
    raise RemoteRunnerReadinessError(f"{reason_code}: execution control plane is not ready")


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


def _enrich_with_operational_metrics(payload: dict[str, Any], cfg: RemoteRunnerConfig) -> None:
    from .metrics import collect_disk_metrics, collect_queue_metrics, collect_sqlite_metrics, get_metrics
    from .run_worker_storage import build_run_worker_health

    if Path(cfg.db_path).is_file():
        try:
            queue = collect_queue_metrics(cfg)
            payload["queue"] = queue
        except Exception:
            payload["queue"] = {"error": "queue_metrics_failed"}
        try:
            workers = build_run_worker_health(cfg)
            payload["workers"] = workers
        except Exception:
            payload["workers"] = {"error": "worker_metrics_failed"}
        try:
            payload["sqlite"] = collect_sqlite_metrics(cfg)
        except Exception:
            payload["sqlite"] = {"ok": False, "error": "sqlite_metrics_failed"}
    else:
        payload["queue"] = {"error": "runtime_database_missing"}
        payload["workers"] = {"error": "runtime_database_missing"}
        payload["sqlite"] = {"ok": False, "error": "runtime_database_missing"}
    try:
        disk = collect_disk_metrics(cfg.data_root)
        payload["disk"] = disk
    except Exception:
        payload["disk"] = {"error": "disk_metrics_failed"}
    try:
        metrics = get_metrics()
        payload["metrics"] = metrics.snapshot()
    except Exception:
        payload["metrics"] = {"error": "metrics_snapshot_failed"}


def _enrich_with_execution_readiness(payload: dict[str, Any], cfg: RemoteRunnerConfig) -> None:
    if not Path(cfg.db_path).is_file():
        payload["executionReadiness"] = {
            "schemaVersion": "execution-readiness-policy.v1",
            "ok": False,
            "status": "failed",
            "reasonCode": "RUNTIME_DATABASE_MISSING",
            "blockingReasons": [
                {"code": "RUNTIME_DATABASE_MISSING", "message": "Runtime database is missing."}
            ],
            "degradedReasons": [],
            "checks": {
                "sqliteWal": False,
                "sqliteBusyTimeout": False,
                "executionInvariants": False,
                "runWorkerAvailable": False,
                "workerHeartbeatFresh": False,
                "queueWaitWithinThreshold": True,
                "resourceWaitWithinThreshold": True,
            },
        }
        return
    try:
        diagnostics = build_execution_diagnostics(cfg)
    except Exception as exc:  # noqa: BLE001 - readiness must report diagnostics failure explicitly.
        payload["executionReadiness"] = {
            "schemaVersion": "execution-readiness-policy.v1",
            "ok": False,
            "status": "failed",
            "reasonCode": "EXECUTION_DIAGNOSTICS_FAILED",
            "blockingReasons": [
                {
                    "code": "EXECUTION_DIAGNOSTICS_FAILED",
                    "message": "Execution diagnostics could not be collected.",
                    "details": {"errorType": type(exc).__name__},
                }
            ],
            "degradedReasons": [],
            "checks": {
                "sqliteWal": False,
                "sqliteBusyTimeout": False,
                "executionInvariants": False,
                "runWorkerAvailable": False,
                "workerHeartbeatFresh": False,
                "queueWaitWithinThreshold": True,
                "resourceWaitWithinThreshold": True,
            },
        }
        return
    payload["executionReadiness"] = diagnostics["readiness"]


def _operational_readiness_checks(payload: dict[str, Any]) -> dict[str, bool]:
    queue = payload.get("queue") if isinstance(payload.get("queue"), dict) else {}
    workers = payload.get("workers") if isinstance(payload.get("workers"), dict) else {}
    sqlite = payload.get("sqlite") if isinstance(payload.get("sqlite"), dict) else {}
    disk = payload.get("disk") if isinstance(payload.get("disk"), dict) else {}
    return {
        "queue_observable": "error" not in queue,
        "workers_observable": "error" not in workers,
        "sqlite_wal": bool(sqlite.get("walEnabled")),
        "sqlite_busy_timeout": bool(sqlite.get("busyTimeoutOk")),
        "disk_free": "error" not in disk and int(disk.get("freeBytes") or 0) > 0,
    }


def _execution_readiness_checks(payload: dict[str, Any]) -> dict[str, bool]:
    readiness = payload.get("executionReadiness") if isinstance(payload.get("executionReadiness"), dict) else {}
    checks = readiness.get("checks") if isinstance(readiness.get("checks"), dict) else {}
    return {
        "execution_ready": bool(readiness.get("ok")),
        "execution_invariants": bool(checks.get("executionInvariants")),
        "run_worker_available": bool(checks.get("runWorkerAvailable")),
        "worker_heartbeat_fresh": bool(checks.get("workerHeartbeatFresh")),
    }
