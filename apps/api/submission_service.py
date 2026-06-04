from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apps.api.models import RunSubmitRequest, UploadSubmitRequest
from apps.api.problem_details import ensure_request_id
from apps.api.response_cache import invalidate_response_cache
from apps.api.route_utils import request_payload, run_runtime_payload, runtime_service


@dataclass(frozen=True)
class RunSubmission:
    payload: dict[str, Any]
    headers: dict[str, str]


class ResponseWithHeaders(Protocol):
    headers: Any


async def upload_file_from_request(request: UploadSubmitRequest) -> dict[str, Any]:
    return await run_runtime_payload(
        lambda: runtime_service().upload_file(request_payload(request)),
        wrapper="data",
    )


async def submit_run_from_request(request: RunSubmitRequest) -> RunSubmission:
    request_id = ensure_request_id(request.requestId)
    result = await run_runtime_payload(
        lambda: runtime_service().submit_run(
            request_payload(request) | {"requestId": request_id}
        ),
        wrapper="raw",
    )
    await invalidate_response_cache("runs")
    return RunSubmission(
        payload=result,
        headers={
            "Location": result["location"],
            "Retry-After": str(result["retryAfter"]),
            "X-Request-Id": str(result["requestId"]),
        },
    )


async def submit_run_response_from_request(request: RunSubmitRequest, response: ResponseWithHeaders) -> dict[str, Any]:
    submission = await submit_run_from_request(request)
    response.headers.update(submission.headers)
    return submission.payload
