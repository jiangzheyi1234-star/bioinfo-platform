from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException


def ensure_request_id(value: str | None = None) -> str:
    candidate = (value or "").strip()
    return candidate or f"req_{uuid.uuid4().hex[:8]}"


def build_problem_detail(
    *,
    status: int,
    title: str,
    detail: str,
    code: str,
    request_id: str,
    instance: str,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": f"https://h2ometa.dev/problems/{code.lower().replace('_', '-')}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
        "code": code,
        "requestId": request_id,
    }
    if errors:
        payload["errors"] = errors
    return payload


def problem_http_exception(
    *,
    status: int,
    title: str,
    detail: str,
    code: str,
    request_id: str,
    instance: str,
    errors: list[dict[str, Any]] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail=build_problem_detail(
            status=status,
            title=title,
            detail=detail,
            code=code,
            request_id=request_id,
            instance=instance,
            errors=errors,
        ),
        headers={"X-Request-Id": request_id},
    )
