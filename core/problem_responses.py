from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from core.problem_status import problem_value_error_status_code


def detail_response(status_code: int, detail: Any) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


def status_detail_response(error: Any) -> JSONResponse:
    return detail_response(error.status_code, str(error))


async def _status_detail_exception_handler(_request: Any, error: Any) -> JSONResponse:
    return status_detail_response(error)


def register_status_detail_exception_handlers(app: Any, *error_types: type[BaseException]) -> None:
    for error_type in error_types:
        app.exception_handler(error_type)(_status_detail_exception_handler)


def status_payload_response(error: Any) -> JSONResponse:
    payload = error.payload if error.payload is not None else str(error)
    return detail_response(error.status_code, payload)


def fixed_status_response(error: BaseException, *, status_code: int) -> JSONResponse:
    return detail_response(status_code, str(error))


def register_fixed_status_exception_handlers(
    app: Any,
    status_code: int,
    *error_types: type[BaseException],
) -> None:
    async def fixed_status_exception_handler(_request: Any, error: BaseException) -> JSONResponse:
        return fixed_status_response(error, status_code=status_code)

    for error_type in error_types:
        app.exception_handler(error_type)(fixed_status_exception_handler)


def value_error_response(error: ValueError) -> JSONResponse:
    detail = str(error)
    return detail_response(problem_value_error_status_code(detail), detail)
