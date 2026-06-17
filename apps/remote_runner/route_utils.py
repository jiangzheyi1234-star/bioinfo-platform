"""Shared helpers for remote runner route modules."""

from __future__ import annotations

import hmac

from core.async_boundary import run_sync
from core.api_payloads import request_payload
from core.api_responses import data_response

from .config import RemoteRunnerConfig, load_remote_runner_config
from .errors import RemoteRunnerAuthError

__all__ = ["data_response", "request_payload", "run_sync"]


def require_auth(authorization: str | None, token: str) -> None:
    scheme, _, provided = str(authorization or "").partition(" ")
    if not token or scheme.lower() != "bearer" or not hmac.compare_digest(provided.strip(), token):
        raise RemoteRunnerAuthError("runner authentication failed")


def authorized_config(authorization: str | None) -> RemoteRunnerConfig:
    cfg = load_remote_runner_config()
    require_auth(authorization, cfg.token)
    return cfg
