"""Shared helpers for remote runner route modules."""

from __future__ import annotations

from dataclasses import dataclass
import hmac

from core.async_boundary import run_sync
from core.api_payloads import request_payload
from core.api_responses import data_response
from core.governance_policy import HIGH_RISK_API_POLICIES

from .config import RemoteRunnerConfig, load_remote_runner_config
from .errors import RemoteRunnerAuthorizationError, RemoteRunnerAuthError
from .governance_audit import record_governance_audit_event
from .sqlite_migrations import (
    DATABASE_MISSING_ERROR,
    SCHEMA_LEDGER_MISSING_ERROR,
    SCHEMA_MIGRATION_REQUIRED_ERROR,
    RemoteRunnerSQLiteSchemaError,
)

__all__ = ["data_response", "request_payload", "run_sync"]


@dataclass(frozen=True)
class RemoteRunnerPrincipal:
    actor: str
    roles: tuple[str, ...]


REMOTE_ACTION_POLICIES = {
    policy.action: policy
    for policy in HIGH_RISK_API_POLICIES
    if policy.surface == "remote-runner-api"
}


def require_auth(authorization: str | None, token: str) -> None:
    scheme, _, provided = str(authorization or "").partition(" ")
    if not token or scheme.lower() != "bearer" or not hmac.compare_digest(provided.strip(), token):
        raise RemoteRunnerAuthError("runner authentication failed")


def authorized_config(authorization: str | None, *, action: str | None = None) -> RemoteRunnerConfig:
    cfg = load_remote_runner_config()
    require_auth(authorization, cfg.token)
    if action:
        authorize_action(cfg, action)
    return cfg


def authorize_action(cfg: RemoteRunnerConfig, action: str) -> RemoteRunnerPrincipal:
    normalized_action = str(action or "").strip()
    policy = REMOTE_ACTION_POLICIES.get(normalized_action)
    if policy is None:
        raise RemoteRunnerAuthorizationError(f"runner authorization policy missing: {action}")
    required_roles = policy.future_roles
    principal = remote_runner_principal(cfg)
    if not set(principal.roles).intersection(required_roles):
        _record_authorization_denial(cfg, normalized_action, principal)
        raise RemoteRunnerAuthorizationError("runner authorization failed")
    return principal


def _record_authorization_denial(
    cfg: RemoteRunnerConfig,
    action: str,
    principal: RemoteRunnerPrincipal,
) -> None:
    policy = REMOTE_ACTION_POLICIES[action]
    try:
        record_governance_audit_event(
            cfg,
            action=action,
            actor=principal.actor,
            subject_kind=policy.subject_kind,
            subject_id="authorization",
            decision="deny",
            reason_code="REMOTE_RUNNER_ROLE_REQUIRED",
            details={
                "actor": principal.actor,
                "requiredRoles": list(policy.future_roles),
                "providedRoles": list(principal.roles),
            },
        )
    except RemoteRunnerSQLiteSchemaError as exc:
        if _authorization_denial_audit_unavailable(exc):
            return
        raise


def _authorization_denial_audit_unavailable(exc: RemoteRunnerSQLiteSchemaError) -> bool:
    message = str(exc)
    return message.startswith(
        (
            DATABASE_MISSING_ERROR,
            SCHEMA_MIGRATION_REQUIRED_ERROR,
            SCHEMA_LEDGER_MISSING_ERROR,
        )
    )


def remote_runner_principal(cfg: RemoteRunnerConfig) -> RemoteRunnerPrincipal:
    roles = tuple(
        role
        for role in (str(item or "").strip() for item in cfg.api_token_roles)
        if role
    )
    actor = str(cfg.api_token_actor or "").strip() or "remote-runner-api"
    return RemoteRunnerPrincipal(actor=actor, roles=roles)
