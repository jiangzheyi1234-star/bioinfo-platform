from __future__ import annotations

import pytest

from core.contracts.command_context import remote_command_context_from_payload, strip_local_control_context


def test_remote_command_context_moves_control_fields_to_headers() -> None:
    context, body = remote_command_context_from_payload(
        {
            "serverId": "srv_1",
            "requestId": "req_1",
            "actor": "operator",
            "runSpec": {"pipelineId": "taxonomy-v1"},
        }
    )

    assert context.server_id == "srv_1"
    assert context.request_id == "req_1"
    assert context.actor == "operator"
    assert context.headers == {
        "X-Request-Id": "req_1",
        "X-H2OMeta-Server-Id": "srv_1",
        "X-H2OMeta-Actor": "operator",
    }
    assert body == {"runSpec": {"pipelineId": "taxonomy-v1"}}


def test_remote_command_context_requires_server_id() -> None:
    with pytest.raises(ValueError, match="REMOTE_COMMAND_CONTEXT_SERVER_ID_REQUIRED"):
        remote_command_context_from_payload({"requestId": "req_1", "runSpec": {"pipelineId": "taxonomy-v1"}})


def test_remote_command_context_generates_request_id_when_missing() -> None:
    context, body = remote_command_context_from_payload(
        {"serverId": "srv_1", "runSpec": {"pipelineId": "taxonomy-v1"}}
    )

    assert context.request_id.startswith("req_")
    assert context.headers["X-H2OMeta-Server-Id"] == "srv_1"
    assert body == {"runSpec": {"pipelineId": "taxonomy-v1"}}


def test_strip_local_control_context_removes_only_transport_fields() -> None:
    payload = {
        "serverId": "srv_1",
        "requestId": "req_1",
        "actor": "operator",
        "reason": "manual retry",
        "scope": "run",
    }

    assert strip_local_control_context(payload) == {"reason": "manual retry", "scope": "run"}
