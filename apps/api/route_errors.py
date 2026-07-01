from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from apps.api.problem_details import build_problem_detail, ensure_request_id
from apps.api.workflow_first_run_service import WorkflowFirstRunValidationCardUnavailableError
from apps.api.workflow_sample_data_service import (
    WorkflowSampleDataIntegrityError,
    WorkflowSampleDataSourceError,
    WorkflowSampleDataUnavailableError,
)
from core.app_runtime.errors import (
    RuntimeConflictError,
    RuntimeServiceError,
    runtime_service_detail,
    runtime_service_problem_extensions,
    runtime_service_status_code,
)
from core.problem_responses import (
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
                extensions=runtime_service_problem_extensions(exc),
            ),
            headers={"X-Request-Id": request_id},
        )

    @app.exception_handler(WorkflowSampleDataUnavailableError)
    async def workflow_sample_data_unavailable_handler(
        request: Request,
        exc: WorkflowSampleDataUnavailableError,
    ) -> JSONResponse:
        return workflow_sample_data_problem_response(
            request,
            exc,
            code="WORKFLOW_SAMPLE_DATA_UNSUPPORTED",
            title="Workflow sample data is unsupported",
        )

    @app.exception_handler(WorkflowSampleDataIntegrityError)
    async def workflow_sample_data_integrity_handler(
        request: Request,
        exc: WorkflowSampleDataIntegrityError,
    ) -> JSONResponse:
        return workflow_sample_data_problem_response(
            request,
            exc,
            code="WORKFLOW_SAMPLE_DATA_INTEGRITY_MISMATCH",
            title="Workflow sample data integrity check failed",
        )

    @app.exception_handler(WorkflowSampleDataSourceError)
    async def workflow_sample_data_source_handler(
        request: Request,
        exc: WorkflowSampleDataSourceError,
    ) -> JSONResponse:
        return workflow_sample_data_problem_response(
            request,
            exc,
            code="WORKFLOW_SAMPLE_DATA_SOURCE_UNAVAILABLE",
            title="Workflow sample data source is unavailable",
        )

    @app.exception_handler(WorkflowFirstRunValidationCardUnavailableError)
    async def workflow_first_run_validation_card_unavailable_handler(
        _request: Request,
        exc: WorkflowFirstRunValidationCardUnavailableError,
    ) -> JSONResponse:
        return status_detail_response(exc)

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return value_error_response(exc)

    register_fixed_status_exception_handlers(app, 400, TypeError, KeyError)
    register_fixed_status_exception_handlers(app, 502, OSError, TimeoutError)


def workflow_sample_data_problem_response(
    request: Request,
    exc: WorkflowSampleDataUnavailableError | WorkflowSampleDataIntegrityError | WorkflowSampleDataSourceError,
    *,
    code: str,
    title: str,
) -> JSONResponse:
    request_id = ensure_request_id(request.headers.get("X-Request-Id"))
    status = exc.status_code
    return JSONResponse(
        status_code=status,
        content=build_problem_detail(
            status=status,
            title=title,
            detail=str(exc),
            code=code,
            request_id=request_id,
            instance=request.url.path,
        ),
        headers={"X-Request-Id": request_id},
    )
