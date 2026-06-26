from __future__ import annotations

from typing import Any

from .api_models import WorkflowTriggerSchedulerRunOnceRequest
from .config import RemoteRunnerConfig
from .route_utils import authorized_config, run_sync
from .trigger_scheduler_control import run_governed_workflow_trigger_scheduler_once


async def _authorized_config_from_request(
    authorization: str | None,
    *,
    action: str,
) -> RemoteRunnerConfig:
    return await run_sync(authorized_config, authorization, action=action)


async def run_workflow_trigger_scheduler_once_request(
    payload: WorkflowTriggerSchedulerRunOnceRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization, action="workflow_trigger.scheduler.run_once")
    return await run_sync(run_governed_workflow_trigger_scheduler_once, cfg, payload)
