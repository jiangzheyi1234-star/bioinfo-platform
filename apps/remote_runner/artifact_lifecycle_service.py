from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .artifact_cache_storage import active_artifact_cache_pin_reasons, artifact_cache_storage_ref_key
from .artifact_io import artifact_local_path, delete_artifact_payload
from .artifact_lifecycle_storage import (
    TERMINAL_RUN_STATUSES,
    lifecycle_reference_reasons,
    list_artifact_lifecycle_rows,
    list_ledger_only_materialization_rows,
    mark_lifecycle_deleted,
)
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .governance_audit import record_governance_audit_event
from .storage_core import get_connection, now_iso


ARTIFACT_GC_EVENT_TYPE = "artifact.gc.v1"
ARTIFACT_GC_SCHEMA_NAME = "ArtifactGarbageCollectionEvent"
ARTIFACT_GC_CONFIRMATION = "delete-artifact-payloads"
ARTIFACT_LIFECYCLE_USAGE_SCHEMA = "h2ometa.artifact-lifecycle-usage.v1"
ARTIFACT_GC_PLAN_SCHEMA = "h2ometa.artifact-gc-plan.v1"
ARTIFACT_GC_PUBLIC_PLAN_SCHEMA = "h2ometa.artifact-gc-public-plan.v1"
ARTIFACT_GC_PUBLIC_RUN_SCHEMA = "h2ometa.artifact-gc-public-run.v1"
DEFAULT_GC_REASON = "retention_expired"


@dataclass(frozen=True)
class GcPolicy:
    retention_days: int
    run_statuses: set[str]
    max_delete_bytes: int | None
    reason: str
    actor: str


def build_artifact_lifecycle_usage(
    cfg: RemoteRunnerConfig,
    *,
    quota_bytes: int | None = None,
) -> dict[str, Any]:
    checked_at = now_iso()
    artifact_rows = list_artifact_lifecycle_rows(cfg)
    ledger_only_rows = list_ledger_only_materialization_rows(cfg)
    active_groups = _unique_storage_groups(
        row for row in artifact_rows if str(row.get("lifecycleState") or "active") == "active"
    )
    deleted_groups = _unique_storage_groups(
        row for row in artifact_rows if str(row.get("lifecycleState") or "") == "deleted"
    )
    ledger_only_groups = _unique_storage_groups(
        row for row in ledger_only_rows if str(row.get("lifecycleState") or "active") == "active"
    )
    active_bytes = sum(int(group["sizeBytes"]) for group in active_groups.values())
    deleted_bytes = sum(int(group["sizeBytes"]) for group in deleted_groups.values())
    ledger_only_bytes = sum(int(group["sizeBytes"]) for group in ledger_only_groups.values())
    usage = {
        "schemaVersion": ARTIFACT_LIFECYCLE_USAGE_SCHEMA,
        "checkedAt": checked_at,
        "artifactCount": len(artifact_rows),
        "activeArtifactCount": sum(1 for row in artifact_rows if row["lifecycleState"] == "active"),
        "deletedArtifactCount": sum(1 for row in artifact_rows if row["lifecycleState"] == "deleted"),
        "activeStorageObjectCount": len(active_groups),
        "activeBytes": active_bytes,
        "deletedBytes": deleted_bytes,
        "ledgerOnlyMaterializationCount": len(ledger_only_rows),
        "ledgerOnlyActiveBytes": ledger_only_bytes,
        "byBackend": _usage_by_backend(active_groups),
    }
    if quota_bytes is not None:
        quota = max(0, int(quota_bytes))
        usage["quota"] = {
            "quotaBytes": quota,
            "usedBytes": active_bytes,
            "remainingBytes": max(0, quota - active_bytes),
            "overageBytes": max(0, active_bytes - quota),
            "usedPercent": round((active_bytes / quota) * 100, 2) if quota else None,
        }
    return usage


def build_governed_artifact_lifecycle_usage(
    cfg: RemoteRunnerConfig,
    *,
    quota_bytes: int | None = None,
) -> dict[str, Any]:
    usage = build_artifact_lifecycle_usage(cfg, quota_bytes=quota_bytes)
    record_governance_audit_event(
        cfg,
        action="artifact.lifecycle.usage.read",
        subject_kind="artifact_lifecycle_usage",
        subject_id="usage",
        actor=cfg.api_token_actor or "remote-runner-api",
        details=_usage_audit_details(usage, quota_provided=quota_bytes is not None),
    )
    return usage


