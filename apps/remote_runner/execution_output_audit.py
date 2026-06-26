from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifact_io import artifact_payload_stats


RUN_OUTPUT_AUDIT_SCHEMA_VERSION = "run-output-audit.v1"


def build_attempt_output_audit(
    *,
    run: dict[str, Any],
    attempts: list[dict[str, Any]],
    managed_work_dir: str | Path,
    managed_results_dir: str | Path,
) -> dict[str, Any]:
    latest = _latest_attempt_raw(attempts)
    base = {
        "schemaVersion": RUN_OUTPUT_AUDIT_SCHEMA_VERSION,
        "available": False,
        "pathExposed": False,
        "configAvailable": False,
        "expectedOutputCount": 0,
        "checkedOutputCount": 0,
        "existingOutputCount": 0,
        "missingOutputCount": 0,
        "verifiedOutputCount": 0,
        "checksumVerifiedOutputCount": 0,
        "rerunRequiredOutputCount": 0,
        "rerunRequired": False,
        "unsafeOutputCount": 0,
        "uncheckedOutputCount": 0,
        "unverifiedOutputCount": 0,
        "outputs": [],
    }
    if latest is None:
        return {**base, "reasonCode": "RUN_RESUME_NO_ATTEMPTS"}
    managed_work_root = Path(managed_work_dir).resolve(strict=False)
    managed_result_root = Path(managed_results_dir).resolve(strict=False)
    work_dir = _path_from(latest.get("workDir"))
    if work_dir is None:
        return {**base, "reasonCode": "WORKDIR_EVIDENCE_MISSING"}
    work_dir = work_dir.resolve(strict=False)
    if not _inside_any_root(work_dir, [managed_work_root]):
        return {**base, "reasonCode": "WORKDIR_OUTSIDE_MANAGED_ROOT"}
    config_path = work_dir / "run-config.json"
    if not config_path.exists():
        return {**base, "reasonCode": "RUN_CONFIG_NOT_FOUND"}
    config = _read_json_object(config_path)
    if config is None:
        return {**base, "configAvailable": True, "reasonCode": "RUN_CONFIG_INVALID"}
    outputs = config.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        return {**base, "configAvailable": True, "reasonCode": "RUN_CONFIG_OUTPUTS_MISSING"}

    safe_roots = _safe_roots(
        run=run,
        work_dir=work_dir,
        managed_result_root=managed_result_root,
    )
    audited = [_audit_output(name, value, work_dir=work_dir, safe_roots=safe_roots) for name, value in outputs.items()]
    existing_count = sum(1 for item in audited if item["state"] == "present")
    missing_count = sum(1 for item in audited if item["state"] == "missing")
    verified_count = sum(1 for item in audited if item.get("verificationState") == "verified")
    checksum_verified_count = sum(1 for item in audited if item.get("checksumVerified") is True)
    rerun_required_count = sum(1 for item in audited if item.get("rerunRequired") is True)
    unsafe_count = sum(1 for item in audited if item["state"] == "unsafe")
    unchecked_count = sum(1 for item in audited if item["state"] == "unchecked")
    unverified_count = sum(1 for item in audited if item.get("verificationState") == "unverified")
    checked_count = len(audited) - unchecked_count
    return {
        **base,
        "available": unsafe_count == 0 and unchecked_count == 0,
        "configAvailable": True,
        "expectedOutputCount": len(audited),
        "checkedOutputCount": checked_count,
        "existingOutputCount": existing_count,
        "missingOutputCount": missing_count,
        "verifiedOutputCount": verified_count,
        "checksumVerifiedOutputCount": checksum_verified_count,
        "rerunRequiredOutputCount": rerun_required_count,
        "rerunRequired": rerun_required_count > 0,
        "unsafeOutputCount": unsafe_count,
        "uncheckedOutputCount": unchecked_count,
        "unverifiedOutputCount": unverified_count,
        "reasonCode": _reason_code(
            existing_count=existing_count,
            missing_count=missing_count,
            verified_count=verified_count,
            rerun_required_count=rerun_required_count,
            unsafe_count=unsafe_count,
            unchecked_count=unchecked_count,
            unverified_count=unverified_count,
        ),
        "outputs": audited,
    }


