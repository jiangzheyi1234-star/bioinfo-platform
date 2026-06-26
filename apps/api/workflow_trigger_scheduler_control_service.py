from __future__ import annotations

from typing import Any

from apps.api.models import WorkflowTriggerSchedulerRunOnceRequest
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import request_payload, run_runtime_payload, runtime_service


async def run_workflow_trigger_scheduler_once_from_request(
    request: WorkflowTriggerSchedulerRunOnceRequest,
    *,
    server_id: str | None,
) -> dict[str, Any]:
    payload = request_payload(request)
    server_id_hint = str(payload.pop("serverId", None) or server_id or "").strip() or None
    result = await run_runtime_payload(
        lambda: runtime_service().run_workflow_trigger_scheduler_once(
            payload,
            server_id=server_id_hint,
        ),
        wrapper="raw",
    )
    await invalidate_response_cache(
        "runs",
        prefixes=(
            "workflow_trigger_events",
            "workflow_trigger_scheduler_ticks",
            "workflow_backfill_launches",
            "workflow_backfill_launch",
        ),
    )
    return result
