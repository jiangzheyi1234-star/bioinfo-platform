"""Shared helpers for remote runner route modules."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .config import RemoteRunnerConfig, load_remote_runner_config


def require_auth(authorization: str | None, token: str) -> None:
    expected = f"Bearer {token}"
    if not token or authorization != expected:
        raise HTTPException(status_code=401, detail="runner authentication failed")


def authorized_config(authorization: str | None) -> RemoteRunnerConfig:
    cfg = load_remote_runner_config()
    require_auth(authorization, cfg.token)
    return cfg


def data_response(value: Any) -> dict[str, Any]:
    return {"data": value}
