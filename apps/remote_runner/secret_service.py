from __future__ import annotations

from typing import Any

from .governance_audit import record_governance_audit_event
from .route_utils import authorized_config, data_response, remote_runner_principal, run_sync
from .secret_provider_readiness import build_secret_provider_readiness


async def get_secret_provider_readiness_request(authorization: str | None) -> dict[str, Any]:
    cfg = await _authorized_config_from_request(authorization, action="secret.provider_readiness.read")
    readiness = await run_sync(build_secret_provider_readiness)
    principal = remote_runner_principal(cfg)
    providers = readiness.get("providers") if isinstance(readiness.get("providers"), list) else []
    configured_count = sum(1 for provider in providers if isinstance(provider, dict) and provider.get("state") == "available")
    await run_sync(
        record_governance_audit_event,
        cfg,
        action="secret.provider_readiness.read",
        actor=principal.actor,
        subject_kind="secret_provider",
        subject_id="readiness",
        decision="allow",
        details={
            "schemaVersion": "provider-readiness-audit.v1",
            "providerCount": len(providers),
            "configuredProviderCount": configured_count,
            "rawReferenceExposure": False,
            "valueExposure": False,
            "individualReferenceProbe": False,
        },
    )
    return data_response(readiness)


async def _authorized_config_from_request(authorization: str | None, *, action: str | None = None):
    return await run_sync(authorized_config, authorization, action=action)
