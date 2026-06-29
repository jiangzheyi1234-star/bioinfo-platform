from __future__ import annotations

from typing import Any

from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, RUN_CREATE, UPLOAD_CREATE, render_remote_endpoint_path
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


SUBMISSION_ENDPOINTS = (UPLOAD_CREATE, RUN_CREATE)


def test_submission_endpoints_are_contract_rendered() -> None:
    assert render_remote_endpoint_path(UPLOAD_CREATE, {}) == "/api/v1/uploads"
    assert render_remote_endpoint_path(RUN_CREATE, {}) == "/api/v1/runs"

    upload = REMOTE_ENDPOINTS[UPLOAD_CREATE]
    run = REMOTE_ENDPOINTS[RUN_CREATE]
    assert upload.method == "POST"
    assert upload.response_key == "data"
    assert upload.cache_scope == "upload-command"
    assert upload.accepted_statuses == (200,)
    assert run.method == "POST"
    assert run.response_key == ""
    assert run.cache_scope == "run-command"
    assert run.accepted_statuses == (202,)


def test_submission_endpoint_contracts_match_openapi_operation_ids_and_statuses() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in SUBMISSION_ENDPOINTS:
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id
            for status in endpoint.accepted_statuses:
                assert str(status) in operation["responses"]


def test_submission_endpoint_caller_preserves_upload_unwrap_and_run_envelope() -> None:
    client = FakeSubmissionClient()

    upload = call_remote_endpoint(
        client,
        UPLOAD_CREATE,
        path_values={},
        payload={"filename": "reads.fastq", "contentBase64": "QEdPQgo=", "mimeType": "text/plain"},
    )
    run = call_remote_endpoint(
        client,
        RUN_CREATE,
        path_values={},
        payload={"serverId": "srv_1", "requestId": "req_1", "runSpec": {"pipelineId": "taxonomy-v1"}},
        extra_headers={"Idempotency-Key": "idem_1", "X-Request-Id": "req_1"},
    )

    assert upload == {"uploadId": "upl_1", "sha256": "abc123"}
    assert run == {
        "data": {"runId": "run_1", "status": "queued", "requestId": "req_1"},
        "location": "/api/v1/runs/run_1",
        "retryAfter": 2,
        "requestId": "req_1",
    }
    assert client.calls == [
        (
            "/api/v1/uploads",
            {"filename": "reads.fastq", "contentBase64": "QEdPQgo=", "mimeType": "text/plain"},
            [200],
            {},
        ),
        (
            "/api/v1/runs",
            {"serverId": "srv_1", "requestId": "req_1", "runSpec": {"pipelineId": "taxonomy-v1"}},
            [202],
            {"Idempotency-Key": "idem_1", "X-Request-Id": "req_1"},
        ),
    ]


def test_submission_proxy_generic_endpoint_call_uses_registry() -> None:
    proxy = FakeProxy()

    upload = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            UPLOAD_CREATE,
            payload={"filename": "reads.fastq", "contentBase64": "QEdPQgo=", "mimeType": "text/plain"},
        )
    )
    run = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            RUN_CREATE,
            payload={"serverId": "srv_1", "requestId": "req_1", "runSpec": {"pipelineId": "taxonomy-v1"}},
            extra_headers={"Idempotency-Key": "idem_1", "X-Request-Id": "req_1"},
        )
    )

    assert upload == {"uploadId": "upl_1", "sha256": "abc123"}
    assert run["location"] == "/api/v1/runs/run_1"
    assert proxy.client.calls[0][0] == "/api/v1/uploads"
    assert proxy.client.calls[1][0] == "/api/v1/runs"


def test_submission_methods_do_not_reappear_on_transport_or_proxy() -> None:
    for method_name in ("create_upload", "create_run"):
        assert not hasattr(RemoteRunnerHttpClient, method_name)
    for method_name in ("upload_content", "submit_run"):
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


def _endpoint_kwargs(
    endpoint_id: str,
    *,
    payload: dict[str, object],
    extra_headers: dict[str, str] | None = None,
) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"serverId": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": {},
        "query_values": {},
        "payload": dict(payload),
    }
    if extra_headers is not None:
        kwargs["extra_headers"] = dict(extra_headers)
    return kwargs


class FakeSubmissionClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], list[int], dict[str, str]]] = []

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        accepted_statuses: set[int] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((path, dict(payload), sorted(accepted_statuses or []), dict(extra_headers or {})))
        if path == "/api/v1/uploads":
            return {"data": {"uploadId": "upl_1", "sha256": "abc123"}}
        return {
            "data": {"runId": "run_1", "status": "queued", "requestId": "req_1"},
            "location": "/api/v1/runs/run_1",
            "retryAfter": 2,
            "requestId": "req_1",
        }


class FakeProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = FakeSubmissionClient()

    def _get_client(self, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        return self.client
