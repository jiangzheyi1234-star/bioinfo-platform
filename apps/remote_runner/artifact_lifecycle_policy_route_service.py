from __future__ import annotations

from typing import Any

from .api_models import ArtifactLifecyclePolicySetRequest
from .artifact_lifecycle_policy import (
    get_governed_artifact_lifecycle_policy,
    set_governed_artifact_lifecycle_policy,
)
from .route_utils import authorized_config, data_response, run_sync


async def get_artifact_lifecycle_policy_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = await run_sync(_authorized_policy_read_config, authorization)
    policy = await run_sync(get_governed_artifact_lifecycle_policy, cfg)
    return data_response(policy)


async def set_artifact_lifecycle_policy_from_request(
    payload: ArtifactLifecyclePolicySetRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await run_sync(_authorized_policy_set_config, authorization)
    policy = await run_sync(set_governed_artifact_lifecycle_policy, cfg, payload.model_dump(mode="json"))
    return data_response(policy)


def _authorized_policy_read_config(authorization: str | None):
    return authorized_config(authorization, action="artifact.lifecycle.policy.read")


def _authorized_policy_set_config(authorization: str | None):
    return authorized_config(authorization, action="artifact.lifecycle.policy.set")
