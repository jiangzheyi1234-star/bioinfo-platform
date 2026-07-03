from __future__ import annotations

import json
from types import SimpleNamespace

from core.contracts.problem_details import (
    PROBLEM_DETAIL_MEDIA_TYPE,
    ProblemDetail,
    build_problem_detail,
    normalize_problem_code,
    problem_detail_response,
)
from core.problem_responses import status_payload_response, value_error_response


class _Headers(dict):
    def get(self, key: str, default: str | None = None) -> str | None:
        return super().get(key, default)


class _ConflictError(Exception):
    status_code = 409

    def __init__(self) -> None:
        super().__init__("runner stopped")
        self.payload = {
            "code": "RUNNER_STOPPED",
            "reasonCode": "RUNNER_STOPPED",
            "serverId": "srv_1",
            "nextAction": "START_RUNNER",
        }


def test_problem_detail_builder_uses_rfc9457_top_level_fields() -> None:
    payload = build_problem_detail(
        status=409,
        title="Request blocked",
        detail="runner stopped",
        code="RUNNER_STOPPED",
        request_id="req_1",
        instance="/api/v1/runs",
        extensions={"reasonCode": "RUNNER_STOPPED"},
    )

    assert payload["type"] == "https://h2ometa.dev/problems/runner-stopped"
    assert payload["title"] == "Request blocked"
    assert payload["status"] == 409
    assert payload["detail"] == "runner stopped"
    assert payload["instance"] == "/api/v1/runs"
    assert payload["code"] == "RUNNER_STOPPED"
    assert payload["requestId"] == "req_1"
    assert payload["reasonCode"] == "RUNNER_STOPPED"
    assert ProblemDetail.model_validate(payload).code == "RUNNER_STOPPED"


def test_problem_detail_openapi_response_uses_problem_json_only() -> None:
    response = problem_detail_response(409)

    assert response["description"] == "RFC 9457 Problem Details (409)"
    assert list(response["content"]) == [PROBLEM_DETAIL_MEDIA_TYPE]
    assert response["content"][PROBLEM_DETAIL_MEDIA_TYPE]["schema"] == {"$ref": "#/components/schemas/ProblemDetail"}


def test_problem_code_normalization_rejects_human_detail_strings() -> None:
    assert normalize_problem_code("RUNNER_STOPPED: runner stopped") == "RUNNER_STOPPED"
    assert normalize_problem_code("runner stopped", default="RuntimeServiceError") == "RUNTIMESERVICEERROR"


def test_status_payload_response_returns_problem_details_media_type() -> None:
    request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/runs"), headers=_Headers({"X-Request-Id": "req_1"}))

    response = status_payload_response(_ConflictError(), request=request)
    payload = json.loads(response.body)

    assert response.status_code == 409
    assert response.media_type == PROBLEM_DETAIL_MEDIA_TYPE
    assert response.headers["X-Request-Id"] == "req_1"
    assert payload["type"] == "https://h2ometa.dev/problems/runner-stopped"
    assert payload["code"] == "RUNNER_STOPPED"
    assert payload["requestId"] == "req_1"
    assert payload["reasonCode"] == "RUNNER_STOPPED"
    assert payload["serverId"] == "srv_1"


def test_value_error_response_uses_stable_problem_code_for_message_text() -> None:
    request = SimpleNamespace(url=SimpleNamespace(path="/api/v1/runs"), headers=_Headers({"X-Request-Id": "req_2"}))

    response = value_error_response(ValueError("remote command context missing"), request=request)
    payload = json.loads(response.body)

    assert payload["type"] == "https://h2ometa.dev/problems/valueerror"
    assert payload["code"] == "VALUEERROR"
    assert payload["detail"] == "remote command context missing"
