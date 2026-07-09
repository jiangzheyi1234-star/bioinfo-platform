from __future__ import annotations

from typing import Any

from apps.api.models import ManagedExtensionActionRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import request_payload, run_runtime_payload, runtime_service


PLUGIN_CENTER_ACTION_CACHE_PREFIXES = (
    "ssh_",
    "servers",
    "workflow_",
    "pipelines",
    "tools",
    "databases",
    "runs",
)


async def list_plugin_center_extensions_from_request() -> dict[str, Any]:
    return await run_runtime_payload(
        runtime_service().list_managed_extensions,
        wrapper="raw",
    )


async def execute_plugin_center_extension_action_from_request(
    extension_id: str,
    request: ManagedExtensionActionRequest,
) -> dict[str, Any]:
    payload = request_payload(request)
    try:
        return await run_runtime_payload(
            lambda: runtime_service().execute_managed_extension_action(extension_id, payload),
            wrapper="raw",
        )
    finally:
        await invalidate_response_cache(prefixes=PLUGIN_CENTER_ACTION_CACHE_PREFIXES)
