from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from apps.remote_runner.main import app
from apps.remote_runner.webhook_raw_request import WEBHOOK_RAW_BODY_MAX_BYTES


def test_workflow_trigger_inbox_route_passes_exact_raw_body_to_envelope_control(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def capture(trigger_id, envelope, authorization):
        seen["triggerId"] = trigger_id
        seen["authorization"] = authorization
        seen["bodySha256"] = envelope.body_sha256
        seen["rawBody"] = envelope.raw_body
        seen["contentType"] = envelope.content_type
        seen["headerNames"] = envelope.header_names
        return {"data": {"ok": True}}

    monkeypatch.setattr(
        "apps.remote_runner.workflow_trigger_routes.submit_workflow_trigger_inbox_event_envelope_request",
        capture,
    )
    raw_body = b'{\n  "source": "instrument-qc",\n  "eventId": "evt_001"\n}'
    response = TestClient(app).post(
        "/api/v1/workflow-triggers/wtr_raw/inbox",
        headers={"Authorization": "Bearer route-token", "Content-Type": "application/json"},
        content=raw_body,
    )

    assert response.status_code == 202
    assert seen["triggerId"] == "wtr_raw"
    assert seen["authorization"] == "Bearer route-token"
    assert seen["rawBody"] == raw_body
    assert seen["bodySha256"] == hashlib.sha256(raw_body).hexdigest()
    assert seen["contentType"] == "application/json"
    assert "Authorization" in seen["headerNames"]


def test_workflow_trigger_inbox_route_rejects_oversized_raw_body_without_body_leak(monkeypatch) -> None:
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("control service should not receive oversized envelope")

    monkeypatch.setattr(
        "apps.remote_runner.workflow_trigger_routes.submit_workflow_trigger_inbox_event_envelope_request",
        fail_if_called,
    )
    raw_body = b'{"source":"instrument-qc","eventId":"' + (b"a" * WEBHOOK_RAW_BODY_MAX_BYTES) + b'"}'
    response = TestClient(app).post(
        "/api/v1/workflow-triggers/wtr_raw/inbox",
        headers={"Authorization": "Bearer route-token", "Content-Type": "application/json"},
        content=raw_body,
    )
    body = response.text

    assert response.status_code == 400
    assert "WEBHOOK_RAW_REQUEST_BODY_TOO_LARGE" in body
    assert raw_body.decode("utf-8", errors="ignore") not in body


def test_workflow_trigger_inbox_route_rejects_conflicting_signature_headers_without_value_leak(monkeypatch) -> None:
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("control service should not receive conflicting header envelope")

    monkeypatch.setattr(
        "apps.remote_runner.workflow_trigger_routes.submit_workflow_trigger_inbox_event_envelope_request",
        fail_if_called,
    )
    response = TestClient(app).post(
        "/api/v1/workflow-triggers/wtr_raw/inbox",
        headers=[
            ("Authorization", "Bearer route-token"),
            ("X-Hub-Signature-256", "sha256=one"),
            ("x-hub-signature-256", "sha256=two"),
        ],
        content=b'{"source":"instrument-qc","eventId":"evt_001"}',
    )
    body = response.text

    assert response.status_code == 400
    assert "WEBHOOK_RAW_REQUEST_HEADER_CONFLICT" in body
    assert "sha256=one" not in body
    assert "sha256=two" not in body
