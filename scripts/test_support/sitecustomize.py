"""Test-only Python startup hooks for Codex Windows runs.

This module is injected by ``scripts/codex_pytest.ps1`` via ``PYTHONPATH`` so
it only affects Codex-managed test runs.
"""

from __future__ import annotations

import inspect
import os
import sys
import types


def _install_asyncio_fallback() -> None:
    if sys.platform != "win32":
        return
    if os.environ.get("CODEX_ASYNCIO_FALLBACK") != "1":
        return
    if "asyncio" in sys.modules:
        return

    asyncio_module = types.ModuleType("asyncio")
    coroutines_module = types.ModuleType("asyncio.coroutines")
    sentinel = object()

    coroutines_module._is_coroutine = sentinel

    def iscoroutinefunction(obj):
        return inspect.iscoroutinefunction(obj) or getattr(obj, "_is_coroutine", None) is sentinel

    asyncio_module.iscoroutinefunction = iscoroutinefunction
    asyncio_module.coroutines = coroutines_module
    asyncio_module.__all__ = ["iscoroutinefunction", "coroutines"]
    asyncio_module.__package__ = "asyncio"
    asyncio_module.__path__ = []  # type: ignore[attr-defined]

    sys.modules["asyncio"] = asyncio_module
    sys.modules["asyncio.coroutines"] = coroutines_module


_install_asyncio_fallback()
