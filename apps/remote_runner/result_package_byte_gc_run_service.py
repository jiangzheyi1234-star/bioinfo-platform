from __future__ import annotations

from typing import Any, Literal

from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .governance_audit import record_governance_audit_event
from .result_package_byte_gc_preview_service import (
    RESULT_PACKAGE_BYTE_GC_PREVIEW_SCHEMA,
    ResultPackageByteGcPolicy,
    build_result_package_byte_gc_plan,
    public_result_package_byte_gc_item,
    result_package_byte_gc_policy_from_payload,
)
from .result_package_byte_gc_service import (
    RESULT_PACKAGE_BYTE_DELETE_CONFIRMATION,
    delete_retired_result_package_bytes,
)
from .storage_core import get_connection, now_iso


RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION: Literal["run-result-package-byte-gc"] = "run-result-package-byte-gc"
RESULT_PACKAGE_BYTE_GC_RUN_SCHEMA = "h2ometa.result-package-byte-gc-run.v1"
RESULT_PACKAGE_BYTE_GC_RUN_EVENT_TYPE = "result.package.bytes.gc.run.v1"
RESULT_PACKAGE_BYTE_GC_RUN_SCHEMA_NAME = "ResultPackageByteGcRunEvent"


def run_result_package_byte_gc(cfg: RemoteRunnerConfig, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = dict(payload or {})
    confirmation = str(body.get("confirmation") or "").strip()
    expected_fingerprint = str(body.get("planFingerprint") or "").strip()
    policy = result_package_byte_gc_policy_from_payload(body)
    plan = build_result_package_byte_gc_plan(cfg, policy)
    public_plan = plan["publicPlan"]
    if confirmation != RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION:
        _record_run_denial(
            cfg,
            policy=policy,
            public_plan=public_plan,
            reason_code="RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION_REQUIRED",
            fingerprint_provided=bool(expected_fingerprint),
        )
        raise ValueError("RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION_REQUIRED")
    if not expected_fingerprint:
        _record_run_denial(
            cfg,
            policy=policy,
            public_plan=public_plan,
            reason_code="RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_REQUIRED",
            fingerprint_provided=False,
        )
        raise ValueError("RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_REQUIRED")
    if expected_fingerprint != str(public_plan["planFingerprint"]):
        _record_run_denial(
            cfg,
            policy=policy,
            public_plan=public_plan,
            reason_code="RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_MISMATCH",
            fingerprint_provided=True,
        )
        raise ValueError("RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_MISMATCH")

    executed_at = now_iso()
    deleted: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    evidence_ids: list[str] = []
    for index, item in enumerate(plan["candidates"]):
        try:
            deletion = delete_retired_result_package_bytes(
                cfg,
                item["resultId"],
                item["packageExportId"],
                confirmation=RESULT_PACKAGE_BYTE_DELETE_CONFIRMATION,
                actor=policy.actor,
                reason=policy.reason,
            )
            evidence_ids.append(str(deletion.get("evidenceId") or ""))
            deleted.append(
                {
                    **item,
                    "itemIndex": index,
                    "packageBytesState": "deleted",
                    "packageFileDeleted": True,
                    "deletedAt": str(deletion.get("deletedAt") or ""),
                    "evidenceId": str(deletion.get("evidenceId") or ""),
                }
            )
        except Exception as exc:
            errors.append(_public_error(index, item, exc))
            break

    evidence = _record_run_evidence(
        cfg,
        policy=policy,
        public_plan=public_plan,
        deleted=deleted,
        errors=errors,
        evidence_ids=evidence_ids,
        executed_at=executed_at,
    )
    decision = "error" if errors else "allow"
    record_governance_audit_event(
        cfg,
        action="result.package.bytes.run",
        subject_kind="result_package_export",
        subject_id="byte-gc-run",
        actor=policy.actor,
        decision=decision,
        reason_code="RESULT_PACKAGE_BYTE_GC_RUN_DELETE_FAILED" if errors else "",
        details={
            **_audit_details(public_plan),
            "deletedCount": len(deleted),
            "deletedBytes": sum(int(item.get("sizeBytes") or 0) for item in deleted),
            "errorCount": len(errors),
            "evidenceId": evidence["eventId"],
        },
    )
    result = _public_run_result(
        public_plan=public_plan,
        deleted=deleted,
        errors=errors,
        evidence_id=evidence["eventId"],
        executed_at=executed_at,
    )
    if errors:
        raise ValueError("RESULT_PACKAGE_BYTE_GC_RUN_DELETE_FAILED")
    return result


def _record_run_denial(
    cfg: RemoteRunnerConfig,
    *,
    policy: ResultPackageByteGcPolicy,
    public_plan: dict[str, Any],
    reason_code: str,
    fingerprint_provided: bool,
) -> None:
    record_governance_audit_event(
        cfg,
        action="result.package.bytes.run",
        subject_kind="result_package_export",
        subject_id="byte-gc-run",
        actor=policy.actor,
        decision="deny",
        reason_code=reason_code,
        details={
            **_audit_details(public_plan),
            "fingerprintProvided": fingerprint_provided,
            "fingerprintMatched": False,
            "deletedCount": 0,
            "deletedBytes": 0,
        },
    )


def _record_run_evidence(
    cfg: RemoteRunnerConfig,
    *,
    policy: ResultPackageByteGcPolicy,
    public_plan: dict[str, Any],
    deleted: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    evidence_ids: list[str],
    executed_at: str,
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type=RESULT_PACKAGE_BYTE_GC_RUN_EVENT_TYPE,
            schema_name=RESULT_PACKAGE_BYTE_GC_RUN_SCHEMA_NAME,
            subject_kind="result_package_export",
            subject_id="byte-gc-run",
            payload={
                "schemaVersion": RESULT_PACKAGE_BYTE_GC_RUN_SCHEMA,
                "previewSchemaVersion": RESULT_PACKAGE_BYTE_GC_PREVIEW_SCHEMA,
                "actor": policy.actor,
                "reasonProvided": policy.reason_provided,
                "reasonRedacted": True,
                "executedAt": executed_at,
                "status": "failed" if errors else "completed",
                "planFingerprint": public_plan["planFingerprint"],
                "candidateCount": public_plan["candidateCount"],
                "deleteBytes": public_plan["deleteBytes"],
                "protectedCount": public_plan["protectedCount"],
                "deletedCount": len(deleted),
                "deletedBytes": sum(int(item.get("sizeBytes") or 0) for item in deleted),
                "errorCount": len(errors),
                "reasonCounts": public_plan["reasonCounts"],
                "deletedEvidenceIds": [value for value in evidence_ids if value],
                "errors": errors,
            },
            schema_version="v1",
            producer="result_package_byte_gc_run_service",
            occurred_at=executed_at,
        )
        connection.commit()
    return event


def _public_run_result(
    *,
    public_plan: dict[str, Any],
    deleted: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    evidence_id: str,
    executed_at: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": RESULT_PACKAGE_BYTE_GC_RUN_SCHEMA,
        "executedAt": executed_at,
        "status": "failed" if errors else "completed",
        "planFingerprint": public_plan["planFingerprint"],
        "deletedCount": len(deleted),
        "deletedBytes": sum(int(item.get("sizeBytes") or 0) for item in deleted),
        "errorCount": len(errors),
        "evidenceId": evidence_id,
        "deleteConfirmationAccepted": True,
        "deleted": [_public_deleted_item(index, item) for index, item in enumerate(deleted)],
        "errors": errors,
        "plan": public_plan,
        "redactionPolicy": public_plan["redactionPolicy"],
    }


def _public_deleted_item(index: int, item: dict[str, Any]) -> dict[str, Any]:
    public = public_result_package_byte_gc_item(index, item)
    public["packageFileDeleted"] = bool(item.get("packageFileDeleted"))
    public["evidenceId"] = str(item.get("evidenceId") or "")
    return public


def _public_error(index: int, item: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {
        "itemIndex": index,
        "classification": "error",
        "reason": "delete_failed",
        "errorCode": _stable_error_code(exc),
        "artifactPayloadMode": str(item.get("artifactPayloadMode") or ""),
        "lifecycleState": str(item.get("lifecycleState") or ""),
        "packageBytesState": str(item.get("packageBytesState") or ""),
        "sizeBytes": int(item.get("sizeBytes") or 0),
    }


def _stable_error_code(exc: Exception) -> str:
    message = str(exc or "").strip()
    code = message.split(":", 1)[0].strip()
    if code.startswith("RESULT_PACKAGE_"):
        return code
    return f"RESULT_PACKAGE_BYTE_GC_RUN_{exc.__class__.__name__.upper()}"


def _audit_details(public_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": RESULT_PACKAGE_BYTE_GC_RUN_SCHEMA,
        "previewSchemaVersion": RESULT_PACKAGE_BYTE_GC_PREVIEW_SCHEMA,
        "retentionDays": public_plan["policy"]["retentionDays"],
        "maxDeleteBytesProvided": public_plan["policy"]["maxDeleteBytes"] is not None,
        "scanLimit": public_plan["policy"]["scanLimit"],
        "scannedCount": public_plan["scannedCount"],
        "candidateCount": public_plan["candidateCount"],
        "deleteBytes": public_plan["deleteBytes"],
        "protectedCount": public_plan["protectedCount"],
        "protectedBytes": public_plan["protectedBytes"],
        "planFingerprint": public_plan["planFingerprint"],
        "reasonCounts": public_plan["reasonCounts"],
    }
