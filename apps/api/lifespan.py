from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.runtime import get_runtime_service
from core.deployment_mode import require_supported_deployment_mode


@asynccontextmanager
async def lifespan(app: FastAPI):
    require_supported_deployment_mode()
    get_runtime_service()
    try:
        yield
    finally:
        runtime = get_runtime_service()
        runtime.shutdown()
        get_runtime_service.cache_clear()