def _audit_output(
    name: Any,
    value: Any,
    *,
    work_dir: Path,
    safe_roots: list[Path],
) -> dict[str, Any]:
    key = str(name or "").strip()
    if not isinstance(value, str):
        return _unchecked(key, "OUTPUT_REFERENCE_INVALID")
    raw_path = str(value or "").strip()
    if not key or not raw_path:
        return _unchecked(key, "OUTPUT_REFERENCE_INVALID")
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = work_dir / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return _unchecked(key, "OUTPUT_PATH_UNRESOLVABLE")
    if not _inside_any_root(resolved, safe_roots):
        return {
            "key": key,
            "state": "unsafe",
            "verificationState": "unverified",
            "pathExposed": False,
            "reasonCode": "OUTPUT_PATH_OUTSIDE_MANAGED_ROOT",
        }
    if not resolved.exists():
        return {
            "key": key,
            "state": "missing",
            "verificationState": "verified",
            "rerunRequired": True,
            "pathExposed": False,
            "reasonCode": "OUTPUT_MISSING_RERUN_REQUIRED",
        }
    try:
        size_bytes, _sha256 = artifact_payload_stats(resolved)
    except (OSError, ValueError):
        return _unchecked(key, "OUTPUT_PAYLOAD_CHECKSUM_UNAVAILABLE")
    return {
        "key": key,
        "state": "present",
        "verificationState": "verified",
        "checksumVerified": True,
        "checksumAlgorithm": "sha256",
        "sizeBytes": size_bytes,
        "pathExposed": False,
        "reasonCode": "OUTPUT_PRESENT_CHECKSUM_VERIFIED",
    }


def _safe_roots(
    *,
    run: dict[str, Any],
    work_dir: Path,
    managed_result_root: Path,
) -> list[Path]:
    roots = [work_dir.resolve(strict=False)]
    result_dir = _path_from(run.get("resultDir"))
    if result_dir is not None:
        resolved_result_dir = result_dir.resolve(strict=False)
        if _inside_any_root(resolved_result_dir, [managed_result_root]):
            roots.append(resolved_result_dir)
    roots.append(managed_result_root)
    return roots


def _reason_code(
    *,
    existing_count: int,
    missing_count: int,
    verified_count: int,
    rerun_required_count: int,
    unsafe_count: int,
    unchecked_count: int,
    unverified_count: int,
) -> str:
    if unsafe_count:
        return "OUTPUT_AUDIT_UNSAFE_REFERENCES"
    if unchecked_count:
        return "OUTPUT_AUDIT_UNCHECKED_REFERENCES"
    if unverified_count:
        return "OUTPUT_AUDIT_UNVERIFIED_OUTPUTS"
    if missing_count and rerun_required_count == missing_count:
        return "OUTPUT_AUDIT_RERUN_REQUIRED"
    if existing_count:
        return "OUTPUT_AUDIT_VERIFIED"
    if verified_count:
        return "OUTPUT_AUDIT_VERIFIED"
    return "OUTPUT_AUDIT_EMPTY"


def _unchecked(key: str, reason_code: str) -> dict[str, Any]:
    return {
        "key": key,
        "state": "unchecked",
        "verificationState": "unverified",
        "pathExposed": False,
        "reasonCode": reason_code,
    }


def _inside_any_root(path: Path, roots: list[Path]) -> bool:
    return any(root == path or root in path.parents for root in roots)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _path_from(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def _latest_attempt_raw(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not attempts:
        return None
    return max(
        attempts,
        key=lambda attempt: (
            _optional_int(attempt.get("attemptNumber")),
            _optional_int(attempt.get("leaseGeneration")),
            str(attempt.get("updatedAt") or ""),
        ),
    )


def _optional_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
