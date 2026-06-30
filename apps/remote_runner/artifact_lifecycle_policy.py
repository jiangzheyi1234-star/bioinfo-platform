from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .governance_audit import record_governance_audit_event
from .run_execution_state_machine import TERMINAL_RUN_STATUSES
from .storage_core import get_connection, now_iso


ARTIFACT_LIFECYCLE_POLICY_SCHEMA = "h2ometa.artifact-lifecycle-policy.v1"
ARTIFACT_LIFECYCLE_POLICY_EVENT_TYPE = "artifact.lifecycle.policy.set.v1"
ARTIFACT_LIFECYCLE_POLICY_SCHEMA_NAME = "ArtifactLifecyclePolicy"
ARTIFACT_LIFECYCLE_POLICY_SET_CONFIRMATION = "set-artifact-lifecycle-policy"
DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ID = "default"
DEFAULT_ARTIFACT_LIFECYCLE_POLICY_REASON = "retention_expired"
DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ACTOR = "artifact-lifecycle-policy"
DEFAULT_ARTIFACT_LIFECYCLE_RETENTION_DAYS = 30
DEFAULT_ARTIFACT_LIFECYCLE_STATUSES = ("canceled", "cancelled", "completed", "failed")
ARTIFACT_LIFECYCLE_POLICY_REQUIRED_FIELDS = ("retentionDays", "eligibleRunStatuses", "reason")
ARTIFACT_LIFECYCLE_POLICY_REASON_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


@dataclass(frozen=True)
class ArtifactLifecyclePolicy:
    policy_id: str
    policy_version: int
    retention_days: int
    eligible_run_statuses: tuple[str, ...]
    quota_bytes: int | None
    max_delete_bytes_per_tick: int | None
    reason: str
    actor: str
    policy_fingerprint: str
    created_at: str
    updated_at: str
    updated_by: str
    update_reason: str
    persisted: bool


def default_artifact_lifecycle_policy(*, now: str | None = None) -> ArtifactLifecyclePolicy:
    timestamp = str(now or now_iso())
    policy = {
        "retentionDays": DEFAULT_ARTIFACT_LIFECYCLE_RETENTION_DAYS,
        "eligibleRunStatuses": list(DEFAULT_ARTIFACT_LIFECYCLE_STATUSES),
        "quotaBytes": None,
        "maxDeleteBytesPerTick": None,
        "reason": DEFAULT_ARTIFACT_LIFECYCLE_POLICY_REASON,
        "actor": DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ACTOR,
    }
    return ArtifactLifecyclePolicy(
        policy_id=DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ID,
        policy_version=0,
        retention_days=int(policy["retentionDays"]),
        eligible_run_statuses=tuple(policy["eligibleRunStatuses"]),
        quota_bytes=None,
        max_delete_bytes_per_tick=None,
        reason=str(policy["reason"]),
        actor=str(policy["actor"]),
        policy_fingerprint=artifact_lifecycle_policy_fingerprint(policy),
        created_at=timestamp,
        updated_at=timestamp,
        updated_by="system-default",
        update_reason="default-policy",
        persisted=False,
    )


