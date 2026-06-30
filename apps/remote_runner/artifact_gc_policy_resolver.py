from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .artifact_lifecycle_policy import (
    artifact_lifecycle_policy_fingerprint,
    get_artifact_lifecycle_policy,
    normalize_artifact_lifecycle_policy_payload,
    require_complete_artifact_lifecycle_policy_payload,
)
from .config import RemoteRunnerConfig


DEFAULT_GC_REASON = "retention_expired"
GC_POLICY_OVERRIDE_FIELDS = (
    "retentionDays",
    "eligibleRunStatuses",
    "quotaBytes",
    "maxDeleteBytes",
    "maxDeleteBytesPerTick",
    "reason",
    "policyId",
    "policyVersion",
    "policyFingerprint",
    "persisted",
)


@dataclass(frozen=True)
class GcPolicy:
    policy_id: str
    policy_version: int
    policy_fingerprint: str
    persisted: bool
    retention_days: int
    run_statuses: set[str]
    max_delete_bytes: int | None
    reason: str
    actor: str


def resolve_gc_policy(cfg: RemoteRunnerConfig, payload: dict[str, Any] | None) -> GcPolicy:
    body = dict(payload or {})
    if not has_gc_policy_override(body):
        stored = get_artifact_lifecycle_policy(cfg)
        return GcPolicy(
            policy_id=stored.policy_id,
            policy_version=stored.policy_version,
            policy_fingerprint=stored.policy_fingerprint,
            persisted=stored.persisted,
            retention_days=stored.retention_days,
            run_statuses=set(stored.eligible_run_statuses),
            max_delete_bytes=stored.max_delete_bytes_per_tick,
            reason=stored.reason,
            actor=str(body.get("actor") or stored.actor or "remote-runner-api").strip() or "remote-runner-api",
        )
    require_complete_artifact_lifecycle_policy_payload(
        body,
        error_prefix="ARTIFACT_GC_INLINE_POLICY",
    )
    if not str(body.get("policyFingerprint") or "").strip():
        raise ValueError("ARTIFACT_GC_INLINE_POLICY_FINGERPRINT_REQUIRED")
    normalized_body = dict(body)
    if "maxDeleteBytes" in body and "maxDeleteBytesPerTick" not in normalized_body:
        normalized_body["maxDeleteBytesPerTick"] = body["maxDeleteBytes"]
    normalized = normalize_artifact_lifecycle_policy_payload(normalized_body)
    fingerprint = artifact_lifecycle_policy_fingerprint(normalized)
    if str(body["policyFingerprint"]) != fingerprint:
        raise ValueError("ARTIFACT_LIFECYCLE_POLICY_FINGERPRINT_MISMATCH")
    policy_id = str(body.get("policyId") or "request").strip() or "request"
    return GcPolicy(
        policy_id=policy_id,
        policy_version=_safe_non_negative_int(body.get("policyVersion"), default=0),
        policy_fingerprint=fingerprint,
        persisted=bool(body.get("persisted")) and policy_id != "request",
        retention_days=int(normalized["retentionDays"]),
        run_statuses=set(normalized["eligibleRunStatuses"]),
        max_delete_bytes=normalized["maxDeleteBytesPerTick"],
        reason=str(normalized["reason"] or DEFAULT_GC_REASON),
        actor=str(normalized["actor"] or "remote-runner-api"),
    )


def has_gc_policy_override(body: dict[str, Any]) -> bool:
    return any(key in body for key in GC_POLICY_OVERRIDE_FIELDS)


def _safe_non_negative_int(value: Any, *, default: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized if normalized >= 0 else default
