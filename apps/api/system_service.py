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
    state_counts = _collect_state_counts()
    readiness_checks = {
        "process": bool(os.getpid()),
        "systemRoutes": True,
        "remoteRunner": state_counts.get("remoteRunnerConnected", False),
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
            "stateCounts": state_counts,
            "securityWarnings": security_warnings,
        }
    }


def _collect_state_counts() -> dict[str, Any]:
    counts: dict[str, Any] = {"localApiProcesses": 1}
    try:
        from apps.api.route_utils import runtime_service

        service = runtime_service()
        ssh_status = service.get_ssh_status()
        counts["remoteRunnerConnected"] = bool(ssh_status.get("connected", False))
        counts["activeSshSessions"] = 1 if ssh_status.get("connected") else 0
    except Exception:
        counts["remoteRunnerConnected"] = False
        counts["activeSshSessions"] = 0
    return counts


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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]
