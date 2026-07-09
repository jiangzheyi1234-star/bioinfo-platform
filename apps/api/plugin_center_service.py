from __future__ import annotations

from typing import Any

from apps.api.route_utils import run_runtime_payload, runtime_service


async def list_plugin_center_extensions_from_request() -> dict[str, Any]:
    return await run_runtime_payload(
        runtime_service().list_managed_extensions,
        wrapper="raw",
    )