def preview_artifact_gc(cfg: RemoteRunnerConfig, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = _policy_from_payload(payload)
    plan = _build_gc_plan(cfg, policy)
    record_governance_audit_event(
        cfg,
        action="artifact.gc.preview",
        subject_kind="artifact_gc",
        subject_id=plan["planId"],
        actor=policy.actor,
        details=_audit_details(plan),
    )
    return plan


def public_artifact_gc_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": ARTIFACT_GC_PUBLIC_PLAN_SCHEMA,
        "planId": str(plan.get("planId") or ""),
        "plannedAt": str(plan.get("plannedAt") or ""),
        "cutoffAt": str(plan.get("cutoffAt") or ""),
        "policy": _public_gc_policy(plan.get("policy") if isinstance(plan.get("policy"), dict) else {}),
        "candidateCount": int(plan.get("candidateCount") or 0),
        "deleteBytes": int(plan.get("deleteBytes") or 0),
        "protectedCount": int(plan.get("protectedCount") or 0),
        "protectedBytes": int(plan.get("protectedBytes") or 0),
        "candidates": [_public_gc_plan_item(item) for item in plan.get("candidates") or []],
        "protected": [_public_gc_plan_item(item, protected_item=True) for item in plan.get("protected") or []],
    }


def public_artifact_gc_run_result(result: dict[str, Any]) -> dict[str, Any]:
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
    return {
        "schemaVersion": ARTIFACT_GC_PUBLIC_RUN_SCHEMA,
        "planId": str(result.get("planId") or ""),
        "executedAt": str(result.get("executedAt") or ""),
        "status": str(result.get("status") or ""),
        "deletedCount": int(result.get("deletedCount") or 0),
        "deletedBytes": int(result.get("deletedBytes") or 0),
        "errorCount": len(result.get("errors") or []),
        "evidenceId": str(result.get("evidenceId") or ""),
        "deleted": [_public_gc_plan_item(item) for item in result.get("deleted") or []],
        "errors": [_public_gc_error(item) for item in result.get("errors") or []],
        "plan": public_artifact_gc_plan(plan),
    }


