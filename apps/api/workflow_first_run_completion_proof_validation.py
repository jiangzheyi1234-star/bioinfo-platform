"""Shared validation for First Successful Run completion proofs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


FIRST_RUN_COMPLETION_PROOF_INVALID = "FIRST_RUN_COMPLETION_PROOF_INVALID"
FIRST_RUN_COMPLETION_PROOF_MIN_VALIDATION_CHECKS = 10

_REQUIRED_READY_FIELDS = (
    "serverId",
    "runId",
    "resultId",
    "workflowRevisionId",
    "packageExportId",
    "packageEvidenceId",
    "resultPackageSha256",
    "resultPackageManifestSha256",
    "validationCardGeneratedAt",
    "validationCardJsonSha256",
    "evidenceBundleId",
    "savedAt",
)
_REQUIRED_SHA256_FIELDS = (
    "resultPackageSha256",
    "resultPackageManifestSha256",
    "validationCardJsonSha256",
)
_REQUIRED_TIMESTAMP_FIELDS = (
    "validationCardGeneratedAt",
    "savedAt",
)
_REQUIRED_REPORT_OUTPUTS = frozenset(("summary.tsv", "qc-summary.tsv", "feature-table.tsv", "run-report.html"))
_REQUIRED_EVIDENCE_BUNDLE_ROLES = frozenset(
    ("result-package", "validation-card-json", "validation-card-markdown", "pilot-handoff")
)


def first_run_completion_proof_invalid_reason(proof: dict[str, Any]) -> str:
    missing_fields = [field for field in _REQUIRED_READY_FIELDS if not str(proof.get(field) or "").strip()]
    if missing_fields:
        return "missing " + ", ".join(missing_fields)
    identity_error = _identity_error(proof)
    if identity_error:
        return identity_error
    invalid_hash_fields = [field for field in _REQUIRED_SHA256_FIELDS if not _valid_sha256(str(proof.get(field) or ""))]
    if invalid_hash_fields:
        return "invalid sha256 " + ", ".join(invalid_hash_fields)
    invalid_timestamp_fields = [
        field for field in _REQUIRED_TIMESTAMP_FIELDS if not _valid_utc_timestamp(str(proof.get(field) or ""))
    ]
    if invalid_timestamp_fields:
        return "invalid timestamp " + ", ".join(invalid_timestamp_fields)
    saved_at = _utc_timestamp(str(proof.get("savedAt") or ""))
    generated_at = _utc_timestamp(str(proof.get("validationCardGeneratedAt") or ""))
    if saved_at is None or generated_at is None or saved_at < generated_at:
        return "savedAt predates validationCardGeneratedAt"
    if not _valid_check_counts(proof.get("validationChecksPassed"), proof.get("validationChecksTotal")):
        return "validation checks are incomplete"
    if proof.get("reportReady") is not True:
        return "report evidence is not ready"
    report_output_error = _report_output_error(proof.get("reportOutputNames"))
    if report_output_error:
        return report_output_error
    if proof.get("evidenceBundleReady") is not True:
        return "evidence bundle is not ready"
    bundle_role_error = _evidence_bundle_role_error(proof.get("evidenceBundleFileRoles"))
    if bundle_role_error:
        return bundle_role_error
    return ""


def saved_first_run_completion_proof_invalid_detail(proof: dict[str, Any]) -> str:
    reason = first_run_completion_proof_invalid_reason(proof)
    if not reason:
        return ""
    if reason.startswith("invalid sha256 "):
        return "saved first-run completion proof has " + reason
    if reason.startswith("missing "):
        return "saved first-run completion proof is " + reason
    return "saved first-run completion proof " + reason


def _valid_check_counts(passed: Any, total: Any) -> bool:
    if not isinstance(passed, int) or isinstance(passed, bool):
        return False
    if not isinstance(total, int) or isinstance(total, bool):
        return False
    return total >= FIRST_RUN_COMPLETION_PROOF_MIN_VALIDATION_CHECKS and passed == total


def _valid_sha256(value: str) -> bool:
    normalized = value.strip().lower()
    return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)


def _evidence_bundle_role_error(value: Any) -> str:
    roles = [str(item or "").strip() for item in value or []]
    role_set = set(roles)
    missing_roles = sorted(_REQUIRED_EVIDENCE_BUNDLE_ROLES - role_set)
    if missing_roles:
        return "missing evidence bundle roles " + ", ".join(missing_roles)
    unexpected_roles = sorted(role for role in role_set if role not in _REQUIRED_EVIDENCE_BUNDLE_ROLES)
    if unexpected_roles:
        return "unexpected evidence bundle roles " + ", ".join(unexpected_roles)
    duplicate_roles = sorted(role for role in role_set if roles.count(role) > 1)
    if duplicate_roles:
        return "duplicate evidence bundle roles " + ", ".join(duplicate_roles)
    return ""


def _report_output_error(value: Any) -> str:
    outputs = [str(item or "").strip() for item in value or []]
    output_set = set(outputs)
    missing_outputs = sorted(_REQUIRED_REPORT_OUTPUTS - output_set)
    if missing_outputs:
        return "missing report outputs " + ", ".join(missing_outputs)
    unexpected_outputs = sorted(output for output in output_set if output not in _REQUIRED_REPORT_OUTPUTS)
    if unexpected_outputs:
        return "unexpected report outputs " + ", ".join(unexpected_outputs)
    duplicate_outputs = sorted(output for output in output_set if outputs.count(output) > 1)
    if duplicate_outputs:
        return "duplicate report outputs " + ", ".join(duplicate_outputs)
    return ""


def _valid_utc_timestamp(value: str) -> bool:
    return _utc_timestamp(value) is not None


def _utc_timestamp(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    candidate = normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed


def _identity_error(proof: dict[str, Any]) -> str:
    run_id = str(proof.get("runId") or "").strip()
    result_id = str(proof.get("resultId") or "").strip()
    expected_result_id = _canonical_result_id(run_id)
    if run_id and result_id and result_id != expected_result_id:
        return "resultId does not match runId"
    evidence_bundle_id = str(proof.get("evidenceBundleId") or "").strip()
    expected_bundle_id = f"{result_id}.first-run-evidence" if result_id else ""
    if result_id and evidence_bundle_id and evidence_bundle_id != expected_bundle_id:
        return "evidenceBundleId does not match resultId"
    return ""


def _canonical_result_id(run_id: str) -> str:
    normalized = run_id.strip()
    return normalized if normalized.startswith("res_") else f"res_{normalized}"