def get_governed_artifact_lifecycle_policy(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    policy = get_artifact_lifecycle_policy(cfg)
    record_governance_audit_event(
        cfg,
        action="artifact.lifecycle.policy.read",
        subject_kind="artifact_lifecycle_policy",
        subject_id=policy.policy_id,
        actor=cfg.api_token_actor or "remote-runner-api",
        details=_audit_details(policy),
    )
    return public_artifact_lifecycle_policy(policy)


def set_governed_artifact_lifecycle_policy(
    cfg: RemoteRunnerConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    body = dict(payload or {})
    if str(body.get("confirmation") or "").strip() != ARTIFACT_LIFECYCLE_POLICY_SET_CONFIRMATION:
        raise ValueError("ARTIFACT_LIFECYCLE_POLICY_SET_CONFIRMATION_REQUIRED")
    policy = set_artifact_lifecycle_policy(cfg, body)
    public = public_artifact_lifecycle_policy(policy)
    event = _record_policy_evidence(cfg, public)
    record_governance_audit_event(
        cfg,
        action="artifact.lifecycle.policy.set",
        subject_kind="artifact_lifecycle_policy",
        subject_id=policy.policy_id,
        actor=policy.updated_by or policy.actor,
        details={**_audit_details(policy), "evidenceId": event["eventId"]},
    )
    return public


def get_artifact_lifecycle_policy(cfg: RemoteRunnerConfig) -> ArtifactLifecyclePolicy:
    with get_connection(cfg) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM artifact_lifecycle_policies
            WHERE policy_id = ?
            """,
            (DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ID,),
        ).fetchone()
    if row is None:
        return default_artifact_lifecycle_policy()
    policy_payload = _json_object(row["policy_json"])
    return _policy_from_row(row, policy_payload)


def set_artifact_lifecycle_policy(
    cfg: RemoteRunnerConfig,
    payload: dict[str, Any],
) -> ArtifactLifecyclePolicy:
    require_complete_artifact_lifecycle_policy_payload(
        payload,
        error_prefix="ARTIFACT_LIFECYCLE_POLICY",
    )
    normalized = normalize_artifact_lifecycle_policy_payload(payload)
    now = now_iso()
    with get_connection(cfg) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT policy_version, created_at
                FROM artifact_lifecycle_policies
                WHERE policy_id = ?
                """,
                (DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ID,),
            ).fetchone()
            previous_version = int(row["policy_version"] or 0) if row else 0
            created_at = str(row["created_at"] or now) if row else now
            version = previous_version + 1
            fingerprint = artifact_lifecycle_policy_fingerprint(normalized)
            connection.execute(
                """
                INSERT INTO artifact_lifecycle_policies (
                    policy_id, policy_version, policy_json, policy_fingerprint,
                    created_at, updated_at, updated_by, update_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET
                    policy_version = excluded.policy_version,
                    policy_json = excluded.policy_json,
                    policy_fingerprint = excluded.policy_fingerprint,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by,
                    update_reason = excluded.update_reason
                """,
                (
                    DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ID,
                    version,
                    _json(normalized),
                    fingerprint,
                    created_at,
                    now,
                    str(normalized["actor"]),
                    str(normalized["reason"]),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return ArtifactLifecyclePolicy(
        policy_id=DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ID,
        policy_version=version,
        retention_days=int(normalized["retentionDays"]),
        eligible_run_statuses=tuple(normalized["eligibleRunStatuses"]),
        quota_bytes=normalized["quotaBytes"],
        max_delete_bytes_per_tick=normalized["maxDeleteBytesPerTick"],
        reason=str(normalized["reason"]),
        actor=str(normalized["actor"]),
        policy_fingerprint=fingerprint,
        created_at=created_at,
        updated_at=now,
        updated_by=str(normalized["actor"]),
        update_reason=str(normalized["reason"]),
        persisted=True,
    )


def normalize_artifact_lifecycle_policy_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    body = dict(payload or {})
    statuses = tuple(
        sorted(
            {
                str(item or "").strip()
                for item in body.get("eligibleRunStatuses", DEFAULT_ARTIFACT_LIFECYCLE_STATUSES)
                if str(item or "").strip()
            }
        )
    )
    invalid = set(statuses) - TERMINAL_RUN_STATUSES
    if invalid:
        raise ValueError(f"ARTIFACT_LIFECYCLE_POLICY_STATUS_UNSUPPORTED: {sorted(invalid)[0]}")
    if not statuses:
        raise ValueError("ARTIFACT_LIFECYCLE_POLICY_STATUS_REQUIRED")
    quota = body.get("quotaBytes")
    max_delete = body.get("maxDeleteBytesPerTick")
    reason = str(body.get("reason") or DEFAULT_ARTIFACT_LIFECYCLE_POLICY_REASON).strip()
    reason = reason or DEFAULT_ARTIFACT_LIFECYCLE_POLICY_REASON
    if not ARTIFACT_LIFECYCLE_POLICY_REASON_PATTERN.fullmatch(reason):
        raise ValueError("ARTIFACT_LIFECYCLE_POLICY_REASON_INVALID")
    return {
        "retentionDays": _non_negative_int(
            body.get("retentionDays", DEFAULT_ARTIFACT_LIFECYCLE_RETENTION_DAYS),
            "ARTIFACT_LIFECYCLE_POLICY_RETENTION_INVALID",
        ),
        "eligibleRunStatuses": list(statuses),
        "quotaBytes": _optional_non_negative_int(quota, "ARTIFACT_LIFECYCLE_POLICY_QUOTA_INVALID"),
        "maxDeleteBytesPerTick": _optional_positive_int(max_delete, "ARTIFACT_LIFECYCLE_POLICY_MAX_DELETE_INVALID"),
        "reason": reason,
        "actor": str(body.get("actor") or DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ACTOR).strip()
        or DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ACTOR,
    }


def require_complete_artifact_lifecycle_policy_payload(
    payload: dict[str, Any] | None,
    *,
    error_prefix: str,
) -> None:
    body = dict(payload or {})
    for field in ARTIFACT_LIFECYCLE_POLICY_REQUIRED_FIELDS:
        value = body.get(field)
        if value is None or value == "" or value == []:
            raise ValueError(f"{error_prefix}_FIELD_REQUIRED: {field}")


def artifact_lifecycle_policy_fingerprint(policy: dict[str, Any]) -> str:
    payload = {
        "retentionDays": int(policy.get("retentionDays") or 0),
        "eligibleRunStatuses": sorted(str(item) for item in policy.get("eligibleRunStatuses") or []),
        "quotaBytes": policy.get("quotaBytes"),
        "maxDeleteBytesPerTick": policy.get("maxDeleteBytesPerTick"),
        "reason": str(policy.get("reason") or ""),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"alpfp_{hashlib.sha256(encoded).hexdigest()}"


def public_artifact_lifecycle_policy(policy: ArtifactLifecyclePolicy) -> dict[str, Any]:
    return {
        "schemaVersion": ARTIFACT_LIFECYCLE_POLICY_SCHEMA,
        "policyId": policy.policy_id,
        "policyVersion": policy.policy_version,
        "policyFingerprint": policy.policy_fingerprint,
        "persisted": policy.persisted,
        "createdAt": policy.created_at,
        "updatedAt": policy.updated_at,
        "updatedBy": policy.updated_by,
        "retentionDays": policy.retention_days,
        "eligibleRunStatuses": list(policy.eligible_run_statuses),
        "quotaBytes": policy.quota_bytes,
        "maxDeleteBytesPerTick": policy.max_delete_bytes_per_tick,
        "reason": policy.reason,
        "redactionPolicy": {
            "pathsExposed": False,
            "storageUrisExposed": False,
            "artifactIdsExposed": False,
            "runIdsExposed": False,
        },
    }


def _policy_from_row(row: Any, policy_payload: dict[str, Any]) -> ArtifactLifecyclePolicy:
    normalized = normalize_artifact_lifecycle_policy_payload(policy_payload)
    return ArtifactLifecyclePolicy(
        policy_id=str(row["policy_id"] or DEFAULT_ARTIFACT_LIFECYCLE_POLICY_ID),
        policy_version=int(row["policy_version"] or 0),
        retention_days=int(normalized["retentionDays"]),
        eligible_run_statuses=tuple(normalized["eligibleRunStatuses"]),
        quota_bytes=normalized["quotaBytes"],
        max_delete_bytes_per_tick=normalized["maxDeleteBytesPerTick"],
        reason=str(normalized["reason"]),
        actor=str(normalized["actor"]),
        policy_fingerprint=str(row["policy_fingerprint"] or artifact_lifecycle_policy_fingerprint(normalized)),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        updated_by=str(row["updated_by"] or ""),
        update_reason=str(row["update_reason"] or ""),
        persisted=True,
    )


def _record_policy_evidence(cfg: RemoteRunnerConfig, public_policy: dict[str, Any]) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type=ARTIFACT_LIFECYCLE_POLICY_EVENT_TYPE,
            schema_name=ARTIFACT_LIFECYCLE_POLICY_SCHEMA_NAME,
            subject_kind="artifact_lifecycle_policy",
            subject_id=str(public_policy["policyId"]),
            payload=public_policy,
            producer="artifact_lifecycle_policy",
            occurred_at=str(public_policy["updatedAt"]),
        )
        connection.commit()
    return event


def _audit_details(policy: ArtifactLifecyclePolicy) -> dict[str, Any]:
    return {
        "policyId": policy.policy_id,
        "policyVersion": policy.policy_version,
        "policyFingerprint": policy.policy_fingerprint,
        "persisted": policy.persisted,
        "retentionDays": policy.retention_days,
        "eligibleRunStatusCount": len(policy.eligible_run_statuses),
        "quotaProvided": policy.quota_bytes is not None,
        "maxDeleteBytesPerTickProvided": policy.max_delete_bytes_per_tick is not None,
    }


def _non_negative_int(value: Any, code: str) -> int:
    normalized = int(value)
    if normalized < 0:
        raise ValueError(code)
    return normalized


def _optional_non_negative_int(value: Any, code: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, code)


def _optional_positive_int(value: Any, code: str) -> int | None:
    if value is None:
        return None
    normalized = int(value)
    if normalized < 1:
        raise ValueError(code)
    return normalized


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_object(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}
