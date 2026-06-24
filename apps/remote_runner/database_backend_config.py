from __future__ import annotations

import os
from typing import Any

DATABASE_BACKEND_UNSUPPORTED_ERROR = "REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED"
DATABASE_URL_UNSUPPORTED_ERROR = "REMOTE_RUNNER_DATABASE_URL_UNSUPPORTED"
SUPPORTED_DATABASE_BACKENDS = {"sqlite"}

DATABASE_BACKEND_ENV_NAMES = (
    "H2OMETA_REMOTE_RUNNER_DATABASE_BACKEND",
    "H2OMETA_DATABASE_BACKEND",
)
DATABASE_URL_ENV_NAMES = (
    "H2OMETA_REMOTE_RUNNER_DATABASE_URL",
    "H2OMETA_DATABASE_URL",
)


def apply_database_backend_env_overrides(cfg: Any) -> None:
    _reject_unsupported_backend_signals(
        [getattr(cfg, "database_backend", "")],
        code=DATABASE_BACKEND_UNSUPPORTED_ERROR,
    )
    _reject_database_url_signals([getattr(cfg, "database_url", "")])
    backend_override = _first_configured_env(DATABASE_BACKEND_ENV_NAMES)
    if backend_override:
        _reject_unsupported_backend_signals(
            [os.environ.get(env_name) for env_name in DATABASE_BACKEND_ENV_NAMES],
            code=DATABASE_BACKEND_UNSUPPORTED_ERROR,
        )
        cfg.database_backend = backend_override
    url_override = _first_configured_env(DATABASE_URL_ENV_NAMES)
    if url_override:
        _reject_database_url_signals([os.environ.get(env_name) for env_name in DATABASE_URL_ENV_NAMES])
    assert_supported_database_backend(cfg)


def assert_supported_database_backend(cfg: Any) -> str:
    database_url = str(getattr(cfg, "database_url", "") or "").strip()
    if database_url:
        raise ValueError(DATABASE_URL_UNSUPPORTED_ERROR)
    backend = runtime_database_backend(cfg)
    cfg.database_backend = backend
    return backend


def runtime_database_backend(cfg: Any) -> str:
    backend = str(getattr(cfg, "database_backend", "sqlite") or "").strip().lower()
    if backend not in SUPPORTED_DATABASE_BACKENDS:
        raise ValueError(f"{DATABASE_BACKEND_UNSUPPORTED_ERROR}: {_safe_backend_label(backend)}")
    return backend


def _first_configured_env(env_names: tuple[str, ...]) -> str:
    for env_name in env_names:
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            return value
    return ""


def _reject_unsupported_backend_signals(values: list[Any], *, code: str) -> None:
    for value in values:
        backend = str(value or "").strip().lower()
        if backend and backend not in SUPPORTED_DATABASE_BACKENDS:
            raise ValueError(f"{code}: {_safe_backend_label(backend)}")


def _reject_database_url_signals(values: list[Any]) -> None:
    for value in values:
        if str(value or "").strip():
            raise ValueError(DATABASE_URL_UNSUPPORTED_ERROR)


def _safe_backend_label(value: str) -> str:
    backend = str(value or "").strip().lower()
    if not backend:
        return "missing"
    if len(backend) > 64:
        return "redacted"
    unsafe_markers = {":", "/", "\\", "@", "?", "#", "&", "="}
    if any(marker in backend for marker in unsafe_markers):
        return "redacted"
    if not all(char.isalnum() or char in {"_", "-", "."} for char in backend):
        return "redacted"
    return backend
