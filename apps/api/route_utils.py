"""Shared helpers for API route modules."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.api.response_cache import cached_response
from apps.api.runtime import get_runtime_service
from core.async_boundary import run_sync
from core.api_payloads import request_payload
from core.api_responses import wrapped_response


def runtime_service():
    return get_runtime_service()


async def run_runtime_payload(
    func: Callable[[], Any],
    *,
    wrapper: str = "raw",
):
    value = await run_sync(func)
    return wrapped_response(value, wrapper=wrapper)


async def cached_runtime_payload(
    key: str,
    ttl_seconds: float,
    func: Callable[[], Any],
    *,
    wrapper: str = "raw",
    force_refresh: bool = False,
):
    return await cached_response(
        key,
        ttl_seconds,
        lambda: run_runtime_payload(
            func,
            wrapper=wrapper,
        ),
        force_refresh=force_refresh,
    )
