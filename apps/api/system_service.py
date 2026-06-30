"""System metadata service helpers for the local API."""

from __future__ import annotations

import os
from typing import Any

from core.deployment_mode import (
    build_production_governance_readiness,
    require_supported_deployment_mode,
    validate_deployment_security,
)


TERMINAL_RUNTIME_BUILD_ID = "terminal-websocket-v1"
LOCAL_EXECUTION_READINESS_SCHEMA_VERSION = "local-execution-readiness-projection.v1"


async def health_from_request() -> dict[str, str]:
    return {"status": "ok", "build_id": TERMINAL_RUNTIME_BUILD_ID}


async def version_from_request() -> dict[str, Any]:
    return {
        "item": {
            "build_id": os.environ.get("H2OMETA_RUNTIME_BUILD_ID", TERMINAL_RUNTIME_BUILD_ID),
            "terminal_transport": "websocket",
            "backend_source": os.environ.get("H2OMETA_BACKEND_SOURCE", "unknown"),
        }
    }


async def service_info_from_request() -> dict[str, Any]:
    build_id = os.environ.get("H2OMETA_RUNTIME_BUILD_ID", TERMINAL_RUNTIME_BUILD_ID)
    backend_source = os.environ.get("H2OMETA_BACKEND_SOURCE", "unknown")
    deployment = require_supported_deployment_mode()
    runtime_snapshot = _collect_runtime_snapshot()
    state_counts = runtime_snapshot["stateCounts"]
    execution_readiness = runtime_snapshot["executionReadiness"]
    readiness_checks = {
        "process": bool(os.getpid()),
        "systemRoutes": True,
        "remoteRunner": state_counts.get("remoteRunnerConnected", False),
        "executionDiagnostics": execution_readiness.get("diagnosticsAvailable") is True,
        "executionReady": execution_readiness.get("ready") is True,
    }
    readiness_status = "ready" if all(readiness_checks.values()) else "degraded"
    security_warnings = validate_deployment_security()
    return {
        "item": {
            "service": "h2ometa-local-api",
            "kind": "local-control-plane",
            "identity": {
                "service": "h2ometa-local-api",
                "processId": os.getpid(),
                "backendSource": backend_source,
            },
            "version": {
                "buildId": build_id,
                "terminalRuntimeBuildId": TERMINAL_RUNTIME_BUILD_ID,
                "terminalTransport": "websocket",
                "backendSource": backend_source,
            },
            "deployment": deployment.to_dict(),
            "productionGovernance": _service_info_production_governance_projection(
                build_production_governance_readiness()
            ),
            "readiness": {
                "status": readiness_status,
                "checks": readiness_checks,
            },
            "executionReadiness": execution_readiness,
            "stateCounts": state_counts,
            "securityWarnings": security_warnings,
        }
    }


def _collect_runtime_snapshot() -> dict[str, Any]:
    counts: dict[str, Any] = {"localApiProcesses": 1}
    execution_readiness = _execution_unavailable(
        connected=False,
        server_id="",
        reason_code="SSH_NOT_CONNECTED",
    )
    try:
        from apps.api.route_utils import runtime_service

        service = runtime_service()
        ssh_status = service.get_ssh_status()
        connected = bool(ssh_status.get("connected", False))
        server_id = str(ssh_status.get("serverId") or "").strip()
        counts["remoteRunnerConnected"] = connected
        counts["activeSshSessions"] = 1 if ssh_status.get("connected") else 0
        if connected:
            execution_readiness = _collect_execution_readiness_projection(service, server_id=server_id)
            _add_execution_state_counts(counts, execution_readiness)
    except Exception:  # noqa: BLE001 - service-info must stay available with a redacted status.
        counts["remoteRunnerConnected"] = False
        counts["activeSshSessions"] = 0
    return {"stateCounts": counts, "executionReadiness": execution_readiness}


def _collect_execution_readiness_projection(service: Any, *, server_id: str) -> dict[str, Any]:
    if not server_id:
        return _execution_unavailable(
            connected=True,
            server_id="",
            reason_code="SERVER_ID_UNAVAILABLE",
        )
    try:
        diagnostics = service.get_runner_execution_diagnostics(server_id)
    except Exception:  # noqa: BLE001 - do not copy remote errors, paths, or tokens into service-info.
        return _execution_unavailable(
            connected=True,
            server_id=server_id,
            reason_code="EXECUTION_DIAGNOSTICS_UNAVAILABLE",
        )
    return _execution_readiness_projection(server_id=server_id, diagnostics=diagnostics)


