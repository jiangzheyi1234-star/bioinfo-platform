from __future__ import annotations

from typing import Any

from apps.api.models import WorkflowTriggerReadinessWatcherRunOnceRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import request_payload, run_runtime_payload, runtime_service


async def run_workflow_trigger_readiness_watcher_once_from_request(
    request: WorkflowTriggerReadinessWatcherRunOnceRequest,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id_hint = str(payload.pop("serverId", None) or server_id or "").strip() or None
    result = await run_runtime_payload(
        lambda: runtime_service().run_workflow_trigger_readiness_watcher_once(
            payload,
            server_id=server_id_hint,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache(
        "runs",
        prefixes=(
            "workflow_trigger_events",
            "workflow_trigger_readiness_observation",
        ),
    )
    return result
