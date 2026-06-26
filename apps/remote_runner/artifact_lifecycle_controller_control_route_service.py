from __future__ import annotations

from typing import Any

from .api_models import ArtifactLifecycleControllerRunOnceRequest
from .artifact_lifecycle_controller_control import (
    run_governed_artifact_lifecycle_controller_once,
)
from .config import RemoteRunnerConfig
from .route_utils import authorized_config, run_sync


async def _authorized_config_from_request(
    authorization: str | None,
    *,
    action: str,
) -> RemoteRunnerConfig:
    return await run_sync(authorized_config, authorization, action=action)


async def run_artifact_lifecycle_controller_once_request(
    payload: ArtifactLifecycleControllerRunOnceRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization, action="artifact.lifecycle.controller.run_once")
    return await run_sync(run_governed_artifact_lifecycle_controller_once, cfg, payload)
