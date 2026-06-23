from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from core.governance_policy import SUPPORTED_ROLES

if TYPE_CHECKING:
    from .config import RemoteRunnerConfig


def normalize_api_token_roles(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_roles = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_roles = value
    else:
        raw_roles = ()
    roles = tuple(dict.fromkeys(str(role or "").strip() for role in raw_roles if str(role or "").strip()))
    unsupported = sorted(set(roles) - SUPPORTED_ROLES)
    if unsupported:
        raise ValueError(f"REMOTE_RUNNER_TOKEN_ROLE_UNSUPPORTED: {unsupported[0]}")
    return roles


def apply_api_token_env_overrides(cfg: RemoteRunnerConfig) -> None:
    actor = os.environ.get("H2OMETA_REMOTE_API_TOKEN_ACTOR")
    if str(actor or "").strip():
        cfg.api_token_actor = str(actor or "").strip()
    roles = os.environ.get("H2OMETA_REMOTE_API_TOKEN_ROLES")
    if str(roles or "").strip():
        cfg.api_token_roles = normalize_api_token_roles(str(roles or ""))
