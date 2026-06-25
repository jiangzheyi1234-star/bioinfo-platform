from __future__ import annotations

from typing import Any

from .artifact_cache_storage import (
    ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
    ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
    ARTIFACT_CACHE_RESTORE_PIN_TTL_SECONDS,
    create_artifact_cache_pin_record,
    release_artifact_cache_pins_record,
)
from .artifact_io import artifact_record_exists, artifact_record_stats, assert_managed_artifact_storage
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .execution_plan_hash import stable_plan_hash
from .rule_cache_restore_plan import RULE_CACHE_RESTORE_PLAN_SCHEMA_VERSION
from .rule_restore_pin_policy import restore_pin_owner_id
from .storage_core import get_connection, now_iso
from .workflow_run_storage import StaleRunAttemptError


RULE_CACHE_RESTORE_PINS_APPLIED_EVENT_TYPE = "rule.cache_restore.pins_applied.v1"
RULE_CACHE_RESTORE_PINS_APPLIED_SCHEMA_NAME = "RuleCacheRestorePinsApplied"
RULE_CACHE_RESTORE_PINS_RELEASED_EVENT_TYPE = "rule.cache_restore.pins_released.v1"
RULE_CACHE_RESTORE_PINS_RELEASED_SCHEMA_NAME = "RuleCacheRestorePinsReleased"


