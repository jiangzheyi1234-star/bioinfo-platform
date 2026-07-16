"""Process-lifetime binding for one fully preflighted runner config."""

from __future__ import annotations

import copy
from dataclasses import asdict
import os
from typing import Any

from core.contracts.runner_protocol_runtime import (
    require_current_runner_protocol_expectation,
)

from .runner_protocol_startup import require_explicit_runner_protocol_config_payload


_PROCESS_BOUND_REMOTE_RUNNER_CONFIG: Any | None = None


def get_process_bound_remote_runner_config() -> Any | None:
    if _PROCESS_BOUND_REMOTE_RUNNER_CONFIG is None:
        return None
    return copy.copy(_PROCESS_BOUND_REMOTE_RUNNER_CONFIG)


def bind_remote_runner_config_snapshot(cfg: Any) -> None:
    """Keep one fully preflighted config snapshot for the process lifetime."""

    require_explicit_loaded_runner_protocol(cfg)
    global _PROCESS_BOUND_REMOTE_RUNNER_CONFIG
    existing = _PROCESS_BOUND_REMOTE_RUNNER_CONFIG
    if existing is not None and asdict(existing) != asdict(cfg):
        raise RuntimeError("REMOTE_RUNNER_CONFIG_SNAPSHOT_ALREADY_BOUND")
    _PROCESS_BOUND_REMOTE_RUNNER_CONFIG = copy.copy(cfg)


def require_explicit_loaded_runner_protocol(cfg: Any) -> None:
    if (
        str(os.environ.get("H2OMETA_REMOTE_CONFIG", "") or "").strip()
        and not bool(getattr(cfg, "_runner_protocol_expectation_explicit", False))
    ):
        require_explicit_runner_protocol_config_payload({})
    require_current_runner_protocol_expectation(
        cfg.runner_protocol_version,
        cfg.runner_protocol_fingerprint,
    )


__all__ = [
    "bind_remote_runner_config_snapshot",
    "get_process_bound_remote_runner_config",
    "require_explicit_loaded_runner_protocol",
]
