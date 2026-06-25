from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .execution_observability_governance import record_run_failure_locator_read_audit
from .route_utils import authorized_config, data_response, run_sync
from .run_failure_locator_read_model import fetch_run_failure_locator


async def get_run_failure_locator_from_request(run_id: str, authorization: str | None) -> dict[str, Any]:
    cfg = await run_sync(_authorized_failure_locator_read_config, authorization)
    locator = await run_sync(fetch_run_failure_locator, cfg, run_id)
    await run_sync(record_run_failure_locator_read_audit, cfg, run_id, locator)
    return data_response(locator)


def _authorized_failure_locator_read_config(authorization: str | None) -> RemoteRunnerConfig:
    return authorized_config(authorization, action="run.failure_locator.read")
