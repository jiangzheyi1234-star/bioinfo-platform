from __future__ import annotations

from typing import Any

from core.contracts.remote_endpoints import (
    RemoteEndpointContractError,
    get_remote_endpoint,
    render_remote_endpoint_path,
)


def call_remote_endpoint(
    client: Any,
    endpoint_id: str,
    *,
    path_values: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> Any:
    endpoint = get_remote_endpoint(endpoint_id)
    path = render_remote_endpoint_path(endpoint_id, path_values)

    if endpoint.method == "GET":
        if payload:
            raise RemoteEndpointContractError("REMOTE_ENDPOINT_GET_PAYLOAD_FORBIDDEN", endpoint_id)
        envelope = client.get_json(path)
    elif endpoint.method == "POST":
        envelope = client.post_json(path, dict(payload or {}))
    elif endpoint.method == "PATCH":
        envelope = client.patch_json(path, dict(payload or {}))
    elif endpoint.method == "DELETE":
        if payload:
            raise RemoteEndpointContractError("REMOTE_ENDPOINT_DELETE_PAYLOAD_FORBIDDEN", endpoint_id)
        envelope = client.delete_json(path)
    else:
        raise RemoteEndpointContractError("REMOTE_ENDPOINT_METHOD_UNSUPPORTED", endpoint.method)

    if not endpoint.response_key:
        return envelope
    if not isinstance(envelope, dict) or endpoint.response_key not in envelope:
        raise RemoteEndpointContractError(
            "REMOTE_ENDPOINT_RESPONSE_KEY_MISSING",
            f"{endpoint_id}.{endpoint.response_key}",
        )
    return envelope[endpoint.response_key]
