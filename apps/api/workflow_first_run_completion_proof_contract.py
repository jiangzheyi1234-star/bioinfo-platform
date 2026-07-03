"""Completion proof evidence contract for First Successful Run status."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.api.workflow_first_run_completion_store import (
    FIRST_RUN_COMPLETION_PROOF_INVALID,
    FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION,
    FirstRunCompletionProofStoreError,
    latest_first_run_completion_proof,
)


FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE = "FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE"
_FIRST_RUN_COMPLETION_PROOF_BLOCKED_CODES = frozenset(
    (FIRST_RUN_COMPLETION_PROOF_INVALID, FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE)
)

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
)
_REQUIRED_SHA256_FIELDS = (
    "resultPackageSha256",
    "resultPackageManifestSha256",
    "validationCardJsonSha256",
)
_REQUIRED_REPORT_OUTPUTS = frozenset(("summary.tsv", "qc-summary.tsv", "feature-table.tsv", "run-report.html"))
_REQUIRED_EVIDENCE_BUNDLE_ROLES = frozenset(
    ("result-package", "validation-card-json", "validation-card-markdown", "pilot-handoff")
)


def first_run_completion_proof_evidence(
    proof: dict[str, Any] | None,
    *,
    server_id: str | None = None,
) -> dict[str, Any]:
    if not proof:
        return {"ready": False}
    if not isinstance(proof, dict):
        return _invalid("saved first-run completion proof must be an object")
    if proof.get("ready") is not True:
        if proof.get("blockedCode") in _FIRST_RUN_COMPLETION_PROOF_BLOCKED_CODES:
            return deepcopy(proof)
        return {"ready": False}
    schema_version = str(proof.get("schemaVersion") or "").strip()
    if schema_version != FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION:
        return _invalid("saved first-run completion proof schema is unsupported")
    requested_server_id = str(server_id or "").strip()
    proof_server_id = str(proof.get("serverId") or "").strip()
    if requested_server_id and proof_server_id != requested_server_id:
        return _invalid("saved first-run completion proof belongs to a different server")
    missing_fields = [field for field in _REQUIRED_READY_FIELDS if not str(proof.get(field) or "").strip()]
    if missing_fields:
        return _invalid("saved first-run completion proof is missing " + ", ".join(missing_fields))
    identity_error = _identity_error(proof)
    if identity_error:
        return _invalid("saved first-run completion proof " + identity_error)
    invalid_hash_fields = [field for field in _REQUIRED_SHA256_FIELDS if not _valid_sha256(str(proof.get(field) or ""))]
    if invalid_hash_fields:
        return _invalid("saved first-run completion proof has invalid sha256 " + ", ".join(invalid_hash_fields))
    passed = proof.get("validationChecksPassed")
    total = proof.get("validationChecksTotal")
    if not _valid_check_counts(passed, total):
        return _invalid("saved first-run completion proof validation checks are incomplete")
    if proof.get("reportReady") is not True:
        return _invalid("saved first-run completion proof report evidence is not ready")
    report_output_names = {str(item or "").strip() for item in proof.get("reportOutputNames") or []}
    missing_report_outputs = sorted(_REQUIRED_REPORT_OUTPUTS - report_output_names)
    if missing_report_outputs:
        return _invalid("saved first-run completion proof is missing report outputs " + ", ".join(missing_report_outputs))
    if proof.get("evidenceBundleReady") is not True:
        return _invalid("saved first-run completion proof evidence bundle is not ready")
    evidence_bundle_roles = {str(item or "").strip() for item in proof.get("evidenceBundleFileRoles") or []}
    missing_bundle_roles = sorted(_REQUIRED_EVIDENCE_BUNDLE_ROLES - evidence_bundle_roles)
    if missing_bundle_roles:
        return _invalid("saved first-run completion proof is missing evidence bundle roles " + ", ".join(missing_bundle_roles))
    return deepcopy(proof)


def first_run_completion_proof_store_unreadable_evidence(exc: Exception) -> dict[str, Any]:
    detail = str(exc).strip() or "unknown store error"
    return {
        "ready": False,
        "blockedCode": FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE,
        "detail": f"saved first-run completion proof store is unreadable: {detail}",
    }


def latest_first_run_completion_proof_evidence(*, server_id: str) -> dict[str, Any]:
    try:
        proof = latest_first_run_completion_proof(server_id=server_id)
    except FirstRunCompletionProofStoreError as exc:
        return first_run_completion_proof_store_unreadable_evidence(exc)
    return first_run_completion_proof_evidence(proof, server_id=server_id)


def _valid_check_counts(passed: Any, total: Any) -> bool:
    if not isinstance(passed, int) or isinstance(passed, bool):
        return False
    if not isinstance(total, int) or isinstance(total, bool):
        return False
    return total > 0 and passed == total


def _valid_sha256(value: str) -> bool:
    normalized = value.strip().lower()
    return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)


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


def _invalid(detail: str) -> dict[str, Any]:
    return {"ready": False, "blockedCode": FIRST_RUN_COMPLETION_PROOF_INVALID, "detail": detail}
