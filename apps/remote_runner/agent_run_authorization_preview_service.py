"""Read-only authorization preview for one Agent-owned workflow run."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .agent_run_authorization_authority import (
    prepare_agent_run_authorization_authority,
)
from .config import RemoteRunnerConfig
from .route_utils import (
    authorized_config,
    data_response,
    remote_runner_principal,
    run_sync,
)


def build_agent_run_authorization_preview(
    cfg: RemoteRunnerConfig,
    session_id: str,
    *,
    actor: str,
) -> dict[str, Any]:
    """Return the shared authority builder's strict public projection."""

    prepared = prepare_agent_run_authorization_authority(
        cfg,
        session_id,
        actor=actor,
    )
    return deepcopy(prepared.preview)


async def get_agent_run_authorization_preview_from_http(
    session_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    """Authorize the remote principal and return the strict public projection."""

    cfg = authorized_config(
        authorization,
        action="agent_session.run_authorization_preview.read",
    )
    principal = remote_runner_principal(cfg)
    preview = await run_sync(
        build_agent_run_authorization_preview,
        cfg,
        session_id,
        actor=principal.actor,
    )
    return data_response(preview)


__all__ = [
    "build_agent_run_authorization_preview",
    "get_agent_run_authorization_preview_from_http",
]
