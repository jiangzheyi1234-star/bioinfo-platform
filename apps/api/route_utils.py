"""Shared helpers for API route modules."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from apps.api.response_cache import cached_response
from apps.api.runtime import get_runtime_service


def runtime_service():
    return get_runtime_service()


async def run_sync(
    func: Callable[[], Any],
    *,
    status_code: int,
    handled_errors: tuple[type[Exception], ...],
):
    try:
        return await asyncio.to_thread(func)
    except handled_errors as exc:
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


async def run_runtime_payload(
    func: Callable[[], Any],
    *,
    status_code: int,
    handled_errors: tuple[type[Exception], ...],
    wrapper: str = "raw",
):
    value = await run_sync(
        func, status_code=status_code, handled_errors=handled_errors
    )
    if wrapper == "raw":
        return value
    if wrapper == "item":
        if isinstance(value, dict) and "item" in value:
            return value
        return {"item": value}
    if wrapper == "data":
        if isinstance(value, dict) and "data" in value:
            return value
        return {"data": value}
    if wrapper == "items":
        if isinstance(value, dict) and "items" in value:
            return value
        return {"items": value}
    if wrapper == "data_items":
        if (
            isinstance(value, dict)
            and isinstance(value.get("data"), dict)
            and "items" in value["data"]
        ):
            return value
        return {"data": {"items": value}}
    raise ValueError(f"Unsupported runtime wrapper: {wrapper}")


async def cached_runtime_payload(
    key: str,
    ttl_seconds: float,
    func: Callable[[], Any],
    *,
    status_code: int,
    handled_errors: tuple[type[Exception], ...],
    wrapper: str = "raw",
    force_refresh: bool = False,
):
    return await cached_response(
        key,
        ttl_seconds,
        lambda: run_runtime_payload(
            func,
            status_code=status_code,
            handled_errors=handled_errors,
            wrapper=wrapper,
        ),
        force_refresh=force_refresh,
    )
