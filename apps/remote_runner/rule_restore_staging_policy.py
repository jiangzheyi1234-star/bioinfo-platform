from __future__ import annotations

from typing import Any


STAGED_FILE_POLICY_PLAN_SCHEMA_VERSION = "staged-file-policy-plan.v1"
STAGED_FILE_POLICY_UNREPRESENTED = "STAGED_FILE_POLICY_UNREPRESENTED"
STAGED_FILE_POLICY_PREVIEW_ONLY = "STAGED_FILE_POLICY_PREVIEW_ONLY"
STAGED_FILE_POLICY_EXECUTION_DISABLED = "STAGED_FILE_POLICY_EXECUTION_DISABLED"
STAGED_FILE_MATERIALIZATION_PIN_REQUIRED = "STAGED_FILE_MATERIALIZATION_PIN_REQUIRED"


def build_staged_file_policy_plan(
    rules: list[dict[str, Any]],
    *,
    output_invalidation_applied: bool,
) -> dict[str, Any]:
    outputs = _rule_outputs(rules)
    output_count = len(outputs)
    cache_hit_count = sum(1 for item in outputs if item["output"].get("cacheHit") is True)
    preview_available = bool(output_invalidation_applied and output_count > 0)
    materialization_enabled = bool(preview_available and cache_hit_count > 0)
    return {
        "schemaVersion": STAGED_FILE_POLICY_PLAN_SCHEMA_VERSION,
        "enabled": False,
        "materializationEnabled": materialization_enabled,
        "previewAvailable": preview_available,
        "reasonCode": _plan_reason_code(
            preview_available=preview_available,
            materialization_enabled=materialization_enabled,
        ),
        "blockedReasonCodes": [
            _plan_blocker(
                preview_available=preview_available,
                materialization_enabled=materialization_enabled,
            )
        ],
        "overwriteAllowed": False,
        "deleteUnknownOutputs": False,
        "pinCreationAllowed": False,
        "attemptFinalOutputPromotionAllowed": materialization_enabled,
        "finalOutputMutationAllowed": materialization_enabled,
        "finalOutputOverwriteAllowed": False,
        "attemptStagingAllowed": materialization_enabled,
        "stagingDirectoryManaged": materialization_enabled,
        "stagingDirectoryExposed": False,
        "pathExposed": False,
        "storageUriExposed": False,
        "cacheKeyExposed": False,
        "unknownOutputHandling": "refuse",
        "unknownOutputScanAvailable": False,
        "managedTargetCount": sum(1 for item in outputs if _restore_target_requires_managed_dir(item)),
        "targetCount": output_count,
        "selectedOutputCount": sum(1 for item in outputs if item["invalidationRole"] == "selected_failed_rule"),
        "downstreamOutputCount": sum(1 for item in outputs if item["invalidationRole"] == "downstream_rule"),
        "cacheHitTargetCount": cache_hit_count,
        "cacheMissTargetCount": sum(
            1
            for item in outputs
            if item["output"].get("artifactKey") is not None and item["output"].get("cacheHit") is not True
        ),
        "unmappedTargetCount": sum(1 for item in outputs if item["output"].get("artifactKey") is None),
        "unknownOutputCount": 0,
        "restorePinnedCount": 0,
        "requires": [
            "managed_work_dir",
            "selected_output_overwrite_plan",
            "downstream_output_tombstone_plan",
            "unknown_output_quarantine_policy",
            "restore_pin_creation_policy",
            "active_attempt_restore_pins",
            "active_staged_materializations",
            "current_attempt_result_dir",
        ],
    }


def staged_file_policy_blocker(*, output_invalidation_applied: bool) -> str:
    if output_invalidation_applied:
        return STAGED_FILE_POLICY_EXECUTION_DISABLED
    return STAGED_FILE_POLICY_UNREPRESENTED


def staged_restore_target_reason(*, output_invalidation_applied: bool) -> str:
    if output_invalidation_applied:
        return STAGED_FILE_POLICY_PREVIEW_ONLY
    return STAGED_FILE_POLICY_UNREPRESENTED


def _plan_reason_code(*, preview_available: bool, materialization_enabled: bool) -> str:
    if not preview_available:
        return STAGED_FILE_POLICY_UNREPRESENTED
    if materialization_enabled:
        return STAGED_FILE_MATERIALIZATION_PIN_REQUIRED
    return STAGED_FILE_POLICY_PREVIEW_ONLY


def _plan_blocker(*, preview_available: bool, materialization_enabled: bool) -> str:
    if not preview_available:
        return STAGED_FILE_POLICY_UNREPRESENTED
    if materialization_enabled:
        return STAGED_FILE_MATERIALIZATION_PIN_REQUIRED
    return STAGED_FILE_POLICY_EXECUTION_DISABLED


def _rule_outputs(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        invalidation_role = str(rule.get("invalidationRole") or "")
        for output in rule.get("outputs") or []:
            if isinstance(output, dict):
                items.append({"invalidationRole": invalidation_role, "output": output})
    return items


def _restore_target_requires_managed_dir(item: dict[str, Any]) -> bool:
    restore_target = item["output"].get("restoreTarget")
    return isinstance(restore_target, dict) and restore_target.get("managedResultsDirRequired") is True
