from __future__ import annotations

from typing import Any


CAPABILITY_BUNDLE_VERSION = "capability-bundle-v1"

REQUIRED_CAPABILITY_BUNDLE_KEYS = frozenset(
    {
        "capabilityBundleVersion",
        "capabilityId",
        "toolRevisionId",
        "source",
        "version",
        "inputs",
        "outputs",
        "parameters",
        "environmentLock",
        "risk",
        "permissions",
        "approval",
        "validationEvidence",
        "selectionSummary",
    }
)


def validate_capability_bundle_contract(bundle: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(key for key in REQUIRED_CAPABILITY_BUNDLE_KEYS if key not in bundle)
    if missing:
        raise ValueError(f"CAPABILITY_BUNDLE_FIELD_REQUIRED: {','.join(missing)}")
    if bundle.get("capabilityBundleVersion") != CAPABILITY_BUNDLE_VERSION:
        raise ValueError("CAPABILITY_BUNDLE_VERSION_UNSUPPORTED")
    return bundle
