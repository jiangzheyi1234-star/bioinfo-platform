from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .artifact_cache_storage import (
    create_artifact_cache_pins,
    get_artifact_cache_entry,
    get_artifact_cache_pin,
    list_artifact_cache_pins,
    release_artifact_cache_pins,
)
from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .storage_core import now_iso


ARTIFACT_CACHE_POLICY_PIN_SCOPE = "policy"
ARTIFACT_CACHE_POLICY_PIN_OWNER_KIND = "operator"
ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION = "release-artifact-cache-policy-pin"


def list_artifact_cache_policy_pins(
    cfg: RemoteRunnerConfig,
    *,
    cache_entry_id: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    return list_artifact_cache_pins(
        cfg,
        cache_entry_id=cache_entry_id,
        state=state,
        pin_scope=ARTIFACT_CACHE_POLICY_PIN_SCOPE,
        limit=limit,
    )


def retain_artifact_cache_policy_pin(
    cfg: RemoteRunnerConfig,
    cache_entry_id: str,
    payload: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    normalized_entry_id = _required_text(cache_entry_id, "ARTIFACT_CACHE_PIN_ENTRY_REQUIRED")
    reason = _required_text(payload.get("reason"), "ARTIFACT_CACHE_PIN_REASON_REQUIRED")
    owner_id = _optional_text(payload.get("ownerId")) or _required_text(actor, "ARTIFACT_CACHE_PIN_ACTOR_REQUIRED")
    expires_at = _optional_text(payload.get("expiresAt"))
    if expires_at:
        _require_future_iso(expires_at)
    entry = get_artifact_cache_entry(cfg, normalized_entry_id)
    if str(entry.get("lifecycleState") or "") != "active":
        raise ValueError(f"ARTIFACT_CACHE_ENTRY_NOT_ACTIVE: {normalized_entry_id}")
    pin = create_artifact_cache_pins(
        cfg,
        entries=[entry],
        pin_scope=ARTIFACT_CACHE_POLICY_PIN_SCOPE,
        owner_kind=ARTIFACT_CACHE_POLICY_PIN_OWNER_KIND,
        owner_id=owner_id,
        reason=reason,
        expires_at=expires_at,
        ttl_seconds=None,
    )[0]
    record_governance_audit_event(
        cfg,
        action="artifact.cache_pin.retain",
        actor=actor,
        subject_kind="artifact_cache_pin",
        subject_id=pin["cachePinId"],
        details={
            "cacheEntryId": pin["cacheEntryId"],
            "ownerId": pin["ownerId"],
            "artifactBlobId": pin["artifactBlobId"],
            "storageBackend": pin["storageBackend"],
            "sha256": pin["sha256"],
            "reason": pin["reason"],
            "expiresAt": pin["expiresAt"],
        },
    )
    return pin


def release_artifact_cache_policy_pin(
    cfg: RemoteRunnerConfig,
    cache_pin_id: str,
    payload: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    confirmation = _required_text(payload.get("confirmation"), "ARTIFACT_CACHE_PIN_RELEASE_CONFIRMATION_REQUIRED")
    if confirmation != ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION:
        raise ValueError("ARTIFACT_CACHE_PIN_RELEASE_CONFIRMATION_REQUIRED")
    pin = get_artifact_cache_pin(cfg, cache_pin_id)
    if pin["pinScope"] != ARTIFACT_CACHE_POLICY_PIN_SCOPE:
        raise ValueError(f"ARTIFACT_CACHE_PIN_SCOPE_UNSUPPORTED: {pin['pinScope']}")
    if pin["ownerKind"] != ARTIFACT_CACHE_POLICY_PIN_OWNER_KIND:
        raise ValueError(f"ARTIFACT_CACHE_PIN_OWNER_KIND_UNSUPPORTED: {pin['ownerKind']}")
    released_at = now_iso()
    release_artifact_cache_pins(cfg, pin_ids=[cache_pin_id], released_at=released_at)
    released = get_artifact_cache_pin(cfg, cache_pin_id)
    record_governance_audit_event(
        cfg,
        action="artifact.cache_pin.release",
        actor=actor,
        subject_kind="artifact_cache_pin",
        subject_id=cache_pin_id,
        details={
            "cacheEntryId": released["cacheEntryId"],
            "ownerId": released["ownerId"],
            "previousState": pin["state"],
            "state": released["state"],
            "releasedAt": released["releasedAt"],
            "reason": str(payload.get("reason") or "").strip(),
        },
    )
    return released


def _require_future_iso(value: str) -> None:
    try:
        expires_at = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("ARTIFACT_CACHE_PIN_EXPIRES_AT_INVALID") from exc
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("ARTIFACT_CACHE_PIN_EXPIRES_AT_PAST")


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
