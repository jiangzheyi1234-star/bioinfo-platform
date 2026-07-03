"""Persistent First Successful Run completion proof index."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import get_app_data_dir


FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION = "h2ometa.first-run.completion-proof.v1"
FIRST_RUN_COMPLETION_PROOF_REGISTRY_VERSION = 1
FIRST_RUN_COMPLETION_PROOF_MAX_RECORDS = 25
FIRST_RUN_COMPLETION_PROOF_INVALID = "FIRST_RUN_COMPLETION_PROOF_INVALID"
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


class FirstRunCompletionProofStoreError(ValueError):
    """Raised when first-run completion proof persistence fails closed."""


def get_first_run_completion_proof_store_path() -> Path:
    return get_app_data_dir() / "first-run" / "completion-proofs-v1.json"


def record_first_run_completion_proof(
    card: dict[str, Any],
    *,
    server_id: str | None = None,
    store_path: Path | None = None,
) -> dict[str, Any]:
    path = store_path or get_first_run_completion_proof_store_path()
    proof = build_first_run_completion_proof(card, server_id=server_id)
    _ensure_ready_completion_proof(proof)
    registry = _read_registry(path)
    records = [record for record in _records(registry) if record.get("proofKey") != proof["proofKey"]]
    records.append(proof)
    registry["records"] = sorted(records, key=lambda item: str(item.get("savedAt") or ""))[
        -FIRST_RUN_COMPLETION_PROOF_MAX_RECORDS:
    ]
    _write_registry(path, registry)
    return _public_proof(proof)


def latest_first_run_completion_proof(
    *,
    server_id: str | None = None,
    store_path: Path | None = None,
) -> dict[str, Any] | None:
    registry = _read_registry(store_path or get_first_run_completion_proof_store_path(), missing_ok=True)
    wanted_server_id = str(server_id or "").strip()
    records = _records(registry)
    if wanted_server_id:
        records = [record for record in records if str(record.get("serverId") or "").strip() == wanted_server_id]
    if not records:
        return None
    latest = sorted(records, key=lambda item: str(item.get("savedAt") or ""))[-1]
    return _public_proof(latest)


def build_first_run_completion_proof(
    card: dict[str, Any],
    *,
    server_id: str | None = None,
) -> dict[str, Any]:
    normalized = _json_clone(card)
    run = _mapping(normalized.get("run"))
    result = _mapping(normalized.get("result"))
    runner = _mapping(normalized.get("runner"))
    workflow_revision = _mapping(normalized.get("workflowRevision"))
    package = _mapping(normalized.get("resultPackage"))
    report_interpretation = _mapping(normalized.get("reportInterpretation"))
    report_outputs = [
        item for item in report_interpretation.get("outputs") or [] if isinstance(item, dict)
    ]
    handoff = _mapping(normalized.get("pilotHandoff"))
    bundle = _mapping(handoff.get("evidenceBundle"))
    required_files = [item for item in bundle.get("requiredFiles") or [] if isinstance(item, dict)]
    checks = [item for item in normalized.get("checks") or [] if isinstance(item, dict)]
    passed_checks = sum(1 for item in checks if item.get("status") == "passed")

    resolved_server_id = str(server_id or runner.get("serverId") or "").strip()
    run_id = str(run.get("runId") or "").strip()
    result_id = str(result.get("resultId") or "").strip()
    workflow_revision_id = str(workflow_revision.get("workflowRevisionId") or "").strip()
    package_export_id = str(package.get("packageExportId") or "").strip()
    if not all((resolved_server_id, run_id, result_id, workflow_revision_id, package_export_id)):
        raise FirstRunCompletionProofStoreError("FIRST_RUN_COMPLETION_PROOF_IDENTITY_REQUIRED")

    return {
        "schemaVersion": FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION,
        "proofKey": "|".join((resolved_server_id, run_id, result_id, package_export_id)),
        "serverId": resolved_server_id,
        "runId": run_id,
        "resultId": result_id,
        "workflowRevisionId": workflow_revision_id,
        "packageExportId": package_export_id,
        "packageEvidenceId": str(package.get("evidenceId") or "").strip(),
        "resultPackageSha256": str(package.get("sha256") or "").strip(),
        "resultPackageManifestSha256": str(package.get("manifestSha256") or "").strip(),
        "validationCardGeneratedAt": str(normalized.get("generatedAt") or "").strip(),
        "validationCardJsonSha256": _validation_card_json_sha256(normalized),
        "validationChecksPassed": passed_checks,
        "validationChecksTotal": len(checks),
        "reportReady": report_interpretation.get("status") == "ready",
        "reportOutputNames": [
            str(item.get("name") or "").strip() for item in report_outputs if item.get("name")
        ],
        "evidenceBundleId": str(bundle.get("bundleId") or "").strip(),
        "evidenceBundleReady": bundle.get("status") == "ready",
        "evidenceBundleFileRoles": [str(item.get("role") or "").strip() for item in required_files if item.get("role")],
        "savedAt": _now(),
        "ready": True,
    }


def _validation_card_json_sha256(card: dict[str, Any]) -> str:
    payload = json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_registry(path: Path, *, missing_ok: bool = False) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": FIRST_RUN_COMPLETION_PROOF_REGISTRY_VERSION, "records": []}
    except json.JSONDecodeError as exc:
        raise FirstRunCompletionProofStoreError("FIRST_RUN_COMPLETION_PROOF_STORE_INVALID_JSON") from exc
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != FIRST_RUN_COMPLETION_PROOF_REGISTRY_VERSION:
        raise FirstRunCompletionProofStoreError("FIRST_RUN_COMPLETION_PROOF_STORE_VERSION_UNSUPPORTED")
    if not isinstance(payload.get("records"), list):
        raise FirstRunCompletionProofStoreError("FIRST_RUN_COMPLETION_PROOF_STORE_RECORDS_INVALID")
    return payload


def _write_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _records(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [record for record in registry.get("records") or [] if isinstance(record, dict)]


def _ensure_ready_completion_proof(proof: dict[str, Any]) -> None:
    missing_fields = [field for field in _REQUIRED_READY_FIELDS if not str(proof.get(field) or "").strip()]
    if missing_fields:
        raise _invalid_proof("missing " + ", ".join(missing_fields))
    invalid_hash_fields = [field for field in _REQUIRED_SHA256_FIELDS if not _valid_sha256(str(proof.get(field) or ""))]
    if invalid_hash_fields:
        raise _invalid_proof("invalid sha256 " + ", ".join(invalid_hash_fields))
    if not _valid_check_counts(proof.get("validationChecksPassed"), proof.get("validationChecksTotal")):
        raise _invalid_proof("validation checks are incomplete")
    if proof.get("reportReady") is not True:
        raise _invalid_proof("report evidence is not ready")
    report_output_names = {str(item or "").strip() for item in proof.get("reportOutputNames") or []}
    missing_report_outputs = sorted(_REQUIRED_REPORT_OUTPUTS - report_output_names)
    if missing_report_outputs:
        raise _invalid_proof("missing report outputs " + ", ".join(missing_report_outputs))
    if proof.get("evidenceBundleReady") is not True:
        raise _invalid_proof("evidence bundle is not ready")
    evidence_bundle_roles = {str(item or "").strip() for item in proof.get("evidenceBundleFileRoles") or []}
    missing_bundle_roles = sorted(_REQUIRED_EVIDENCE_BUNDLE_ROLES - evidence_bundle_roles)
    if missing_bundle_roles:
        raise _invalid_proof("missing evidence bundle roles " + ", ".join(missing_bundle_roles))


def _valid_check_counts(passed: Any, total: Any) -> bool:
    if not isinstance(passed, int) or isinstance(passed, bool):
        return False
    if not isinstance(total, int) or isinstance(total, bool):
        return False
    return total > 0 and passed == total


def _valid_sha256(value: str) -> bool:
    normalized = value.strip().lower()
    return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)


def _invalid_proof(detail: str) -> FirstRunCompletionProofStoreError:
    return FirstRunCompletionProofStoreError(f"{FIRST_RUN_COMPLETION_PROOF_INVALID}: {detail}")


def _public_proof(record: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(record[key]) for key in record if key != "proofKey"}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_clone(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FirstRunCompletionProofStoreError("FIRST_RUN_COMPLETION_PROOF_CARD_REQUIRED")
    return json.loads(json.dumps(deepcopy(value), ensure_ascii=False))


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
