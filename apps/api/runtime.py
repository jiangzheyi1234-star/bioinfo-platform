"""Runtime singleton for API process."""

from __future__ import annotations

from functools import lru_cache

from core.app_runtime.service import RuntimeService


@lru_cache(maxsize=1)
def get_runtime_service() -> RuntimeService:
    runtime = RuntimeService()
    runtime.initialize()
    return runtime
