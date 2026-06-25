from __future__ import annotations

from typing import Any

from .artifact_cache_storage import (
    ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
    ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
    ARTIFACT_CACHE_RESTORE_PIN_TTL_SECONDS,
)


RESTORE_PIN_POLICY_PLAN_SCHEMA_VERSION = "restore-pin-policy-plan.v1"
RESTORE_PIN_OUTPUT_POLICY_SCHEMA_VERSION = "restore-pin-output-policy.v1"
RESTORE_PIN_POLICY_UNREPRESENTED = "RESTORE_PIN_POLICY_UNREPRESENTED"
RESTORE_PIN_POLICY_PREVIEW_ONLY = "RESTORE_PIN_POLICY_PREVIEW_ONLY"
RESTORE_PIN_CREATION_DISABLED = "RESTORE_PIN_CREATION_DISABLED"
RESTORE_PIN_OUTPUT_INVALIDATION_REQUIRED = "RESTORE_PIN_OUTPUT_INVALIDATION_REQUIRED"
RESTORE_PIN_CACHE_HIT_REQUIRED = "RESTORE_PIN_CACHE_HIT_REQUIRED"
RESTORE_PIN_CACHE_ENTRY_REQUIRED = "RESTORE_PIN_CACHE_ENTRY_REQUIRED"


def build_restore_pin_policy_plan(
    rules: list[dict[str, Any]],
    *,
    output_invalidation_applied: bool,
) -> dict[str, Any]:
    outputs = _rule_outputs(rules)
    candidate_count = sum(1 for output in outputs if _pin_policy(output).get("candidate") is True)
    eligible_count = sum(1 for output in outputs if _pin_policy(output).get("eligible") is True)
    output_count = len(outputs)
    preview_available = bool(output_invalidation_applied and output_count > 0)
    return {
        "schemaVersion": RESTORE_PIN_POLICY_PLAN_SCHEMA_VERSION,
        "previewAvailable": preview_available,
        "creationEnabled": False,
        "pinCreationAllowed": False,
        "reasonCode": RESTORE_PIN_POLICY_PREVIEW_ONLY if preview_available else RESTORE_PIN_POLICY_UNREPRESENTED,
        "blockedReasonCodes": [
            RESTORE_PIN_CREATION_DISABLED if preview_available else RESTORE_PIN_POLICY_UNREPRESENTED
        ],
        "pinScope": ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
        "ownerKind": ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
        "ttlSeconds": ARTIFACT_CACHE_RESTORE_PIN_TTL_SECONDS,
        "attemptScoped": True,
        "ownerIdExposed": False,
        "cacheKeyExposed": False,
        "storageUriExposed": False,
        "pathExposed": False,
        "targetCount": output_count,
        "candidatePinCount": candidate_count,
        "requiredPinCount": eligible_count,
        "eligiblePinCount": eligible_count,
        "blockedPinCount": max(0, output_count - eligible_count),
        "createdPinCount": 0,
        "activePinCount": 0,
        "releasedPinCount": 0,
        "requires": [
            "active_attempt_lease",
            "verified_cache_hit",
            "attempt_scoped_restore_pin_owner",
            "pin_release_after_restore",
            "gc_protection_during_restore",
        ],
    }


def restore_pin_output_policy(
    *,
    cache_hit: bool,
    cache_entry: Any,
    output_invalidation_applied: bool,
) -> dict[str, Any]:
    cache_entry_present = isinstance(cache_entry, dict)
    candidate = bool(cache_hit and cache_entry_present)
    eligible = bool(output_invalidation_applied and candidate)
    reason_code = _output_reason_code(
        cache_hit=cache_hit,
        cache_entry_present=cache_entry_present,
        output_invalidation_applied=output_invalidation_applied,
    )
    return {
        "schemaVersion": RESTORE_PIN_OUTPUT_POLICY_SCHEMA_VERSION,
        "candidate": candidate,
        "required": eligible,
        "eligible": eligible,
        "created": False,
        "pinCreationAllowed": False,
        "pinScope": ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
        "ownerKind": ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
        "ttlSeconds": ARTIFACT_CACHE_RESTORE_PIN_TTL_SECONDS,
        "attemptScoped": True,
        "ownerIdExposed": False,
        "cacheKeyExposed": False,
        "storageUriExposed": False,
        "pathExposed": False,
        "reasonCode": reason_code,
        "blockedReasonCodes": [RESTORE_PIN_CREATION_DISABLED if eligible else reason_code],
    }


def restore_pin_policy_blocker(*, output_invalidation_applied: bool) -> str:
    if output_invalidation_applied:
        return RESTORE_PIN_CREATION_DISABLED
    return RESTORE_PIN_POLICY_UNREPRESENTED


def _output_reason_code(
    *,
    cache_hit: bool,
    cache_entry_present: bool,
    output_invalidation_applied: bool,
) -> str:
    if not output_invalidation_applied:
        return RESTORE_PIN_OUTPUT_INVALIDATION_REQUIRED
    if not cache_hit:
        return RESTORE_PIN_CACHE_HIT_REQUIRED
    if not cache_entry_present:
        return RESTORE_PIN_CACHE_ENTRY_REQUIRED
    return RESTORE_PIN_POLICY_PREVIEW_ONLY


def _rule_outputs(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for rule in rules:
        if isinstance(rule, dict):
            outputs.extend(output for output in rule.get("outputs") or [] if isinstance(output, dict))
    return outputs


def _pin_policy(output: dict[str, Any]) -> dict[str, Any]:
    policy = output.get("restorePinPolicy")
    return policy if isinstance(policy, dict) else {}
