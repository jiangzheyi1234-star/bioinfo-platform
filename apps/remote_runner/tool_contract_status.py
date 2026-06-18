from __future__ import annotations

from typing import Any


VALIDATION_KEYS = ("dryRun", "smokeRun", "outputValidation", "production")
VALIDATION_PASSED = "passed"
VALIDATION_NOT_RUN = "not_run"


def default_contract_status() -> dict[str, dict[str, str]]:
    return {key: {"status": VALIDATION_NOT_RUN, "message": ""} for key in VALIDATION_KEYS}


def normalize_contract_status(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        return default_contract_status()
    normalized = default_contract_status()
    for key in VALIDATION_KEYS:
        value = raw.get(key)
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or VALIDATION_NOT_RUN).strip() or VALIDATION_NOT_RUN
        item = {"status": status, "message": str(value.get("message") or "")}
        code = str(value.get("code") or "").strip()
        if code:
            item["code"] = code
        checked_at = str(value.get("checkedAt") or "").strip()
        if checked_at:
            item["checkedAt"] = checked_at
        for evidence_key in (
            "runId",
            "logPath",
            "resourceKey",
            "resourceType",
            "configKey",
            "acceptedTemplates",
            "acceptedCapabilities",
            "evidenceType",
            "targetPlatform",
            "artifactDigest",
            "policyVersion",
            "databaseId",
            "templateId",
            "role",
            "artifactName",
            "packId",
            "packChecksum",
            "artifactCount",
            "artifactNames",
            "evidenceId",
        ):
            evidence_value = str(value.get(evidence_key) or "").strip()
            if evidence_value:
                item[evidence_key] = evidence_value
        normalized[key] = item
    return normalized
