from __future__ import annotations

from typing import Any

from apps.api.models import ToolProductionEvidenceRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import request_payload, run_runtime_payload, runtime_service


async def mark_tool_production_from_request(
    tool_id: str,
    request: ToolProductionEvidenceRequest,
) -> dict[str, Any]:
    result = await run_runtime_payload(
        lambda: runtime_service().mark_tool_production_enabled(
            tool_id,
            request_payload(request),
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("tools", "workflow_catalog")
    return result
