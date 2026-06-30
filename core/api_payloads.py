from __future__ import annotations

from typing import Any


def request_payload(
    request: Any | None,
    *,
    by_alias: bool = False,
    exclude_unset: bool = False,
) -> dict[str, Any]:
    if request is None:
        return {}
    runtime_payload = getattr(request, "runtime_payload", None)
    if callable(runtime_payload):
        return request.runtime_payload()
    return request.model_dump(
        by_alias=by_alias,
        exclude_none=True,
        exclude_unset=exclude_unset,
        mode="json",
    )
