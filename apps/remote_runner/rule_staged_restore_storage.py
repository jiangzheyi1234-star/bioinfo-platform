from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
import uuid

from .artifact_cache_storage import (
    ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
    ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
)
from .artifact_io import (
    artifact_payload_stats,
    artifact_record_exists,
    artifact_record_stats,
    assert_managed_artifact_storage,
    restore_artifact_payload,
)
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .execution_plan_hash import stable_plan_hash
from .rule_cache_restore_plan import RULE_CACHE_RESTORE_PLAN_SCHEMA_VERSION
from .rule_restore_pin_policy import restore_pin_owner_id
from .storage_core import get_connection, now_iso
from .workflow_run_storage import StaleRunAttemptError


RULE_CACHE_RESTORE_STAGED_FILES_APPLIED_EVENT_TYPE = "rule.cache_restore.staged_files_applied.v1"
RULE_CACHE_RESTORE_STAGED_FILES_APPLIED_SCHEMA_NAME = "RuleCacheRestoreStagedFilesApplied"


def prepare_rule_cache_restore_staged_files(
    cfg: RemoteRunnerConfig,
    plan: dict[str, Any],
    *,
    plan_hash: str,
    attempt_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    context = _validated_request_context(
        cfg,
        plan,
        plan_hash=plan_hash,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    with get_connection(cfg) as connection:
        _require_active_lease(
            connection,
            run_id=context["runId"],
            attempt_id=context["attemptId"],
            lease_generation=context["leaseGeneration"],
        )
        _require_run_revision(
            connection,
            run_id=context["runId"],
            workflow_revision_id=context["workflowRevisionId"],
        )
        targets = [
            _staged_target(
                cfg,
                connection,
                context=context,
                output=output,
            )
            for output in _eligible_outputs(plan)
        ]
    return _public_result(
        "rule-cache-restore-staged-file-prepare-result.v1",
        context=context,
        status="ready",
        target_count=len(targets),
        staged_file_count=len(targets),
        prepared_staged_file_count=0,
        created_staged_file_count=0,
        reused_staged_file_count=sum(1 for target in targets if target.get("existingMaterialization")),
        restore_pin_count=len(targets),
    )


def apply_rule_cache_restore_staged_files(
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
    context = _validated_request_context(
        cfg,
        plan,
        plan_hash=plan_hash,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    occurred_at = str(now or now_iso())
    with get_connection(cfg) as connection:
        _require_active_lease(
            connection,
            run_id=context["runId"],
            attempt_id=context["attemptId"],
            lease_generation=context["leaseGeneration"],
        )
        _require_run_revision(
            connection,
            run_id=context["runId"],
            workflow_revision_id=context["workflowRevisionId"],
        )
        targets = [
            _staged_target(
                cfg,
                connection,
                context=context,
                output=output,
            )
            for output in _eligible_outputs(plan)
        ]

    created_paths: list[Path] = []
    restored_targets: list[dict[str, Any]] = []
    try:
        for target in targets:
            restored = _restore_or_reuse_target(cfg, target)
            if restored.get("createdPath"):
                created_paths.append(Path(restored["path"]))
            restored_targets.append({**target, **restored})

        with get_connection(cfg) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_active_lease(
                connection,
                run_id=context["runId"],
                attempt_id=context["attemptId"],
                lease_generation=context["leaseGeneration"],
            )
            _require_run_revision(
                connection,
                run_id=context["runId"],
                workflow_revision_id=context["workflowRevisionId"],
            )
            _recheck_targets(connection, targets=restored_targets)
            materializations = [
                _record_staged_materialization(
                    connection,
                    target=target,
                    occurred_at=occurred_at,
                )
                for target in restored_targets
            ]
            evidence = append_evidence_event(
                connection,
                event_type=RULE_CACHE_RESTORE_STAGED_FILES_APPLIED_EVENT_TYPE,
                schema_name=RULE_CACHE_RESTORE_STAGED_FILES_APPLIED_SCHEMA_NAME,
                subject_kind="run_rule_cache_restore",
                subject_id=context["runId"],
                producer="rule_staged_restore_storage",
                occurred_at=occurred_at,
                payload={
                    "schemaVersion": "rule-cache-restore-staged-files-applied.v1",
                    "runId": context["runId"],
                    "workflowRevisionId": context["workflowRevisionId"],
                    "planHash": plan_hash,
                    "attemptId": context["attemptId"],
                    "leaseGeneration": context["leaseGeneration"],
                    "actorPresent": bool(_optional_text(actor)),
                    "reasonCode": "rule_cache_restore_staged_files_apply",
                    "reasonProvided": bool(_optional_text(reason)),
                    "targetCount": len(restored_targets),
                    "createdStagedFileCount": sum(1 for target in restored_targets if target["createdPath"]),
                    "reusedStagedFileCount": sum(1 for target in restored_targets if not target["createdPath"]),
                    "cacheEntryIds": [target["entry"]["cacheEntryId"] for target in restored_targets],
                    "cachePinIds": [target["pin"]["cachePinId"] for target in restored_targets],
                    "artifactBlobIds": [target["entry"]["artifactBlobId"] for target in restored_targets],
                    "materializationIds": [item["materializationId"] for item in materializations],
                    "stagedStorageUris": [target["storageUri"] for target in restored_targets],
                    "stagedLocalPaths": [target["path"] for target in restored_targets],
                    "sizeBytes": sum(int(target["sizeBytes"]) for target in restored_targets),
                },
            )
            connection.commit()
    except Exception:
        for path in created_paths:
            _remove_created_path(path)
        raise

    return _public_result(
        "rule-cache-restore-staged-file-apply-result.v1",
        context=context,
        status="applied",
        target_count=len(restored_targets),
        staged_file_count=len(restored_targets),
        prepared_staged_file_count=0,
        created_staged_file_count=sum(1 for target in restored_targets if target["createdPath"]),
        reused_staged_file_count=sum(1 for target in restored_targets if not target["createdPath"]),
        restore_pin_count=len(restored_targets),
        evidence_id=evidence["eventId"],
    )


def _validated_request_context(
    cfg: RemoteRunnerConfig,
    plan: dict[str, Any],
    *,
    plan_hash: str,
    attempt_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    del cfg
    _validate_plan(plan, plan_hash=plan_hash)
    return {
        "runId": _required_text(plan.get("runId"), "RULE_CACHE_RESTORE_RUN_ID_REQUIRED"),
        "workflowRevisionId": _required_text(
            plan.get("workflowRevisionId"),
            "RULE_CACHE_RESTORE_WORKFLOW_REVISION_REQUIRED",
        ),
        "planHash": _required_text(plan_hash, "RULE_CACHE_RESTORE_PLAN_HASH_REQUIRED"),
        "attemptId": _required_text(attempt_id, "STAGED_RESTORE_ATTEMPT_ID_REQUIRED"),
        "leaseGeneration": _required_generation(lease_generation),
    }


def _validate_plan(plan: dict[str, Any], *, plan_hash: str) -> None:
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
        raise ValueError("STAGED_RESTORE_OUTPUT_INVALIDATION_REQUIRED")
    policy = plan.get("stagedFilePolicy") if isinstance(plan.get("stagedFilePolicy"), dict) else {}
    if policy.get("previewAvailable") is not True:
        raise ValueError(str(policy.get("reasonCode") or "STAGED_FILE_POLICY_UNAVAILABLE"))
    if policy.get("materializationEnabled") is not True:
        raise ValueError(str(policy.get("reasonCode") or "STAGED_FILE_MATERIALIZATION_UNAVAILABLE"))
    if policy.get("deleteUnknownOutputs") is not False:
        raise ValueError("STAGED_RESTORE_UNKNOWN_OUTPUT_DELETE_UNSAFE")
    if str(policy.get("unknownOutputHandling") or "") != "refuse":
        raise ValueError("STAGED_RESTORE_UNKNOWN_OUTPUT_POLICY_UNSAFE")
    if not _eligible_outputs(plan):
        raise ValueError("STAGED_RESTORE_TARGET_EMPTY")


def _eligible_outputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in plan.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for output in rule.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            entry = output.get("cacheEntry") if isinstance(output.get("cacheEntry"), dict) else {}
            cache_entry_id = str(entry.get("cacheEntryId") or "").strip()
            if output.get("cacheHit") is True and cache_entry_id and cache_entry_id not in seen:
                outputs.append(output)
                seen.add(cache_entry_id)
    return outputs


def _staged_target(
    cfg: RemoteRunnerConfig,
    connection: Any,
    *,
    context: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    safe_entry = output.get("cacheEntry") if isinstance(output.get("cacheEntry"), dict) else {}
    cache_entry_id = _required_text(safe_entry.get("cacheEntryId"), "STAGED_RESTORE_CACHE_ENTRY_REQUIRED")
    entry = _require_cache_entry(cfg, connection, safe_entry=safe_entry, cache_entry_id=cache_entry_id)
    pin = _require_active_restore_pin(
        connection,
        entry=entry,
        owner_id=restore_pin_owner_id(context["attemptId"], context["leaseGeneration"]),
    )
    target_path = _staged_target_path(cfg, context=context, entry=entry)
    existing = _existing_materialization(connection, entry=entry, target_path=target_path)
    return {
        "entry": entry,
        "pin": pin,
        "targetPath": target_path,
        "existingMaterialization": existing,
    }


def _require_cache_entry(
    cfg: RemoteRunnerConfig,
    connection: Any,
    *,
    safe_entry: dict[str, Any],
    cache_entry_id: str,
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM artifact_cache_entries WHERE cache_entry_id = ? AND lifecycle_state = 'active'",
        (cache_entry_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"ARTIFACT_CACHE_ENTRY_NOT_ACTIVE: {cache_entry_id}")
    entry = _cache_entry_row_to_dict(row)
    for key in ("cacheEntryId", "artifactBlobId", "artifactKey", "stepId", "role", "sizeBytes", "sha256"):
        if safe_entry.get(key) is not None and str(safe_entry.get(key) or "") != str(entry.get(key) or ""):
            raise ValueError(f"STAGED_RESTORE_CACHE_ENTRY_SCOPE_STALE: {key}")
    _require_cache_payload_available(cfg, entry)
    return entry


def _require_active_restore_pin(connection: Any, *, entry: dict[str, Any], owner_id: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT *
        FROM artifact_cache_pins
        WHERE cache_entry_id = ?
          AND pin_scope = ?
          AND owner_kind = ?
          AND owner_id = ?
          AND state = 'active'
        """,
        (
            entry["cacheEntryId"],
            ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
            ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
            owner_id,
        ),
    ).fetchone()
    if row is None:
        raise ValueError("STAGED_RESTORE_ACTIVE_PIN_REQUIRED")
    return _pin_row_to_dict(row)


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


def _restore_or_reuse_target(cfg: RemoteRunnerConfig, target: dict[str, Any]) -> dict[str, Any]:
    target_path = Path(target["targetPath"])
    existing = target.get("existingMaterialization")
    if existing is not None:
        _require_existing_target_matches(target_path, target["entry"])
        return {
            "path": str(target_path.resolve()),
            "storageBackend": "local",
            "storageUri": target_path.resolve().as_uri(),
            "localPath": str(target_path.resolve()),
            "sizeBytes": int(target["entry"]["sizeBytes"]),
            "sha256": str(target["entry"]["sha256"]),
            "createdPath": False,
            "materializationId": existing["materializationId"],
        }
    if target_path.exists():
        raise ValueError("STAGED_RESTORE_DESTINATION_EXISTS")
    restore = restore_artifact_payload(cfg, target["entry"], target_path)
    return {**restore, "createdPath": True, "materializationId": ""}


def _require_existing_target_matches(path: Path, entry: dict[str, Any]) -> None:
    if not path.exists():
        raise ValueError("STAGED_RESTORE_MATERIALIZATION_MISSING")
    actual_size, actual_sha = artifact_payload_stats(path)
    if int(actual_size) != int(entry["sizeBytes"]) or str(actual_sha) != str(entry["sha256"]):
        raise ValueError("STAGED_RESTORE_MATERIALIZATION_CHECKSUM_MISMATCH")


def _record_staged_materialization(connection: Any, *, target: dict[str, Any], occurred_at: str) -> dict[str, Any]:
    existing_id = str(target.get("materializationId") or "").strip()
    if existing_id:
        return {"materializationId": existing_id, "created": False}
    materialization_id = f"amat_{uuid.uuid4().hex[:12]}"
    connection.execute(
        """
        INSERT INTO artifact_materializations (
            materialization_id, artifact_blob_id, storage_backend,
            storage_uri, local_path, created_at
        ) VALUES (?, ?, 'local', ?, ?, ?)
        """,
        (
            materialization_id,
            target["entry"]["artifactBlobId"],
            target["storageUri"],
            target["localPath"],
            occurred_at,
        ),
    )
    return {"materializationId": materialization_id, "created": True}


def _recheck_targets(connection: Any, *, targets: list[dict[str, Any]]) -> None:
    for target in targets:
        _require_active_cache_entry_row(connection, target["entry"]["cacheEntryId"])
        _require_active_restore_pin(
            connection,
            entry=target["entry"],
            owner_id=target["pin"]["ownerId"],
        )


def _require_active_cache_entry_row(connection: Any, cache_entry_id: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM artifact_cache_entries WHERE cache_entry_id = ? AND lifecycle_state = 'active'",
        (cache_entry_id,),
    ).fetchone()
    if row is None:
        raise ValueError("ARTIFACT_CACHE_ENTRY_NOT_ACTIVE")


def _existing_materialization(connection: Any, *, entry: dict[str, Any], target_path: Path) -> dict[str, Any] | None:
    resolved = target_path.resolve()
    row = connection.execute(
        """
        SELECT *
        FROM artifact_materializations
        WHERE artifact_blob_id = ?
          AND storage_backend = 'local'
          AND storage_uri = ?
          AND lifecycle_state = 'active'
        """,
        (entry["artifactBlobId"], resolved.as_uri()),
    ).fetchone()
    if row is None:
        return None
    return {
        "materializationId": row["materialization_id"],
        "artifactBlobId": row["artifact_blob_id"],
        "storageUri": row["storage_uri"],
        "localPath": row["local_path"],
    }


def _staged_target_path(cfg: RemoteRunnerConfig, *, context: dict[str, Any], entry: dict[str, Any]) -> Path:
    root = (
        Path(cfg.work_dir).resolve()
        / "cache-restore-staging"
        / _path_part(context["runId"])
        / _path_part(context["attemptId"])
        / str(context["leaseGeneration"])
    )
    filename = f"{_path_part(entry['artifactKey'])}-{_path_part(entry['cacheEntryId'])}"
    target = (root / filename).resolve()
    if not _is_relative_to(target, Path(cfg.work_dir).resolve()):
        raise ValueError("STAGED_RESTORE_TARGET_UNMANAGED")
    return target


def _public_result(
    schema_version: str,
    *,
    context: dict[str, Any],
    status: str,
    target_count: int,
    staged_file_count: int,
    prepared_staged_file_count: int,
    created_staged_file_count: int,
    reused_staged_file_count: int,
    restore_pin_count: int,
    evidence_id: str | None = None,
) -> dict[str, Any]:
    result = {
        "schemaVersion": schema_version,
        "runId": context["runId"],
        "planHash": context["planHash"],
        "status": status,
        "attemptId": context["attemptId"],
        "leaseGeneration": context["leaseGeneration"],
        "targetCount": target_count,
        "stagedFileCount": staged_file_count,
        "preparedStagedFileCount": prepared_staged_file_count,
        "createdStagedFileCount": created_staged_file_count,
        "reusedStagedFileCount": reused_staged_file_count,
        "restorePinCount": restore_pin_count,
        "finalOutputMutated": False,
        "runStateMutated": False,
        "stagingDirectoryExposed": False,
        "pathExposed": False,
        "storageUriExposed": False,
        "cacheKeyExposed": False,
        "ownerIdExposed": False,
    }
    if evidence_id:
        result["evidenceId"] = evidence_id
    return result


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


def _pin_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "cachePinId": row["cache_pin_id"],
        "cacheEntryId": row["cache_entry_id"],
        "artifactBlobId": row["artifact_blob_id"],
        "pinScope": row["pin_scope"],
        "ownerKind": row["owner_kind"],
        "ownerId": row["owner_id"],
        "state": row["state"],
    }


def _remove_created_path(path: Path) -> None:
    target = Path(path)
    if target.is_dir():
        import shutil

        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def _path_part(value: Any) -> str:
    text = str(value or "").strip()
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in text)
    safe = safe.strip(".-")
    if safe:
        return safe[:80]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


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
        raise ValueError("STAGED_RESTORE_LEASE_GENERATION_REQUIRED") from exc
    if generation < 1:
        raise ValueError("STAGED_RESTORE_LEASE_GENERATION_REQUIRED")
    return generation
