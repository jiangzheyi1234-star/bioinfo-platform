from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.problem_responses import (
    register_status_detail_exception_handlers,
    status_payload_response,
    value_error_response,
)

from .database_errors import DatabaseCandidateConflictError, DatabaseRegistryError
from .errors import (
    IdempotencyKeyReusedError,
    RemoteRunnerAuthError,
    RemoteRunnerNotFoundError,
    RemoteRunnerReadinessError,
    UploadTooLargeError,
    WorkflowDesignRevisionConflictError,
)
from .pipeline import PipelineRegistryError
from .preflight import RunPreflightError
from .tools_errors import ToolRegistryError


def register_exception_handlers(app: FastAPI) -> None:
    register_status_detail_exception_handlers(
        app,
        RemoteRunnerAuthError,
        RemoteRunnerReadinessError,
        RemoteRunnerNotFoundError,
        WorkflowDesignRevisionConflictError,
        IdempotencyKeyReusedError,
        UploadTooLargeError,
        DatabaseRegistryError,
        PipelineRegistryError,
        RunPreflightError,
        ToolRegistryError,
    )

    @app.exception_handler(DatabaseCandidateConflictError)
    async def database_candidate_conflict_handler(
        _request: Request,
        exc: DatabaseCandidateConflictError,
    ) -> JSONResponse:
        return status_payload_response(exc)

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return value_error_response(exc)
