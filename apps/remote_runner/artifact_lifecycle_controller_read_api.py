from __future__ import annotations

from typing import Any

from .artifact_lifecycle_controller_read_model import list_governed_artifact_lifecycle_controller_ticks
from .route_utils import authorized_config, data_response, run_sync


async def list_artifact_lifecycle_controller_ticks_from_request(
    limit: int,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await run_sync(_authorized_controller_tick_read_config, authorization)
    ticks = await run_sync(list_governed_artifact_lifecycle_controller_ticks, cfg, limit=limit)
    return data_response(ticks)


def _authorized_controller_tick_read_config(authorization: str | None):
    return authorized_config(authorization, action="artifact.lifecycle.controller_ticks.read")
