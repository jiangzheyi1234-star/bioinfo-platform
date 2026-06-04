from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from apps.api.problem_details import build_problem_detail, ensure_request_id
from apps.api.workflow_sample_data_service import WorkflowSampleDataUnavailableError
from core.app_runtime.errors import (
    RuntimeConflictError,
    RuntimeServiceError,
    runtime_service_detail,
    runtime_service_status_code,
)
from core.problem_responses import (
    detail_response,
    register_fixed_status_exception_handlers,
    status_detail_response,
    status_payload_response,
    value_error_response,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RuntimeConflictError)
    async def runtime_conflict_error_handler(_request: Request, exc: RuntimeConflictError) -> JSONResponse:
        return status_payload_response(exc)

    @app.exception_handler(RuntimeServiceError)
    async def runtime_service_error_handler(request: Request, exc: RuntimeServiceError) -> JSONResponse:
        status = runtime_service_status_code(exc)
        request_id = ensure_request_id(request.headers.get("X-Request-Id"))
        normalized_detail = runtime_service_detail(exc)
        return JSONResponse(
            status_code=status,
            content=build_problem_detail(
                status=status,
                title="Runtime service error",
                detail=normalized_detail,
                code="RUNNER_NOT_READY" if status >= 500 else "RUNTIME_SERVICE_ERROR",
                request_id=request_id,
                instance=request.url.path,
            ),
            headers={"X-Request-Id": request_id},
        )

    @app.exception_handler(WorkflowSampleDataUnavailableError)
    async def workflow_sample_data_unavailable_handler(
        _request: Request,
        exc: WorkflowSampleDataUnavailableError,
    ) -> JSONResponse:
        return status_detail_response(exc)

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return value_error_response(exc)

    register_fixed_status_exception_handlers(app, 400, TypeError, KeyError)
    register_fixed_status_exception_handlers(app, 502, OSError, TimeoutError)
