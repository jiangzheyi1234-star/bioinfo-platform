"""Process-lifetime binding for one fully preflighted runner config."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import asdict
import os
from typing import Any

from core.contracts.runner_protocol_runtime import (
    require_current_runner_protocol_expectation,
)

from .runner_protocol_startup import require_explicit_runner_protocol_config_payload


_PROCESS_BOUND_REMOTE_RUNNER_CONFIG: Any | None = None
_PROCESS_BOUND_REMOTE_RUNNER_STARTUP_BINDING: dict[str, str] | None = None
_STARTUP_BINDING_FIELDS = frozenset(
    {
        "artifactArchiveSha256Path",
        "bootstrapManifestFingerprint",
        "configPath",
        "declaredArtifactArchiveSha256",
        "effectiveConfigFingerprint",
        "manifestPath",
        "packagePath",
        "persistedConfigFingerprint",
        "protocolFingerprint",
        "protocolVersion",
        "runnerPythonPath",
    }
)


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


def get_process_bound_remote_runner_startup_binding() -> dict[str, str] | None:
    if _PROCESS_BOUND_REMOTE_RUNNER_STARTUP_BINDING is None:
        return None
    return copy.deepcopy(_PROCESS_BOUND_REMOTE_RUNNER_STARTUP_BINDING)


def bind_remote_runner_startup_binding(binding: Mapping[str, object]) -> None:
    """Bind the exact release evidence verified before runtime imports."""

    if not isinstance(binding, Mapping) or frozenset(binding) != _STARTUP_BINDING_FIELDS:
        raise RuntimeError("REMOTE_RUNNER_STARTUP_BINDING_INVALID")
    normalized: dict[str, str] = {}
    for field in sorted(_STARTUP_BINDING_FIELDS):
        value = binding.get(field)
        if not isinstance(value, str) or not value or value != value.strip():
            raise RuntimeError(f"REMOTE_RUNNER_STARTUP_BINDING_INVALID: {field}")
        normalized[field] = value
    global _PROCESS_BOUND_REMOTE_RUNNER_STARTUP_BINDING
    existing = _PROCESS_BOUND_REMOTE_RUNNER_STARTUP_BINDING
    if existing is not None and existing != normalized:
        raise RuntimeError("REMOTE_RUNNER_STARTUP_BINDING_ALREADY_BOUND")
    _PROCESS_BOUND_REMOTE_RUNNER_STARTUP_BINDING = copy.deepcopy(normalized)


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
    "bind_remote_runner_startup_binding",
    "get_process_bound_remote_runner_config",
    "get_process_bound_remote_runner_startup_binding",
    "require_explicit_loaded_runner_protocol",
]
