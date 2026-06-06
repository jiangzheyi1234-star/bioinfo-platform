"""System metadata service helpers for the local API."""

from __future__ import annotations

import os
from typing import Any


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
            "readiness": {
                "status": "ready",
                "checks": {
                    "process": bool(os.getpid()),
                    "systemRoutes": True,
                },
            },
            "stateCounts": {"localApiProcesses": 1},
        }
    }