def prepare_rule_cache_restore_pins(
    cfg: RemoteRunnerConfig,
    plan: dict[str, Any],
    *,
    plan_hash: str,
    attempt_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    run_id, workflow_revision_id, normalized_attempt_id, normalized_generation = _validated_request_context(
        cfg,
        plan,
        plan_hash=plan_hash,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        lock=False,
    )
    outputs = _eligible_pin_outputs(plan)
    if not outputs:
        raise ValueError("RESTORE_PIN_REQUIRED_OUTPUT_EMPTY")
    with get_connection(cfg) as connection:
        _require_active_lease(
            connection,
            run_id=run_id,
            attempt_id=normalized_attempt_id,
            lease_generation=normalized_generation,
        )
        _require_run_revision(connection, run_id=run_id, workflow_revision_id=workflow_revision_id)
        entries = [_require_cache_entry(cfg, connection, output) for output in outputs]
    return {
        "schemaVersion": "rule-cache-restore-pin-prepare-result.v1",
        "runId": run_id,
        "planHash": plan_hash,
        "status": "ready",
        "attemptId": normalized_attempt_id,
        "leaseGeneration": normalized_generation,
        "eligiblePinCount": len(entries),
        "preparedPinCount": 0,
        "pinCreationAllowed": True,
        "ownerKind": ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
        "pinScope": ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
        "ttlSeconds": ARTIFACT_CACHE_RESTORE_PIN_TTL_SECONDS,
        "ownerIdExposed": False,
        "cacheKeyExposed": False,
        "storageUriExposed": False,
        "pathExposed": False,
    }


def apply_rule_cache_restore_pins(
    cfg: RemoteRunnerConfig,
    plan: dict[str, Any],
    *,
    plan_hash: str,
    attempt_id: str,
    lease_generation: int,
    actor: str | None = None,
    reason: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    run_id, workflow_revision_id, normalized_attempt_id, normalized_generation = _validated_request_context(
        cfg,
        plan,
        plan_hash=plan_hash,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        lock=True,
    )
    outputs = _eligible_pin_outputs(plan)
    if not outputs:
        raise ValueError("RESTORE_PIN_REQUIRED_OUTPUT_EMPTY")

    occurred_at = str(now or now_iso())
    owner_id = restore_pin_owner_id(normalized_attempt_id, normalized_generation)
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        _require_active_lease(
            connection,
            run_id=run_id,
            attempt_id=normalized_attempt_id,
            lease_generation=normalized_generation,
        )
        _require_run_revision(connection, run_id=run_id, workflow_revision_id=workflow_revision_id)
        entries = [_require_cache_entry(cfg, connection, output) for output in outputs]
        existing_pin_count = _existing_restore_pin_count(
            connection,
            entries=entries,
            owner_id=owner_id,
        )
        pins = [
            create_artifact_cache_pin_record(
                connection,
                entry=entry,
                pin_scope=ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
                owner_kind=ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
                owner_id=owner_id,
                reason="rule_cache_restore_apply",
                created_at=occurred_at,
                expires_at=_expires_at_for_pin(occurred_at),
            )
            for entry in entries
        ]
        evidence = append_evidence_event(
            connection,
            event_type=RULE_CACHE_RESTORE_PINS_APPLIED_EVENT_TYPE,
            schema_name=RULE_CACHE_RESTORE_PINS_APPLIED_SCHEMA_NAME,
            subject_kind="run_rule_cache_restore",
            subject_id=run_id,
            producer="rule_restore_pin_storage",
            occurred_at=occurred_at,
            payload={
                "schemaVersion": "rule-cache-restore-pins-applied.v1",
                "runId": run_id,
                "workflowRevisionId": workflow_revision_id,
                "planHash": plan_hash,
                "attemptId": normalized_attempt_id,
                "leaseGeneration": normalized_generation,
                "actorPresent": bool(_optional_text(actor)),
                "reasonCode": "rule_cache_restore_apply",
                "reasonProvided": bool(_optional_text(reason)),
                "cacheEntryCount": len(entries),
                "cachePinCount": len(pins),
                "createdPinCount": max(0, len(pins) - existing_pin_count),
                "reusedPinCount": existing_pin_count,
                "cacheEntryIds": [entry["cacheEntryId"] for entry in entries],
                "cachePinIds": [pin["cachePinId"] for pin in pins],
                "artifactBlobIds": [entry["artifactBlobId"] for entry in entries],
                "ttlSeconds": ARTIFACT_CACHE_RESTORE_PIN_TTL_SECONDS,
            },
        )
        connection.commit()

    return {
        "schemaVersion": "rule-cache-restore-pin-apply-result.v1",
        "runId": run_id,
        "planHash": plan_hash,
        "status": "applied",
        "attemptId": normalized_attempt_id,
        "leaseGeneration": normalized_generation,
        "evidenceId": evidence["eventId"],
        "appliedPinCount": len(pins),
        "createdPinCount": max(0, len(pins) - existing_pin_count),
        "reusedPinCount": existing_pin_count,
        "cacheEntryCount": len(entries),
        "cachePinIds": [pin["cachePinId"] for pin in pins],
        "expiresAt": pins[0]["expiresAt"] if pins else "",
        "ownerKind": ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
        "pinScope": ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
        "ownerIdExposed": False,
        "cacheKeyExposed": False,
        "storageUriExposed": False,
        "pathExposed": False,
    }


def release_rule_cache_restore_pins(
    cfg: RemoteRunnerConfig,
    *,
    cache_pin_ids: list[str],
    attempt_id: str,
    lease_generation: int,
    reason: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    normalized_ids = sorted({_required_text(item, "RESTORE_PIN_ID_REQUIRED") for item in cache_pin_ids})
    normalized_attempt_id = _required_text(attempt_id, "RESTORE_PIN_ATTEMPT_ID_REQUIRED")
    normalized_generation = _required_generation(lease_generation)
    owner_id = restore_pin_owner_id(normalized_attempt_id, normalized_generation)
    released_at = str(now or now_iso())
    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        pins = _require_owned_restore_pins(connection, pin_ids=normalized_ids, owner_id=owner_id)
        release_artifact_cache_pins_record(connection, pin_ids=normalized_ids, released_at=released_at)
        evidence = append_evidence_event(
            connection,
            event_type=RULE_CACHE_RESTORE_PINS_RELEASED_EVENT_TYPE,
            schema_name=RULE_CACHE_RESTORE_PINS_RELEASED_SCHEMA_NAME,
            subject_kind="run_rule_cache_restore",
            subject_id=normalized_attempt_id,
            producer="rule_restore_pin_storage",
            occurred_at=released_at,
            payload={
                "schemaVersion": "rule-cache-restore-pins-released.v1",
                "attemptId": normalized_attempt_id,
                "leaseGeneration": normalized_generation,
                "reasonCode": "rule_cache_restore_release",
                "reasonProvided": bool(_optional_text(reason)),
                "cachePinCount": len(pins),
                "cachePinIds": normalized_ids,
                "cacheEntryIds": [pin["cache_entry_id"] for pin in pins],
            },
        )
        connection.commit()
    return {
        "schemaVersion": "rule-cache-restore-pin-release-result.v1",
        "status": "released",
        "attemptId": normalized_attempt_id,
        "leaseGeneration": normalized_generation,
        "releasedPinCount": len(pins),
        "cachePinIds": normalized_ids,
        "evidenceId": evidence["eventId"],
        "releasedAt": released_at,
    }


def _validate_prepare_plan(plan: dict[str, Any], *, plan_hash: str) -> None:
    if not isinstance(plan, dict):
        raise ValueError("RULE_CACHE_RESTORE_PLAN_REQUIRED")
    if plan.get("schemaVersion") != RULE_CACHE_RESTORE_PLAN_SCHEMA_VERSION:
        raise ValueError("RULE_CACHE_RESTORE_PLAN_SCHEMA_UNSUPPORTED")
    normalized_hash = _required_text(plan_hash, "RULE_CACHE_RESTORE_PLAN_HASH_REQUIRED")
    if str(plan.get("planHash") or "") != normalized_hash:
        raise ValueError("RULE_CACHE_RESTORE_PLAN_HASH_MISMATCH")
    if stable_plan_hash(plan) != normalized_hash:
        raise ValueError("RULE_CACHE_RESTORE_PLAN_HASH_STALE")
    cache_eligibility = plan.get("cacheEligibility") if isinstance(plan.get("cacheEligibility"), dict) else {}
    if cache_eligibility.get("outputInvalidationApplied") is not True:
        raise ValueError("RESTORE_PIN_OUTPUT_INVALIDATION_REQUIRED")
    policy = plan.get("restorePinPolicy") if isinstance(plan.get("restorePinPolicy"), dict) else {}
    if policy.get("previewAvailable") is not True:
        raise ValueError(str(policy.get("reasonCode") or "RESTORE_PIN_POLICY_UNAVAILABLE"))


def _validated_request_context(
    cfg: RemoteRunnerConfig,
    plan: dict[str, Any],
    *,
    plan_hash: str,
    attempt_id: str,
    lease_generation: int,
    lock: bool,
) -> tuple[str, str, str, int]:
    del cfg, lock
    _validate_prepare_plan(plan, plan_hash=plan_hash)
    run_id = _required_text(plan.get("runId"), "RULE_CACHE_RESTORE_RUN_ID_REQUIRED")
    workflow_revision_id = _required_text(
        plan.get("workflowRevisionId"),
        "RULE_CACHE_RESTORE_WORKFLOW_REVISION_REQUIRED",
    )
    normalized_attempt_id = _required_text(attempt_id, "RESTORE_PIN_ATTEMPT_ID_REQUIRED")
    normalized_generation = _required_generation(lease_generation)
    return run_id, workflow_revision_id, normalized_attempt_id, normalized_generation


def _eligible_pin_outputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in plan.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for output in rule.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            policy = output.get("restorePinPolicy") if isinstance(output.get("restorePinPolicy"), dict) else {}
            entry = output.get("cacheEntry") if isinstance(output.get("cacheEntry"), dict) else {}
            cache_entry_id = str(entry.get("cacheEntryId") or "").strip()
            if policy.get("eligible") is True and cache_entry_id and cache_entry_id not in seen:
                outputs.append(output)
                seen.add(cache_entry_id)
    return outputs


def _require_cache_entry(cfg: RemoteRunnerConfig, connection: Any, output: dict[str, Any]) -> dict[str, Any]:
    safe_entry = output.get("cacheEntry") if isinstance(output.get("cacheEntry"), dict) else {}
    cache_entry_id = _required_text(safe_entry.get("cacheEntryId"), "RESTORE_PIN_CACHE_ENTRY_REQUIRED")
    row = connection.execute(
        "SELECT * FROM artifact_cache_entries WHERE cache_entry_id = ? AND lifecycle_state = 'active'",
        (cache_entry_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"ARTIFACT_CACHE_ENTRY_NOT_ACTIVE: {cache_entry_id}")
    entry = _cache_entry_row_to_dict(row)
    _require_entry_matches_plan(entry, safe_entry)
    _require_cache_payload_available(cfg, entry)
    return entry


def _require_entry_matches_plan(entry: dict[str, Any], safe_entry: dict[str, Any]) -> None:
    expected = {
        "cacheEntryId": safe_entry.get("cacheEntryId"),
        "artifactBlobId": safe_entry.get("artifactBlobId"),
        "artifactKey": safe_entry.get("artifactKey"),
        "stepId": safe_entry.get("stepId"),
        "role": safe_entry.get("role"),
        "sizeBytes": safe_entry.get("sizeBytes"),
        "sha256": safe_entry.get("sha256"),
        "lifecycleState": "active",
    }
    for key, value in expected.items():
        if value is not None and str(entry.get(key) or "") != str(value):
            raise ValueError(f"ARTIFACT_CACHE_ENTRY_SCOPE_STALE: {key}")


def _require_cache_payload_available(cfg: RemoteRunnerConfig, entry: dict[str, Any]) -> None:
    record = {
        "storageBackend": entry["storageBackend"],
        "storageUri": entry["storageUri"],
        "sizeBytes": int(entry["sizeBytes"]),
        "sha256": entry["sha256"],
        "path": "",
    }
    try:
        assert_managed_artifact_storage(cfg, record)
    except ValueError as exc:
        if str(exc).startswith("RESULT_ARTIFACT_STORAGE_UNMANAGED"):
            raise ValueError(f"ARTIFACT_CACHE_PAYLOAD_UNMANAGED: {entry['cacheEntryId']}") from exc
        raise
    if not artifact_record_exists(cfg, record):
        raise ValueError(f"ARTIFACT_CACHE_PAYLOAD_UNAVAILABLE: {entry['cacheEntryId']}")
    actual_size, actual_sha = artifact_record_stats(cfg, record)
    if int(actual_size) != int(entry["sizeBytes"]) or str(actual_sha) != str(entry["sha256"]):
        raise ValueError(f"ARTIFACT_CACHE_PAYLOAD_CHECKSUM_MISMATCH: {entry['cacheEntryId']}")


def _require_active_lease(
    connection: Any,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> None:
    lease = connection.execute(
        "SELECT attempt_id, lease_generation, state FROM run_leases WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if (
        lease is None
        or str(lease["attempt_id"]) != attempt_id
        or int(lease["lease_generation"]) != int(lease_generation)
        or str(lease["state"]) != "active"
    ):
        raise StaleRunAttemptError("RUN_ATTEMPT_STALE")


def _require_run_revision(connection: Any, *, run_id: str, workflow_revision_id: str) -> None:
    run = connection.execute(
        "SELECT workflow_revision_id FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        raise KeyError(run_id)
    if str(run["workflow_revision_id"] or "") != workflow_revision_id:
        raise ValueError("RULE_CACHE_RESTORE_WORKFLOW_REVISION_MISMATCH")


def _require_owned_restore_pins(connection: Any, *, pin_ids: list[str], owner_id: str) -> list[Any]:
    if not pin_ids:
        raise ValueError("RESTORE_PIN_ID_REQUIRED")
    placeholders = ",".join("?" for _ in pin_ids)
    rows = connection.execute(
        f"""
        SELECT *
        FROM artifact_cache_pins
        WHERE cache_pin_id IN ({placeholders})
        """,
        tuple(pin_ids),
    ).fetchall()
    by_id = {str(row["cache_pin_id"]): row for row in rows}
    if set(by_id) != set(pin_ids):
        raise ValueError("RESTORE_PIN_SCOPE_STALE")
    for row in rows:
        if (
            str(row["pin_scope"]) != ARTIFACT_CACHE_RESTORE_PIN_SCOPE
            or str(row["owner_kind"]) != ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND
            or str(row["owner_id"]) != owner_id
        ):
            raise ValueError("RESTORE_PIN_SCOPE_STALE")
    return [by_id[pin_id] for pin_id in pin_ids]


def _existing_restore_pin_count(connection: Any, *, entries: list[dict[str, Any]], owner_id: str) -> int:
    count = 0
    for entry in entries:
        existing = connection.execute(
            """
            SELECT 1
            FROM artifact_cache_pins
            WHERE cache_entry_id = ?
              AND pin_scope = ?
              AND owner_kind = ?
              AND owner_id = ?
            """,
            (
                entry["cacheEntryId"],
                ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
                ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
                owner_id,
            ),
        ).fetchone()
        if existing is not None:
            count += 1
    return count


def _cache_entry_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "cacheEntryId": row["cache_entry_id"],
        "cacheKey": row["cache_key"],
        "artifactBlobId": row["artifact_blob_id"],
        "storageBackend": row["storage_backend"],
        "storageUri": row["storage_uri"],
        "sha256": row["sha256"],
        "artifactKey": row["artifact_key"],
        "stepId": row["step_id"],
        "role": row["role"],
        "sizeBytes": int(row["size_bytes"]),
        "lifecycleState": row["lifecycle_state"],
    }


def _expires_at_for_pin(created_at: str) -> str:
    from datetime import datetime, timedelta, timezone

    try:
        base = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        base = datetime.now(timezone.utc)
    return (base + timedelta(seconds=ARTIFACT_CACHE_RESTORE_PIN_TTL_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _required_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


def _required_generation(value: Any) -> int:
    try:
        generation = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("RESTORE_PIN_LEASE_GENERATION_REQUIRED") from exc
    if generation < 1:
        raise ValueError("RESTORE_PIN_LEASE_GENERATION_REQUIRED")
    return generation