def run_artifact_gc(cfg: RemoteRunnerConfig, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = dict(payload or {})
    confirmation = str(body.get("confirmation") or "").strip()
    policy = _policy_from_payload(body)
    plan = _build_gc_plan(cfg, policy)
    if confirmation != ARTIFACT_GC_CONFIRMATION:
        record_governance_audit_event(
            cfg,
            action="artifact.gc.run",
            subject_kind="artifact_gc",
            subject_id=plan["planId"],
            actor=policy.actor,
            decision="deny",
            reason_code="ARTIFACT_GC_CONFIRMATION_REQUIRED",
            details=_audit_details(plan),
        )
        raise ValueError("ARTIFACT_GC_CONFIRMATION_REQUIRED")

    deleted: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    executed_at = now_iso()
    for item in plan["candidates"]:
        try:
            _require_candidate_not_pinned(cfg, item)
            deletion = delete_artifact_payload(cfg, item)
            _mark_candidate_deleted(cfg, item, deleted_at=executed_at, reason=policy.reason)
            deleted.append({**item, "payloadDeleted": bool(deletion["deleted"])})
        except Exception as exc:
            errors.append(
                {
                    "storageBackend": item["storageBackend"],
                    "storageUri": item["storageUri"],
                    "sha256": item["sha256"],
                    "error": str(exc) or exc.__class__.__name__,
                }
            )
            break

    event = _record_gc_evidence(
        cfg,
        plan=plan,
        deleted=deleted,
        errors=errors,
        executed_at=executed_at,
        actor=policy.actor,
    )
    decision = "error" if errors else "allow"
    record_governance_audit_event(
        cfg,
        action="artifact.gc.run",
        subject_kind="artifact_gc",
        subject_id=plan["planId"],
        actor=policy.actor,
        decision=decision,
        reason_code="ARTIFACT_GC_DELETE_FAILED" if errors else "",
        details={
            **_audit_details(plan),
            "deletedCount": len(deleted),
            "deletedBytes": sum(int(item["sizeBytes"]) for item in deleted),
            "errorCount": len(errors),
            "evidenceId": event["eventId"],
        },
    )
    result = {
        "schemaVersion": ARTIFACT_GC_PLAN_SCHEMA,
        "planId": plan["planId"],
        "executedAt": executed_at,
        "status": "failed" if errors else "completed",
        "deletedCount": len(deleted),
        "deletedBytes": sum(int(item["sizeBytes"]) for item in deleted),
        "deleted": deleted,
        "errors": errors,
        "evidenceId": event["eventId"],
        "plan": plan,
    }
    if errors:
        raise ValueError("ARTIFACT_GC_DELETE_FAILED")
    return result


def _build_gc_plan(cfg: RemoteRunnerConfig, policy: GcPolicy) -> dict[str, Any]:
    planned_at = now_iso()
    cutoff = _utc_now() - timedelta(days=policy.retention_days)
    rows = list_artifact_lifecycle_rows(cfg)
    ref_reasons = lifecycle_reference_reasons(cfg)
    cache_pin_reasons = active_artifact_cache_pin_reasons(cfg)
    groups = _unique_storage_groups(rows)
    candidates: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    for group in groups.values():
        active_records = [row for row in group["records"] if row["lifecycleState"] == "active"]
        if not active_records:
            protected.append(_protected_item(group, ["already_deleted"]))
            continue
        reasons = sorted(
            {
                reason
                for row in active_records
                for reason in _record_protection_reasons(
                    cfg,
                    row,
                    policy=policy,
                    cutoff=cutoff,
                    ref_reasons=ref_reasons,
                    cache_pin_reasons=cache_pin_reasons,
                )
            }
        )
        if reasons:
            protected.append(_protected_item(group, reasons))
            continue
        candidates.append(_candidate_item(group, policy=policy))

    candidates, max_protected = _apply_max_delete_bytes(candidates, policy.max_delete_bytes)
    protected.extend(max_protected)
    candidates.sort(key=lambda item: (str(item["terminalAt"] or ""), str(item["storageUri"])))
    protected.sort(key=lambda item: (",".join(item["reasons"]), str(item["storageUri"])))
    delete_bytes = sum(int(item["sizeBytes"]) for item in candidates)
    plan = {
        "schemaVersion": ARTIFACT_GC_PLAN_SCHEMA,
        "planId": _plan_id(planned_at, policy, candidates, protected),
        "plannedAt": planned_at,
        "cutoffAt": _format_dt(cutoff),
        "policy": {
            "retentionDays": policy.retention_days,
            "eligibleRunStatuses": sorted(policy.run_statuses),
            "maxDeleteBytes": policy.max_delete_bytes,
            "reason": policy.reason,
        },
        "candidateCount": len(candidates),
        "deleteBytes": delete_bytes,
        "protectedCount": len(protected),
        "protectedBytes": sum(int(item["sizeBytes"]) for item in protected),
        "candidates": candidates,
        "protected": protected,
    }
    return plan


def _record_protection_reasons(
    cfg: RemoteRunnerConfig,
    row: dict[str, Any],
    *,
    policy: GcPolicy,
    cutoff: datetime,
    ref_reasons: dict[str, set[str]],
    cache_pin_reasons: dict[str, set[str]],
) -> list[str]:
    reasons: list[str] = []
    run_id = str(row.get("runId") or "").strip()
    run_status = str(row.get("runStatus") or "").strip()
    if not run_status:
        reasons.append("run_missing")
    elif run_status not in TERMINAL_RUN_STATUSES:
        reasons.append("run_not_terminal")
    elif run_status not in policy.run_statuses:
        reasons.append("status_not_selected")
    reasons.extend(sorted(ref_reasons.get(run_id, set())))
    reasons.extend(sorted(cache_pin_reasons.get(_storage_ref_key(row), set())))
    terminal_at = _terminal_at(row)
    if terminal_at is None:
        reasons.append("terminal_time_missing")
    elif terminal_at > cutoff:
        reasons.append("retention_window")
    materialization_state = str(row.get("materializationLifecycleState") or "")
    if materialization_state and materialization_state != "active":
        reasons.append("materialization_not_active")
    reasons.extend(_storage_safety_reasons(cfg, row))
    return reasons


def _require_candidate_not_pinned(cfg: RemoteRunnerConfig, item: dict[str, Any]) -> None:
    reasons = active_artifact_cache_pin_reasons(cfg).get(
        artifact_cache_storage_ref_key(
            str(item.get("storageBackend") or ""),
            str(item.get("storageUri") or ""),
            str(item.get("sha256") or ""),
        ),
        set(),
    )
    if reasons:
        raise ValueError(f"ARTIFACT_GC_CANDIDATE_PINNED: {','.join(sorted(reasons))}")


def _storage_safety_reasons(cfg: RemoteRunnerConfig, row: dict[str, Any]) -> list[str]:
    backend = str(row.get("storageBackend") or "local").strip()
    if backend == "local":
        try:
            path = artifact_local_path(row).resolve()
        except ValueError:
            return ["storage_uri_invalid"]
        if not _is_managed_local_path(cfg, path):
            return ["unmanaged_local_path"]
        if path.exists() and path.is_dir():
            return ["directory_artifact_unsupported"]
        if path.exists() and not path.is_file():
            return ["local_path_unsupported"]
        return []
    if backend == "s3":
        return [] if _is_managed_s3_uri(cfg, str(row.get("storageUri") or "")) else ["unmanaged_s3_object"]
    return ["storage_backend_unsupported"]


def _storage_ref_key(row: dict[str, Any]) -> str:
    return artifact_cache_storage_ref_key(
        str(row.get("storageBackend") or ""),
        str(row.get("storageUri") or ""),
        str(row.get("sha256") or ""),
    )


def _candidate_item(group: dict[str, Any], *, policy: GcPolicy) -> dict[str, Any]:
    records = group["records"]
    terminal_values = [_terminal_at(row) for row in records]
    terminal_at = min((value for value in terminal_values if value is not None), default=None)
    retention_until = _format_dt(terminal_at + timedelta(days=policy.retention_days)) if terminal_at else ""
    return {
        "groupId": group["groupId"],
        "storageBackend": group["storageBackend"],
        "storageUri": group["storageUri"],
        "path": group["path"],
        "sha256": group["sha256"],
        "sizeBytes": group["sizeBytes"],
        "artifactIds": sorted({row["artifactId"] for row in records}),
        "runIds": sorted({row["runId"] for row in records}),
        "materializationIds": sorted(
            {str(row.get("materializationId") or "") for row in records if row.get("materializationId")}
        ),
        "terminalAt": _format_dt(terminal_at) if terminal_at else "",
        "retentionUntil": retention_until,
        "reason": policy.reason,
    }


def _protected_item(group: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    records = group["records"]
    return {
        "groupId": group["groupId"],
        "storageBackend": group["storageBackend"],
        "storageUri": group["storageUri"],
        "path": group["path"],
        "sha256": group["sha256"],
        "sizeBytes": group["sizeBytes"],
        "artifactIds": sorted({row["artifactId"] for row in records if row.get("artifactId")}),
        "runIds": sorted({row["runId"] for row in records if row.get("runId")}),
        "materializationIds": sorted({str(row.get("materializationId") or "") for row in records if row.get("materializationId")}),
        "reasons": reasons,
    }


def _mark_candidate_deleted(
    cfg: RemoteRunnerConfig,
    item: dict[str, Any],
    *,
    deleted_at: str,
    reason: str,
) -> None:
    with get_connection(cfg) as connection:
        mark_lifecycle_deleted(
            connection,
            artifact_ids=list(item.get("artifactIds") or []),
            storage_backend=str(item["storageBackend"]),
            storage_uri=str(item["storageUri"]),
            sha256=str(item["sha256"]),
            deleted_at=deleted_at,
            reason=reason,
            retention_until=str(item.get("retentionUntil") or ""),
        )
        connection.commit()


def _record_gc_evidence(
    cfg: RemoteRunnerConfig,
    *,
    plan: dict[str, Any],
    deleted: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    executed_at: str,
    actor: str,
) -> dict[str, Any]:
    payload = {
        "schemaVersion": ARTIFACT_GC_PLAN_SCHEMA,
        "planId": plan["planId"],
        "actor": actor,
        "executedAt": executed_at,
        "status": "failed" if errors else "completed",
        "deletedCount": len(deleted),
        "deletedBytes": sum(int(item["sizeBytes"]) for item in deleted),
        "errors": errors,
        "policy": dict(plan["policy"]),
        "deleted": [
            {
                "storageBackend": item["storageBackend"],
                "storageUri": item["storageUri"],
                "sha256": item["sha256"],
                "sizeBytes": item["sizeBytes"],
                "artifactIds": list(item["artifactIds"]),
                "runIds": list(item["runIds"]),
                "payloadDeleted": bool(item["payloadDeleted"]),
            }
            for item in deleted
        ],
    }
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type=ARTIFACT_GC_EVENT_TYPE,
            schema_name=ARTIFACT_GC_SCHEMA_NAME,
            subject_kind="artifact_gc",
            subject_id=str(plan["planId"]),
            payload=payload,
            producer="artifact_lifecycle_service",
            occurred_at=executed_at,
        )
        connection.commit()
    return event


def _policy_from_payload(payload: dict[str, Any] | None) -> GcPolicy:
    body = dict(payload or {})
    statuses = {
        str(item or "").strip()
        for item in body.get("eligibleRunStatuses", sorted(TERMINAL_RUN_STATUSES))
        if str(item or "").strip()
    }
    invalid = statuses - TERMINAL_RUN_STATUSES
    if invalid:
        raise ValueError(f"ARTIFACT_GC_STATUS_UNSUPPORTED: {sorted(invalid)[0]}")
    if not statuses:
        raise ValueError("ARTIFACT_GC_STATUS_REQUIRED")
    max_delete = body.get("maxDeleteBytes")
    return GcPolicy(
        retention_days=max(0, int(body.get("retentionDays", 30))),
        run_statuses=statuses,
        max_delete_bytes=int(max_delete) if max_delete is not None else None,
        reason=str(body.get("reason") or DEFAULT_GC_REASON).strip() or DEFAULT_GC_REASON,
        actor=str(body.get("actor") or "remote-runner-api").strip() or "remote-runner-api",
    )


def _unique_storage_groups(rows: Any) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        backend = str(row.get("storageBackend") or "local")
        storage_uri = str(row.get("storageUri") or "")
        sha256 = str(row.get("sha256") or "")
        group_id = _group_id(backend, storage_uri, sha256)
        group = groups.setdefault(
            group_id,
            {
                "groupId": group_id,
                "storageBackend": backend,
                "storageUri": storage_uri,
                "path": str(row.get("path") or row.get("localPath") or ""),
                "sha256": sha256,
                "sizeBytes": int(row.get("sizeBytes") or 0),
                "records": [],
            },
        )
        group["sizeBytes"] = max(int(group["sizeBytes"]), int(row.get("sizeBytes") or 0))
        group["records"].append(row)
    return groups


def _usage_by_backend(groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_backend: dict[str, dict[str, int]] = {}
    for group in groups.values():
        backend = str(group["storageBackend"])
        summary = by_backend.setdefault(backend, {"storageObjectCount": 0, "bytes": 0})
        summary["storageObjectCount"] += 1
        summary["bytes"] += int(group["sizeBytes"])
    return by_backend


def _usage_audit_details(usage: dict[str, Any], *, quota_provided: bool) -> dict[str, Any]:
    details = {
        "artifactCount": int(usage.get("artifactCount") or 0),
        "activeArtifactCount": int(usage.get("activeArtifactCount") or 0),
        "deletedArtifactCount": int(usage.get("deletedArtifactCount") or 0),
        "activeStorageObjectCount": int(usage.get("activeStorageObjectCount") or 0),
        "activeBytes": int(usage.get("activeBytes") or 0),
        "deletedBytes": int(usage.get("deletedBytes") or 0),
        "ledgerOnlyMaterializationCount": int(usage.get("ledgerOnlyMaterializationCount") or 0),
        "ledgerOnlyActiveBytes": int(usage.get("ledgerOnlyActiveBytes") or 0),
        "quotaProvided": bool(quota_provided),
    }
    quota = usage.get("quota") if isinstance(usage.get("quota"), dict) else {}
    if quota:
        details.update(
            {
                "quotaBytes": int(quota.get("quotaBytes") or 0),
                "quotaOverageBytes": int(quota.get("overageBytes") or 0),
            }
        )
    return details


def _public_gc_policy(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "retentionDays": int(policy.get("retentionDays") or 0),
        "eligibleRunStatuses": [str(item) for item in policy.get("eligibleRunStatuses") or []],
        "maxDeleteBytes": policy.get("maxDeleteBytes"),
        "reason": str(policy.get("reason") or ""),
    }


def _public_gc_plan_item(item: dict[str, Any], *, protected_item: bool = False) -> dict[str, Any]:
    public = {
        "storageBackend": str(item.get("storageBackend") or ""),
        "sizeBytes": int(item.get("sizeBytes") or 0),
        "artifactCount": len(item.get("artifactIds") or []),
        "runCount": len(item.get("runIds") or []),
        "materializationCount": len(item.get("materializationIds") or []),
    }
    for key in ("terminalAt", "retentionUntil", "reason"):
        if item.get(key):
            public[key] = str(item[key])
    if protected_item:
        public["reasons"] = [str(reason) for reason in item.get("reasons") or []]
    if "payloadDeleted" in item:
        public["payloadDeleted"] = bool(item.get("payloadDeleted"))
    return public


def _public_gc_error(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "storageBackend": str(item.get("storageBackend") or ""),
        "errorCode": "ARTIFACT_GC_DELETE_FAILED",
    }


def _apply_max_delete_bytes(
    candidates: list[dict[str, Any]],
    max_delete_bytes: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if max_delete_bytes is None:
        return candidates, []
    kept: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    total = 0
    for item in sorted(candidates, key=lambda value: (str(value["terminalAt"]), str(value["storageUri"]))):
        size = int(item["sizeBytes"])
        if total + size > max_delete_bytes:
            protected.append({**item, "reasons": ["max_delete_bytes"]})
            continue
        kept.append(item)
        total += size
    return kept, protected


def _terminal_at(row: dict[str, Any]) -> datetime | None:
    return _parse_iso(str(row.get("runFinishedAt") or row.get("runLastUpdatedAt") or row.get("createdAt") or ""))


def _parse_iso(value: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_managed_local_path(cfg: RemoteRunnerConfig, path: Path) -> bool:
    roots = [Path(cfg.results_dir).resolve(), Path(cfg.work_dir).resolve()]
    return any(_is_relative_to(path, root) for root in roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_managed_s3_uri(cfg: RemoteRunnerConfig, storage_uri: str) -> bool:
    parsed = urlparse(storage_uri)
    if parsed.scheme != "s3":
        return False
    bucket = str(parsed.netloc or "").strip()
    object_name = unquote(str(parsed.path or "").lstrip("/"))
    expected_bucket = str(cfg.artifact_s3_bucket or "").strip()
    if expected_bucket and bucket != expected_bucket:
        return False
    prefix = str(cfg.artifact_s3_prefix or "").strip().strip("/")
    managed_prefix = f"{prefix}/artifacts/sha256/" if prefix else "artifacts/sha256/"
    return bool(object_name.startswith(managed_prefix))


def _group_id(storage_backend: str, storage_uri: str, sha256: str) -> str:
    payload = f"{storage_backend}\n{storage_uri}\n{sha256}"
    return f"agc_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _plan_id(planned_at: str, policy: GcPolicy, candidates: list[dict[str, Any]], protected: list[dict[str, Any]]) -> str:
    payload = repr(
        {
            "plannedAt": planned_at,
            "policy": {
                "retentionDays": policy.retention_days,
                "eligibleRunStatuses": sorted(policy.run_statuses),
                "maxDeleteBytes": policy.max_delete_bytes,
                "reason": policy.reason,
            },
            "candidates": [item["groupId"] for item in candidates],
            "protected": [item["groupId"] for item in protected],
        }
    )
    return f"agcp_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _audit_details(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidateCount": int(plan["candidateCount"]),
        "deleteBytes": int(plan["deleteBytes"]),
        "protectedCount": int(plan["protectedCount"]),
        "protectedBytes": int(plan["protectedBytes"]),
        "retentionDays": int(plan["policy"]["retentionDays"]),
        "eligibleRunStatuses": list(plan["policy"]["eligibleRunStatuses"]),
        "maxDeleteBytes": plan["policy"]["maxDeleteBytes"],
        "reason": str(plan["policy"]["reason"]),
    }
