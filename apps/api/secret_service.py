from __future__ import annotations

from typing import Any

from apps.api.route_utils import run_runtime_payload, runtime_service


async def get_secret_provider_readiness_from_request(*, server_id: str | None) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().get_secret_provider_readiness(server_id=server_id),
        wrapper="raw",
    )
