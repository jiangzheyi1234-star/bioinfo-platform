from __future__ import annotations

import re
import uuid
from typing import Any


PROBLEM_DETAIL_MEDIA_TYPE = "application/problem+json"
PROBLEM_TYPE_BASE_URI = "https://h2ometa.dev/problems"


def ensure_request_id(value: str | None = None) -> str:
    candidate = str(value or "").strip()
    return candidate or f"req_{uuid.uuid4().hex[:8]}"


def problem_type_uri(code: str) -> str:
    normalized = normalize_problem_code(code).lower().replace("_", "-")
    return f"{PROBLEM_TYPE_BASE_URI}/{normalized}"


def normalize_problem_code(value: Any, *, default: str = "H2OMETA_ERROR") -> str:
    def normalize_token(token: str) -> str:
        return token.upper().replace("-", "_").replace(".", "_")

    candidate = str(value or "").strip()
    fallback = normalize_token(str(default or "H2OMETA_ERROR").strip() or "H2OMETA_ERROR")
    if not candidate:
        return fallback
    token = candidate.split(":", 1)[0].strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", token):
        return fallback
    return normalize_token(token)


def build_problem_detail(
    *,
    status: int,
    title: str,
    detail: str,
    code: str,
    request_id: str,
    instance: str,
    errors: list[dict[str, Any]] | None = None,
    extensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_code = normalize_problem_code(code)
    payload: dict[str, Any] = {
        "type": problem_type_uri(normalized_code),
        "title": str(title or "Request failed"),
        "status": int(status),
        "detail": str(detail or normalized_code),
        "instance": str(instance or ""),
        "code": normalized_code,
        "requestId": ensure_request_id(request_id),
    }
    if errors:
        payload["errors"] = errors
    if extensions:
        for key, value in extensions.items():
            if key not in payload:
                payload[key] = value
    return payload


def problem_extensions_from_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): value
        for key, value in payload.items()
        if str(key) not in {"type", "title", "status", "detail", "instance", "requestId"}
    }
