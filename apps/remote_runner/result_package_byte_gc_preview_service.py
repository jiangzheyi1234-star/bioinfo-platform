from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .result_package_storage import list_result_package_exports_for_byte_gc
from .storage_core import now_iso


RESULT_PACKAGE_BYTE_GC_PREVIEW_SCHEMA = "h2ometa.result-package-byte-gc-preview.v1"
DEFAULT_RESULT_PACKAGE_BYTE_GC_REASON = "retired_export_bytes"


@dataclass(frozen=True)
class ResultPackageByteGcPolicy:
    retention_days: int
    max_delete_bytes: int | None
    reason: str
    actor: str
    scan_limit: int


def preview_result_package_byte_gc(cfg: RemoteRunnerConfig, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = _policy_from_payload(payload)
    previewed_at = now_iso()
    cutoff_at = _format_utc(_utc_now() - timedelta(days=policy.retention_days))
    records = list_result_package_exports_for_byte_gc(cfg, limit=policy.scan_limit)
    candidates: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    for record in records:
        item = _classify_export(cfg, record, cutoff_at=cutoff_at)
        if item["classification"] == "candidate":
            candidates.append(item)
        else:
            protected.append(item)
    selected = _apply_max_delete_bytes(candidates, policy.max_delete_bytes)
    limited = [item for item in candidates if item not in selected]
    protected.extend({**item, "classification": "protected", "reason": "max_delete_bytes_limited"} for item in limited)
    plan = _public_preview(
        previewed_at=previewed_at,
        cutoff_at=cutoff_at,
        policy=policy,
        candidates=selected,
        protected=protected,
        scanned_count=len(records),
    )
    record_governance_audit_event(
        cfg,
        action="result.package.bytes.preview",
        subject_kind="result_package_export",
        subject_id="byte-gc-preview",
        actor=policy.actor,
        details={
            "schemaVersion": RESULT_PACKAGE_BYTE_GC_PREVIEW_SCHEMA,
            "retentionDays": policy.retention_days,
            "maxDeleteBytesProvided": policy.max_delete_bytes is not None,
            "scanLimit": policy.scan_limit,
            "scannedCount": len(records),
            "candidateCount": plan["candidateCount"],
            "deleteBytes": plan["deleteBytes"],
            "protectedCount": plan["protectedCount"],
            "planFingerprint": plan["planFingerprint"],
            "reasonCounts": plan["reasonCounts"],
        },
    )
    return plan


def _classify_export(cfg: RemoteRunnerConfig, record: dict[str, Any], *, cutoff_at: str) -> dict[str, Any]:
    base = {
        "packageExportId": str(record.get("packageExportId") or ""),
        "resultId": str(record.get("resultId") or ""),
        "runId": str(record.get("runId") or ""),
        "artifactPayloadMode": str(record.get("artifactPayloadMode") or ""),
        "lifecycleState": str(record.get("lifecycleState") or ""),
        "packageBytesState": str(record.get("packageBytesState") or ""),
        "sizeBytes": int(record.get("sizeBytes") or 0),
        "retiredAtPresent": bool(str(record.get("retiredAt") or "").strip()),
        "createdAtPresent": bool(str(record.get("createdAt") or "").strip()),
    }
    if base["lifecycleState"] != "retired":
        return {**base, "classification": "protected", "reason": f"lifecycle_{base['lifecycleState'] or 'unknown'}"}
    if base["packageBytesState"] != "available":
        return {**base, "classification": "protected", "reason": f"bytes_{base['packageBytesState'] or 'unknown'}"}
    retired_at = str(record.get("retiredAt") or "").strip()
    if not retired_at:
        return {**base, "classification": "protected", "reason": "retired_time_missing"}
    if retired_at > cutoff_at:
        return {**base, "classification": "protected", "reason": "retention_window_active"}
    try:
        package = _validate_managed_package_file(cfg, record)
    except ValueError as exc:
        return {**base, "classification": "protected", "reason": str(exc)}
    return {
        **base,
        "classification": "candidate",
        "reason": "retired_bytes_eligible",
        "verifiedSizeBytes": int(package["sizeBytes"]),
        "checksumVerified": True,
    }


def _validate_managed_package_file(cfg: RemoteRunnerConfig, record: dict[str, Any]) -> dict[str, Any]:
    package_path = Path(str(record.get("packagePath") or "")).resolve()
    managed_root = (Path(cfg.results_dir) / "packages").resolve()
    if not _is_relative_to(package_path, managed_root):
        raise ValueError("package_path_unmanaged")
    if not package_path.is_file():
        raise ValueError("package_file_missing")
    size_bytes = package_path.stat().st_size
    if size_bytes != int(record.get("sizeBytes") or 0):
        raise ValueError("package_size_mismatch")
    if _file_sha256(package_path) != str(record.get("sha256") or ""):
        raise ValueError("package_checksum_mismatch")
    return {"sizeBytes": size_bytes}


def _public_preview(
    *,
    previewed_at: str,
    cutoff_at: str,
    policy: ResultPackageByteGcPolicy,
    candidates: list[dict[str, Any]],
    protected: list[dict[str, Any]],
    scanned_count: int,
) -> dict[str, Any]:
    public_candidates = [_public_item(index, item) for index, item in enumerate(candidates)]
    public_protected = [_public_item(index, item) for index, item in enumerate(protected)]
    delete_bytes = sum(int(item.get("sizeBytes") or 0) for item in candidates)
    reason_counts = _reason_counts([*public_candidates, *public_protected])
    fingerprint_payload = {
        "schemaVersion": RESULT_PACKAGE_BYTE_GC_PREVIEW_SCHEMA,
        "cutoffAt": cutoff_at,
        "retentionDays": policy.retention_days,
        "maxDeleteBytes": policy.max_delete_bytes,
        "candidateSet": [
            {
                "packageExportId": item["packageExportId"],
                "sizeBytes": item["sizeBytes"],
                "reason": item["reason"],
            }
            for item in candidates
        ],
        "protectedReasons": reason_counts,
    }
    return {
        "schemaVersion": RESULT_PACKAGE_BYTE_GC_PREVIEW_SCHEMA,
        "previewedAt": previewed_at,
        "cutoffAt": cutoff_at,
        "planFingerprint": _digest_json(fingerprint_payload),
        "policy": {
            "retentionDays": policy.retention_days,
            "maxDeleteBytes": policy.max_delete_bytes,
            "reasonProvided": bool(policy.reason),
            "reasonRedacted": True,
            "scanLimit": policy.scan_limit,
            "deletionAuthorized": False,
            "deleteConfirmationAccepted": False,
        },
        "scannedCount": scanned_count,
        "candidateCount": len(public_candidates),
        "deleteBytes": delete_bytes,
        "protectedCount": len(public_protected),
        "protectedBytes": sum(int(item.get("sizeBytes") or 0) for item in protected),
        "reasonCounts": reason_counts,
        "candidates": public_candidates,
        "protected": public_protected,
        "redactionPolicy": {
            "packageExportIdsExposed": False,
            "resultIdsExposed": False,
            "runIdsExposed": False,
            "pathsExposed": False,
            "storageUrisExposed": False,
            "sha256Exposed": False,
        },
    }


def _public_item(index: int, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "itemIndex": index,
        "classification": str(item.get("classification") or ""),
        "reason": str(item.get("reason") or ""),
        "artifactPayloadMode": str(item.get("artifactPayloadMode") or ""),
        "lifecycleState": str(item.get("lifecycleState") or ""),
        "packageBytesState": str(item.get("packageBytesState") or ""),
        "sizeBytes": int(item.get("sizeBytes") or 0),
        "retiredAtPresent": bool(item.get("retiredAtPresent")),
        "checksumVerified": bool(item.get("checksumVerified")),
    }


def _apply_max_delete_bytes(candidates: list[dict[str, Any]], max_delete_bytes: int | None) -> list[dict[str, Any]]:
    if max_delete_bytes is None:
        return list(candidates)
    selected: list[dict[str, Any]] = []
    total = 0
    for item in candidates:
        size = int(item.get("sizeBytes") or 0)
        if total + size > max_delete_bytes:
            continue
        selected.append(item)
        total += size
    return selected


def _policy_from_payload(payload: dict[str, Any] | None) -> ResultPackageByteGcPolicy:
    body = dict(payload or {})
    return ResultPackageByteGcPolicy(
        retention_days=_non_negative_int(body.get("retentionDays", 30), "RESULT_PACKAGE_BYTE_GC_RETENTION_INVALID"),
        max_delete_bytes=_optional_positive_int(
            body.get("maxDeleteBytes"),
            "RESULT_PACKAGE_BYTE_GC_MAX_DELETE_BYTES_INVALID",
        ),
        reason=str(body.get("reason") or DEFAULT_RESULT_PACKAGE_BYTE_GC_REASON).strip()
        or DEFAULT_RESULT_PACKAGE_BYTE_GC_REASON,
        actor=str(body.get("actor") or "remote-runner-api").strip() or "remote-runner-api",
        scan_limit=_bounded_scan_limit(body.get("scanLimit", 1000)),
    )


def _non_negative_int(value: Any, code: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if integer < 0:
        raise ValueError(code)
    return integer


def _optional_positive_int(value: Any, code: str) -> int | None:
    if value is None:
        return None
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if integer < 1:
        raise ValueError(code)
    return integer


def _bounded_scan_limit(value: Any) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("RESULT_PACKAGE_BYTE_GC_SCAN_LIMIT_INVALID") from exc
    if integer < 1 or integer > 5000:
        raise ValueError("RESULT_PACKAGE_BYTE_GC_SCAN_LIMIT_INVALID")
    return integer


def _reason_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        reason = str(item.get("reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _digest_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
