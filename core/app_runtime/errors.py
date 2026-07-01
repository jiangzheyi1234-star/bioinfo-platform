from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


class RuntimeServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class RuntimeConflictError(RuntimeServiceError):
    status_code = 409

    def __init__(self, message: str, *, payload: Any = None):
        super().__init__(message, status_code=self.status_code)
        self.payload = payload


RUNTIME_SERVICE_PROBLEM_DETAIL_KEYS = {
    "reasonCode",
    "nextAction",
    "serverId",
    "blockReasons",
    "activeLeaseCount",
    "allocatedResourceCount",
    "resourceWaitCount",
    "claimedJobCount",
    "runningSlotCount",
}


def runtime_service_detail(error: RuntimeServiceError | str) -> str:
    if isinstance(error, RuntimeServiceError):
        if error.detail is not None:
            return _normalize_detail(error.detail)
        return _remote_http_detail(str(error))
    return _remote_http_detail(str(error))


def runtime_service_problem_extensions(error: RuntimeServiceError | str) -> dict[str, Any]:
    if not isinstance(error, RuntimeServiceError) or not isinstance(error.detail, Mapping):
        return {}
    extensions: dict[str, Any] = {}
    for key in RUNTIME_SERVICE_PROBLEM_DETAIL_KEYS:
        if key not in error.detail:
            continue
        value = _safe_problem_extension_value(error.detail[key])
        if value is not None:
            extensions[key] = value
    return extensions


def runtime_service_status_code(error: RuntimeServiceError | str) -> int:
    detail = runtime_service_detail(error)
    fallback = error.status_code if isinstance(error, RuntimeServiceError) else _remote_http_status_code(str(error))
    if fallback is None:
        fallback = 404 if "not found" in detail.lower() or detail.endswith("_NOT_FOUND") else 400
    return classify_runtime_service_status(detail=detail, fallback=fallback)


def _normalize_detail(detail: Any) -> str:
    if isinstance(detail, str):
        return detail.strip()
    return json.dumps(detail, ensure_ascii=False, separators=(",", ":"))


def _safe_problem_extension_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        safe_items = [str(item).strip() for item in value if str(item).strip()]
        return safe_items or None
    return None


def _remote_http_detail(detail: str) -> str:
    match = re.match(r"^runner http error \d+:\s*(.*)$", detail)
    return match.group(1).strip() if match else detail


def _remote_http_status_code(detail: str) -> int | None:
    match = re.match(r"^runner http error (\d+)(?::|$)", detail)
    return int(match.group(1)) if match else None


def classify_runtime_service_status(*, detail: str, fallback: int) -> int:
    lowered = detail.lower()
    if (
        "workflow_tool_not_ready" in lowered
        or "workflow tool not ready" in lowered
        or "capability_bundle_not_selectable" in lowered
    ):
        return 409
    readiness_markers = (
        "not ready",
        "workflow runtime",
        "snakemake",
        "conda",
        "workflow profile",
        "pipeline registry",
        "canary",
        "prepare the remote workspace",
        "ssh is not connected",
        "ssh disconnected",
    )
    if any(marker in lowered for marker in readiness_markers):
        return 503
    return fallback
