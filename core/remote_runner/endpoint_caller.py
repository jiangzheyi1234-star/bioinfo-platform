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
    query_values: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    raw_body: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    endpoint = get_remote_endpoint(endpoint_id)
    path = render_remote_endpoint_path(endpoint_id, path_values, query_values=query_values)
    status_kwargs: dict[str, set[int]] = {"accepted_statuses": set(endpoint.accepted_statuses)}
    if payload is not None and raw_body is not None:
        raise RemoteEndpointContractError("REMOTE_ENDPOINT_BODY_AMBIGUOUS", endpoint_id)
    if extra_headers and raw_body is None:
        raise RemoteEndpointContractError("REMOTE_ENDPOINT_EXTRA_HEADERS_WITHOUT_RAW_BODY", endpoint_id)

    if endpoint.method == "GET":
        if payload or raw_body is not None:
            raise RemoteEndpointContractError("REMOTE_ENDPOINT_GET_PAYLOAD_FORBIDDEN", endpoint_id)
        envelope = client.get_json(path, **status_kwargs)
    elif endpoint.method == "POST":
        if raw_body is not None:
            envelope = client.post_bytes_json(path, raw_body, extra_headers=extra_headers, **status_kwargs)
        else:
            envelope = client.post_json(path, dict(payload or {}), **status_kwargs)
    elif endpoint.method == "PATCH":
        if raw_body is not None:
            raise RemoteEndpointContractError("REMOTE_ENDPOINT_PATCH_RAW_BODY_UNSUPPORTED", endpoint_id)
        envelope = client.patch_json(path, dict(payload or {}), **status_kwargs)
    elif endpoint.method == "DELETE":
        if payload or raw_body is not None:
            raise RemoteEndpointContractError("REMOTE_ENDPOINT_DELETE_PAYLOAD_FORBIDDEN", endpoint_id)
        envelope = client.delete_json(path, **status_kwargs)
    else:
        raise RemoteEndpointContractError("REMOTE_ENDPOINT_METHOD_UNSUPPORTED", endpoint.method)

    if not endpoint.response_key:
        data = envelope
    elif not isinstance(envelope, dict) or endpoint.response_key not in envelope:
        raise RemoteEndpointContractError(
            "REMOTE_ENDPOINT_RESPONSE_KEY_MISSING",
            f"{endpoint_id}.{endpoint.response_key}",
        )
    else:
        data = envelope[endpoint.response_key]
    if not endpoint.response_item_key:
        return data
    if not isinstance(data, dict) or endpoint.response_item_key not in data:
        raise RemoteEndpointContractError(
            "REMOTE_ENDPOINT_RESPONSE_ITEM_KEY_MISSING",
            f"{endpoint_id}.{endpoint.response_item_key}",
        )
    return data[endpoint.response_item_key]
