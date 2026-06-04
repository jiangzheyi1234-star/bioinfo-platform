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
