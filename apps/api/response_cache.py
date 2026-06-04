"""Small in-process response cache for slow local API reads."""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


_cache: dict[str, _CacheEntry] = {}
_in_flight: dict[str, asyncio.Task[Any]] = {}
_lock = asyncio.Lock()


async def cached_response(
    key: str,
    ttl_seconds: float,
    loader: Callable[[], Awaitable[Any]],
    *,
    force_refresh: bool = False,
) -> Any:
    now = time.monotonic()
    async with _lock:
        entry = _cache.get(key)
        if not force_refresh and entry and entry.expires_at > now:
            return copy.deepcopy(entry.value)
        if not force_refresh and key in _in_flight:
            task = _in_flight[key]
        else:
            task = asyncio.create_task(loader())
            _in_flight[key] = task

    succeeded = False
    try:
        value = await task
        succeeded = True
    finally:
        if not succeeded:
            async with _lock:
                if _in_flight.get(key) is task:
                    _in_flight.pop(key, None)

    async with _lock:
        if _in_flight.get(key) is task:
            _cache[key] = _CacheEntry(copy.deepcopy(value), time.monotonic() + ttl_seconds)
            _in_flight.pop(key, None)
    return copy.deepcopy(value)


async def invalidate_response_cache(*keys: str, prefixes: tuple[str, ...] = ()) -> None:
    async with _lock:
        for key in keys:
            _cache.pop(key, None)
            _in_flight.pop(key, None)
        if prefixes:
            for key in list(_cache.keys()):
                if key.startswith(prefixes):
                    _cache.pop(key, None)
            for key in list(_in_flight.keys()):
                if key.startswith(prefixes):
                    _in_flight.pop(key, None)
