from __future__ import annotations

from core.app_runtime.errors import classify_runtime_service_status


def classify_run_submission_status(*, detail: str, fallback: int) -> int:
    return classify_runtime_service_status(detail=detail, fallback=fallback)
