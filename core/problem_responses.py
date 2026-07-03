from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from core.contracts.problem_details import (
    PROBLEM_DETAIL_MEDIA_TYPE,
    build_problem_detail,
    ensure_request_id,
    normalize_problem_code,
    problem_extensions_from_payload,
)
from core.problem_status import problem_value_error_status_code


def _request_path(request: Any) -> str:
    url = getattr(request, "url", None)
    path = getattr(url, "path", "")
    return str(path or "")


def _request_id(request: Any) -> str:
    headers = getattr(request, "headers", {}) or {}
    getter = getattr(headers, "get", None)
    value = getter("X-Request-Id") if callable(getter) else None
    return ensure_request_id(value)


def _response(
    *,
    status_code: int,
    title: str,
    detail: str,
    code: str,
    request: Any = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content=build_problem_detail(
            status=status_code,
            title=title,
            detail=detail,
            code=code,
            request_id=request_id,
            instance=_request_path(request),
            extensions=extensions,
        ),
        headers={"X-Request-Id": request_id},
        media_type=PROBLEM_DETAIL_MEDIA_TYPE,
    )


def detail_response(status_code: int, detail: Any, *, request: Any = None, code: str = "HTTP_ERROR") -> JSONResponse:
    return _response(
        status_code=status_code,
        title="Request failed",
        detail=str(detail),
        code=code,
        request=request,
    )


def status_detail_response(error: Any, *, request: Any = None) -> JSONResponse:
    detail = str(error)
    return detail_response(
        error.status_code,
        detail,
        request=request,
        code=normalize_problem_code(detail, default=type(error).__name__),
    )


async def _status_detail_exception_handler(request: Any, error: Any) -> JSONResponse:
    return status_detail_response(error, request=request)


def register_status_detail_exception_handlers(app: Any, *error_types: type[BaseException]) -> None:
    for error_type in error_types:
        app.exception_handler(error_type)(_status_detail_exception_handler)


def status_payload_response(error: Any, *, request: Any = None) -> JSONResponse:
    payload = error.payload if error.payload is not None else str(error)
    detail = str(error)
    extensions = problem_extensions_from_payload(payload)
    code = normalize_problem_code(extensions.get("code") or detail, default=type(error).__name__)
    return _response(
        status_code=error.status_code,
        title="Request blocked" if int(error.status_code) == 409 else "Request failed",
        detail=detail,
        code=code,
        request=request,
        extensions=extensions,
    )


def fixed_status_response(error: BaseException, *, status_code: int, request: Any = None) -> JSONResponse:
    return detail_response(
        status_code,
        str(error),
        request=request,
        code=normalize_problem_code(str(error), default=type(error).__name__),
    )


def register_fixed_status_exception_handlers(
    app: Any,
    status_code: int,
    *error_types: type[BaseException],
) -> None:
    async def fixed_status_exception_handler(request: Any, error: BaseException) -> JSONResponse:
        return fixed_status_response(error, status_code=status_code, request=request)

    for error_type in error_types:
        app.exception_handler(error_type)(fixed_status_exception_handler)


def value_error_response(error: ValueError, *, request: Any = None) -> JSONResponse:
    detail = str(error)
    return detail_response(
        problem_value_error_status_code(detail),
        detail,
        request=request,
        code=normalize_problem_code(detail, default=type(error).__name__),
    )
