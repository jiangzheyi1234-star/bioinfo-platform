from __future__ import annotations

from typing import Any

from .apptainer import ApptainerAdapter
from .base import EnvironmentInspection, EnvironmentLock, ExecutionEnvironmentAdapter
from .conda import CondaAdapter
from .native import NativeAdapter

__all__ = [
    "ApptainerAdapter",
    "CondaAdapter",
    "EnvironmentInspection",
    "EnvironmentLock",
    "ExecutionEnvironmentAdapter",
    "NativeAdapter",
    "build_adapter",
    "list_adapters",
]

_ADAPTER_REGISTRY: dict[str, type] = {
    "native": NativeAdapter,
    "conda": CondaAdapter,
    "apptainer": ApptainerAdapter,
}


def list_adapters() -> list[str]:
    return sorted(_ADAPTER_REGISTRY.keys())


def build_adapter(name: str, **kwargs: Any) -> ExecutionEnvironmentAdapter:
    normalized = str(name or "").strip().lower()
    if normalized not in _ADAPTER_REGISTRY:
        raise ValueError(f"UNKNOWN_ENVIRONMENT_ADAPTER: {name}")
    adapter_cls = _ADAPTER_REGISTRY[normalized]
    return adapter_cls(**kwargs)