def _execution_readiness_projection(*, server_id: str, diagnostics: dict[str, Any]) -> dict[str, Any]:
    readiness = _mapping(diagnostics.get("readiness"))
    queue = _mapping(diagnostics.get("queueMetrics"))
    worker_health = _mapping(diagnostics.get("workerHealth"))
    worker_summary = _mapping(worker_health.get("summary"))
    ready = readiness.get("ok") is True
    return {
        "schemaVersion": LOCAL_EXECUTION_READINESS_SCHEMA_VERSION,
        "connected": True,
        "diagnosticsAvailable": True,
        "ready": ready,
        "status": "ready" if ready else str(readiness.get("status") or "degraded"),
        "reasonCode": str(readiness.get("reasonCode") or ""),
        "serverId": server_id,
        "generatedAt": str(diagnostics.get("generatedAt") or ""),
        "queue": _execution_queue_projection(queue),
        "workers": _execution_worker_projection(worker_health, worker_summary),
        "checks": _bool_mapping(readiness.get("checks")),
    }


def _execution_queue_projection(queue: dict[str, Any]) -> dict[str, Any]:
    wait_reasons = _mapping(queue.get("waitReasons"))
    return {
        "queuedJobs": _int_value(queue.get("queuedJobs")),
        "totalQueuedJobs": _int_value(queue.get("totalQueuedJobs")),
        "scheduledQueuedJobs": _int_value(queue.get("scheduledQueuedJobs")),
        "claimedJobs": _int_value(queue.get("claimedJobs")),
        "activeLeases": _int_value(queue.get("activeLeases")),
        "resourceWaitJobs": _int_value(queue.get("resourceWaitJobs")),
        "oldestQueuedAgeSeconds": _optional_int(queue.get("oldestQueuedAgeSeconds")),
        "waitReasons": {str(key): _int_value(value) for key, value in wait_reasons.items()},
    }


def _execution_worker_projection(
    worker_health: dict[str, Any],
    worker_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "workerCount": _int_value(worker_summary.get("workerCount")),
        "totalSlots": _int_value(worker_summary.get("totalSlots")),
        "runningSlots": _int_value(worker_summary.get("runningSlots")),
        "idleSlots": _int_value(worker_summary.get("idleSlots")),
        "queueDepth": _int_value(worker_health.get("queueDepth")),
        "claimedJobs": _int_value(worker_health.get("claimedJobs")),
        "workerStates": _int_dict(worker_summary.get("workerStates")),
        "slotStates": _int_dict(worker_summary.get("slotStates")),
    }


def _execution_unavailable(*, connected: bool, server_id: str, reason_code: str) -> dict[str, Any]:
    return {
        "schemaVersion": LOCAL_EXECUTION_READINESS_SCHEMA_VERSION,
        "connected": connected,
        "diagnosticsAvailable": False,
        "ready": False,
        "status": "unavailable",
        "reasonCode": reason_code,
        "serverId": server_id,
        "generatedAt": "",
        "queue": {},
        "workers": {},
        "checks": {},
    }


def _add_execution_state_counts(counts: dict[str, Any], execution_readiness: dict[str, Any]) -> None:
    queue = _mapping(execution_readiness.get("queue"))
    workers = _mapping(execution_readiness.get("workers"))
    if queue:
        counts["queueDepth"] = _int_value(queue.get("queuedJobs"))
        counts["claimedJobs"] = _int_value(queue.get("claimedJobs"))
        counts["activeLeases"] = _int_value(queue.get("activeLeases"))
        counts["resourceWaitJobs"] = _int_value(queue.get("resourceWaitJobs"))
    if workers:
        counts["runWorkerCount"] = _int_value(workers.get("workerCount"))
        counts["runningWorkerSlots"] = _int_value(workers.get("runningSlots"))
        counts["idleWorkerSlots"] = _int_value(workers.get("idleSlots"))


def _service_info_production_governance_projection(readiness: dict[str, Any]) -> dict[str, Any]:
    """Return the service-info allowlist projection for production governance."""
    return {
        "schemaVersion": str(readiness.get("schemaVersion") or ""),
        "currentModeStatus": str(readiness.get("currentModeStatus") or ""),
        "publicMultiUserStatus": str(readiness.get("publicMultiUserStatus") or ""),
        "publicMultiUserReady": readiness.get("publicMultiUserReady") is True,
        "currentModeBlockingCheckIds": _string_list(readiness.get("currentModeBlockingCheckIds")),
        "publicMultiUserBlockingCheckIds": _string_list(readiness.get("publicMultiUserBlockingCheckIds")),
        "checks": [
            _service_info_production_governance_check_projection(check)
            for check in _dict_list(readiness.get("checks"))
        ],
    }


def _service_info_production_governance_check_projection(check: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(check.get("id") or ""),
        "status": str(check.get("status") or ""),
        "reasonCode": str(check.get("reasonCode") or ""),
        "blocksCurrentMode": check.get("blocksCurrentMode") is True,
        "requiredFor": str(check.get("requiredFor") or ""),
        "evidence": _string_list(check.get("evidence")),
    }


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bool_mapping(value: Any) -> dict[str, bool]:
    return {str(key): item is True for key, item in _mapping(value).items()}


def _int_dict(value: Any) -> dict[str, int]:
    return {str(key): _int_value(item) for key, item in _mapping(value).items()}


def _int_value(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]
