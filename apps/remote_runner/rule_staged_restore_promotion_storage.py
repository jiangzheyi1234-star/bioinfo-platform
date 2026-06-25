from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from .artifact_cache_storage import (
    ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
    ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
)
from .artifact_io import artifact_payload_stats, restore_artifact_payload
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .execution_plan_hash import stable_plan_hash
from .executor_inputs import _build_run_outputs
from .executor_paths import _resolve_execution_result_dir
from .rule_cache_restore_plan import RULE_CACHE_RESTORE_PLAN_SCHEMA_VERSION
from .rule_restore_pin_policy import restore_pin_owner_id
from .storage_core import get_connection, now_iso
from .workflow_run_storage import StaleRunAttemptError


RULE_CACHE_RESTORE_FINAL_OUTPUTS_PROMOTED_EVENT_TYPE = "rule.cache_restore.final_outputs_promoted.v1"
RULE_CACHE_RESTORE_FINAL_OUTPUTS_PROMOTED_SCHEMA_NAME = "RuleCacheRestoreFinalOutputsPromoted"


def prepare_rule_cache_restore_final_outputs(
    cfg: RemoteRunnerConfig,
    plan: dict[str, Any],
    *,
    plan_hash: str,
    attempt_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    context = _validated_request_context(
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
        run = _require_run_revision(
            connection,
            run_id=context["runId"],
            workflow_revision_id=context["workflowRevisionId"],
        )
        output_paths = _declared_output_paths(cfg, run=run, context=context)
        targets = [
            _promotion_target(
                cfg,
                connection,
                context=context,
                output=output,
                output_paths=output_paths,
            )
            for output in _eligible_outputs(plan)
        ]
    return _public_result(
        "rule-cache-restore-final-output-prepare-result.v1",
        context=context,
        status="ready",
        target_count=len(targets),
        final_output_count=len(targets),
        prepared_final_output_count=0,
        created_final_output_count=0,
        reused_final_output_count=sum(1 for target in targets if _existing_candidate(target) is not None),
        candidate_output_count=sum(1 for target in targets if _existing_candidate(target) is not None),
    )


def apply_rule_cache_restore_final_outputs(
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
        run = _require_run_revision(
            connection,
            run_id=context["runId"],
            workflow_revision_id=context["workflowRevisionId"],
        )
        output_paths = _declared_output_paths(cfg, run=run, context=context)
        targets = [
            _promotion_target(
                cfg,
                connection,
                context=context,
                output=output,
                output_paths=output_paths,
            )
            for output in _eligible_outputs(plan)
        ]

    created_paths: list[Path] = []
    promoted_targets: list[dict[str, Any]] = []
    try:
        for target in targets:
            promoted = _restore_or_reuse_final_output(cfg, target)
            if promoted["createdFinalOutput"]:
                created_paths.append(Path(promoted["finalPath"]))
            promoted_targets.append({**target, **promoted})

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
            _recheck_targets(connection, targets=promoted_targets)
            candidates = [
                _record_candidate_output(
                    connection,
                    context=context,
                    target=target,
                    occurred_at=occurred_at,
                )
                for target in promoted_targets
            ]
            evidence = append_evidence_event(
                connection,
                event_type=RULE_CACHE_RESTORE_FINAL_OUTPUTS_PROMOTED_EVENT_TYPE,
                schema_name=RULE_CACHE_RESTORE_FINAL_OUTPUTS_PROMOTED_SCHEMA_NAME,
                subject_kind="run_rule_cache_restore",
                subject_id=context["runId"],
                producer="rule_staged_restore_promotion_storage",
                occurred_at=occurred_at,
                payload={
                    "schemaVersion": "rule-cache-restore-final-outputs-promoted.v1",
                    "runId": context["runId"],
                    "workflowRevisionId": context["workflowRevisionId"],
                    "planHash": plan_hash,
                    "attemptId": context["attemptId"],
                    "leaseGeneration": context["leaseGeneration"],
                    "actorPresent": bool(_optional_text(actor)),
                    "reasonCode": "rule_cache_restore_final_output_apply",
                    "reasonProvided": bool(_optional_text(reason)),
                    "targetCount": len(promoted_targets),
                    "createdFinalOutputCount": sum(1 for target in promoted_targets if target["createdFinalOutput"]),
                    "reusedFinalOutputCount": sum(1 for target in promoted_targets if not target["createdFinalOutput"]),
                    "candidateOutputIds": [candidate["candidateOutputId"] for candidate in candidates],
                    "cacheEntryIds": [target["entry"]["cacheEntryId"] for target in promoted_targets],
                    "cachePinIds": [target["pin"]["cachePinId"] for target in promoted_targets],
                    "artifactBlobIds": [target["entry"]["artifactBlobId"] for target in promoted_targets],
                    "stagedMaterializationIds": [
                        target["stagedMaterialization"]["materializationId"] for target in promoted_targets
                    ],
                    "finalOutputPaths": [target["finalPath"] for target in promoted_targets],
                    "finalStorageUris": [target["finalStorageUri"] for target in promoted_targets],
                    "sizeBytes": sum(int(target["sizeBytes"]) for target in promoted_targets),
                },
            )
            connection.commit()
    except Exception:
        for path in created_paths:
            _remove_created_path(path)
        raise

    return _public_result(
        "rule-cache-restore-final-output-apply-result.v1",
        context=context,
        status="applied",
        target_count=len(promoted_targets),
        final_output_count=len(promoted_targets),
        prepared_final_output_count=0,
        created_final_output_count=sum(1 for target in promoted_targets if target["createdFinalOutput"]),
        reused_final_output_count=sum(1 for target in promoted_targets if not target["createdFinalOutput"]),
        candidate_output_count=len(promoted_targets),
        evidence_id=evidence["eventId"],
    )


def _validated_request_context(
    plan: dict[str, Any],
    *,
    plan_hash: str,
    attempt_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    _validate_plan(plan, plan_hash=plan_hash)
    return {
        "runId": _required_text(plan.get("runId"), "RULE_CACHE_RESTORE_RUN_ID_REQUIRED"),
        "workflowRevisionId": _required_text(
            plan.get("workflowRevisionId"),
            "RULE_CACHE_RESTORE_WORKFLOW_REVISION_REQUIRED",
        ),
        "planHash": _required_text(plan_hash, "RULE_CACHE_RESTORE_PLAN_HASH_REQUIRED"),
        "attemptId": _required_text(attempt_id, "FINAL_OUTPUT_PROMOTION_ATTEMPT_ID_REQUIRED"),
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
        raise ValueError("FINAL_OUTPUT_PROMOTION_OUTPUT_INVALIDATION_REQUIRED")
    policy = plan.get("stagedFilePolicy") if isinstance(plan.get("stagedFilePolicy"), dict) else {}
    if policy.get("materializationEnabled") is not True:
        raise ValueError(str(policy.get("reasonCode") or "STAGED_FILE_MATERIALIZATION_REQUIRED"))
    if policy.get("attemptFinalOutputPromotionAllowed") is not True:
        raise ValueError(str(policy.get("reasonCode") or "FINAL_OUTPUT_PROMOTION_DISABLED"))
    if policy.get("finalOutputOverwriteAllowed") is not False or policy.get("deleteUnknownOutputs") is not False:
        raise ValueError("FINAL_OUTPUT_PROMOTION_OVERWRITE_POLICY_UNSAFE")
    if str(policy.get("unknownOutputHandling") or "") != "refuse":
        raise ValueError("FINAL_OUTPUT_PROMOTION_UNKNOWN_OUTPUT_POLICY_UNSAFE")
    if not _eligible_outputs(plan):
        raise ValueError("FINAL_OUTPUT_PROMOTION_TARGET_EMPTY")


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


def _promotion_target(
    cfg: RemoteRunnerConfig,
    connection: Any,
    *,
    context: dict[str, Any],
    output: dict[str, Any],
    output_paths: dict[str, Path],
) -> dict[str, Any]:
    safe_entry = output.get("cacheEntry") if isinstance(output.get("cacheEntry"), dict) else {}
    artifact_key = _required_text(output.get("artifactKey"), "FINAL_OUTPUT_PROMOTION_ARTIFACT_KEY_REQUIRED")
    if artifact_key not in output_paths:
        raise ValueError("FINAL_OUTPUT_PROMOTION_OUTPUT_PATH_UNMAPPED")
    cache_entry_id = _required_text(safe_entry.get("cacheEntryId"), "FINAL_OUTPUT_PROMOTION_CACHE_ENTRY_REQUIRED")
    entry = _require_cache_entry(connection, safe_entry=safe_entry, cache_entry_id=cache_entry_id)
    pin = _require_active_restore_pin(
        connection,
        entry=entry,
        owner_id=restore_pin_owner_id(context["attemptId"], context["leaseGeneration"]),
    )
    staged_path = _staged_target_path(cfg, context=context, entry=entry)
    staged_materialization = _require_staged_materialization(connection, entry=entry, staged_path=staged_path)
    final_path = output_paths[artifact_key].resolve()
    _require_managed_final_output(cfg, context=context, final_path=final_path)
    existing_candidate = _existing_candidate_row(
        connection,
        context=context,
        artifact_key=artifact_key,
        final_path=final_path,
        entry=entry,
    )
    if final_path.exists():
        _require_existing_final_output_matches(final_path, entry)
        if existing_candidate is None:
            raise ValueError("FINAL_OUTPUT_PROMOTION_DESTINATION_EXISTS")
    return {
        "artifactKey": artifact_key,
        "stepId": str(output.get("stepId") or entry.get("stepId") or "").strip(),
        "entry": entry,
        "pin": pin,
        "stagedPath": staged_path,
        "stagedMaterialization": staged_materialization,
        "finalPath": final_path,
        "existingCandidate": existing_candidate,
    }


def _require_cache_entry(connection: Any, *, safe_entry: dict[str, Any], cache_entry_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM artifact_cache_entries WHERE cache_entry_id = ? AND lifecycle_state = 'active'",
        (cache_entry_id,),
    ).fetchone()
    if row is None:
        raise ValueError("ARTIFACT_CACHE_ENTRY_NOT_ACTIVE")
    entry = _cache_entry_row_to_dict(row)
    for key in ("cacheEntryId", "artifactBlobId", "artifactKey", "stepId", "role", "sizeBytes", "sha256"):
        if safe_entry.get(key) is not None and str(safe_entry.get(key) or "") != str(entry.get(key) or ""):
            raise ValueError(f"FINAL_OUTPUT_PROMOTION_CACHE_ENTRY_SCOPE_STALE: {key}")
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
        raise ValueError("FINAL_OUTPUT_PROMOTION_ACTIVE_PIN_REQUIRED")
    return _pin_row_to_dict(row)


def _require_staged_materialization(connection: Any, *, entry: dict[str, Any], staged_path: Path) -> dict[str, Any]:
    resolved = staged_path.resolve()
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
        raise ValueError("FINAL_OUTPUT_PROMOTION_STAGED_MATERIALIZATION_REQUIRED")
    if not resolved.exists():
        raise ValueError("FINAL_OUTPUT_PROMOTION_STAGED_FILE_MISSING")
    size_bytes, sha256 = artifact_payload_stats(resolved)
    if int(size_bytes) != int(entry["sizeBytes"]) or str(sha256) != str(entry["sha256"]):
        raise ValueError("FINAL_OUTPUT_PROMOTION_STAGED_CHECKSUM_MISMATCH")
    return {
        "materializationId": row["materialization_id"],
        "artifactBlobId": row["artifact_blob_id"],
        "storageUri": row["storage_uri"],
        "localPath": row["local_path"],
    }


def _restore_or_reuse_final_output(cfg: RemoteRunnerConfig, target: dict[str, Any]) -> dict[str, Any]:
    final_path = Path(target["finalPath"])
    existing = _existing_candidate(target)
    if final_path.exists():
        _require_existing_final_output_matches(final_path, target["entry"])
        if existing is None:
            raise ValueError("FINAL_OUTPUT_PROMOTION_DESTINATION_EXISTS")
        return {
            "finalPath": str(final_path.resolve()),
            "finalStorageUri": final_path.resolve().as_uri(),
            "sizeBytes": int(target["entry"]["sizeBytes"]),
            "sha256": str(target["entry"]["sha256"]),
            "createdFinalOutput": False,
            "candidateOutputId": existing["candidateOutputId"],
        }
    restore = restore_artifact_payload(
        cfg,
        {
            "storageBackend": "local",
            "storageUri": Path(target["stagedPath"]).resolve().as_uri(),
            "localPath": str(Path(target["stagedPath"]).resolve()),
            "sizeBytes": int(target["entry"]["sizeBytes"]),
            "sha256": str(target["entry"]["sha256"]),
        },
        final_path,
    )
    return {
        "finalPath": restore["path"],
        "finalStorageUri": restore["storageUri"],
        "sizeBytes": int(restore["sizeBytes"]),
        "sha256": str(restore["sha256"]),
        "createdFinalOutput": True,
        "candidateOutputId": "",
    }


def _require_existing_final_output_matches(path: Path, entry: dict[str, Any]) -> None:
    size_bytes, sha256 = artifact_payload_stats(path)
    if int(size_bytes) != int(entry["sizeBytes"]) or str(sha256) != str(entry["sha256"]):
        raise ValueError("FINAL_OUTPUT_PROMOTION_DESTINATION_CHECKSUM_MISMATCH")


def _record_candidate_output(
    connection: Any,
    *,
    context: dict[str, Any],
    target: dict[str, Any],
    occurred_at: str,
) -> dict[str, Any]:
    output_key = target["artifactKey"]
    existing = connection.execute(
        """
        SELECT *
        FROM candidate_outputs
        WHERE run_id = ? AND attempt_id = ? AND lease_generation = ? AND output_key = ?
        """,
        (context["runId"], context["attemptId"], int(context["leaseGeneration"]), output_key),
    ).fetchone()
    if existing is not None and existing["adopted_artifact_id"]:
        raise ValueError("FINAL_OUTPUT_PROMOTION_CANDIDATE_ALREADY_ADOPTED")
    if existing is not None and str(existing["path"]) != str(target["finalPath"]):
        raise ValueError("FINAL_OUTPUT_PROMOTION_CANDIDATE_PATH_MISMATCH")
    candidate_id = (
        str(existing["candidate_output_id"])
        if existing is not None
        else _optional_text(target.get("candidateOutputId")) or f"cout_{uuid.uuid4().hex[:12]}"
    )
    connection.execute(
        """
        INSERT INTO candidate_outputs (
            candidate_output_id, run_id, attempt_id, lease_generation, output_key, path,
            size_bytes, sha256, observed_at, verification_state,
            verification_json, adopted_artifact_id, adopted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL)
        ON CONFLICT(run_id, attempt_id, lease_generation, output_key) DO UPDATE SET
            path = excluded.path,
            size_bytes = excluded.size_bytes,
            sha256 = excluded.sha256,
            observed_at = excluded.observed_at,
            verification_state = 'pending',
            verification_json = excluded.verification_json,
            adopted_artifact_id = NULL,
            adopted_at = NULL
        """,
        (
            candidate_id,
            context["runId"],
            context["attemptId"],
            int(context["leaseGeneration"]),
            output_key,
            str(target["finalPath"]),
            int(target["sizeBytes"]),
            target["sha256"],
            occurred_at,
            _stable_json(
                {
                    "observedAt": occurred_at,
                    "source": "rule-cache-restore-final-output-promotion",
                    "planHash": context["planHash"],
                }
            ),
        ),
    )
    return {"candidateOutputId": candidate_id, "created": existing is None}


def _recheck_targets(connection: Any, *, targets: list[dict[str, Any]]) -> None:
    for target in targets:
        _require_active_cache_entry(connection, target["entry"]["cacheEntryId"])
        _require_active_restore_pin(
            connection,
            entry=target["entry"],
            owner_id=target["pin"]["ownerId"],
        )
        _require_staged_materialization(
            connection,
            entry=target["entry"],
            staged_path=target["stagedPath"],
        )
        _require_existing_final_output_matches(Path(target["finalPath"]), target["entry"])


def _require_active_cache_entry(connection: Any, cache_entry_id: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM artifact_cache_entries WHERE cache_entry_id = ? AND lifecycle_state = 'active'",
        (cache_entry_id,),
    ).fetchone()
    if row is None:
        raise ValueError("ARTIFACT_CACHE_ENTRY_NOT_ACTIVE")


def _existing_candidate(target: dict[str, Any]) -> dict[str, Any] | None:
    existing = target.get("existingCandidate")
    return existing if isinstance(existing, dict) else None


def _existing_candidate_row(
    connection: Any,
    *,
    context: dict[str, Any],
    artifact_key: str,
    final_path: Path,
    entry: dict[str, Any],
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM candidate_outputs
        WHERE run_id = ? AND attempt_id = ? AND lease_generation = ? AND output_key = ?
        """,
        (context["runId"], context["attemptId"], int(context["leaseGeneration"]), artifact_key),
    ).fetchone()
    if row is None:
        return None
    if row["adopted_artifact_id"]:
        raise ValueError("FINAL_OUTPUT_PROMOTION_CANDIDATE_ALREADY_ADOPTED")
    if str(row["path"]) != str(final_path):
        raise ValueError("FINAL_OUTPUT_PROMOTION_CANDIDATE_PATH_MISMATCH")
    if str(row["sha256"] or "") != str(entry["sha256"]):
        raise ValueError("FINAL_OUTPUT_PROMOTION_CANDIDATE_CHECKSUM_MISMATCH")
    return {
        "candidateOutputId": row["candidate_output_id"],
        "outputKey": row["output_key"],
        "path": row["path"],
        "sha256": row["sha256"],
    }


def _declared_output_paths(
    cfg: RemoteRunnerConfig,
    *,
    run: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Path]:
    run_spec = json.loads(run["run_spec_json"] or "{}")
    result_dir = _resolve_execution_result_dir(
        cfg,
        run_id=context["runId"],
        attempt_id=context["attemptId"],
        lease_generation=context["leaseGeneration"],
    ).resolve()
    execution = run_spec.get("execution") if isinstance(run_spec.get("execution"), dict) else {}
    if isinstance(execution.get("outputs"), dict) and execution["outputs"]:
        return {key: Path(value).resolve() for key, value in _build_run_outputs(execution, result_dir).items()}
    outputs = run_spec.get("outputs") if isinstance(run_spec.get("outputs"), dict) else None
    if outputs:
        return _normalize_output_paths(outputs, result_dir=result_dir)
    workflow = run_spec.get("workflow") if isinstance(run_spec.get("workflow"), dict) else {}
    workflow_outputs = workflow.get("outputs") if isinstance(workflow.get("outputs"), dict) else None
    if workflow_outputs:
        return _normalize_workflow_output_paths(workflow_outputs, result_dir=result_dir)
    raise ValueError("FINAL_OUTPUT_PROMOTION_OUTPUT_PATHS_REQUIRED")


def _normalize_output_paths(outputs: dict[str, Any], *, result_dir: Path) -> dict[str, Path]:
    normalized: dict[str, Path] = {}
    for key, value in outputs.items():
        name = _required_text(key, "FINAL_OUTPUT_PROMOTION_OUTPUT_KEY_REQUIRED")
        normalized[name] = _normalize_output_path(value, result_dir=result_dir)
    return normalized


def _normalize_workflow_output_paths(outputs: dict[str, Any], *, result_dir: Path) -> dict[str, Path]:
    normalized: dict[str, Path] = {}
    for key, value in outputs.items():
        name = _required_text(key, "FINAL_OUTPUT_PROMOTION_OUTPUT_KEY_REQUIRED")
        if not isinstance(value, dict):
            raise ValueError("FINAL_OUTPUT_PROMOTION_WORKFLOW_OUTPUT_INVALID")
        normalized[name] = _normalize_output_path(value.get("path"), result_dir=result_dir)
    return normalized


def _normalize_output_path(value: Any, *, result_dir: Path) -> Path:
    raw = _required_text(value, "FINAL_OUTPUT_PROMOTION_OUTPUT_PATH_REQUIRED")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = result_dir / raw
    resolved = candidate.resolve()
    if not _is_relative_to(resolved, result_dir.resolve()):
        raise ValueError("FINAL_OUTPUT_PROMOTION_OUTPUT_PATH_UNMANAGED")
    return resolved


def _require_managed_final_output(
    cfg: RemoteRunnerConfig,
    *,
    context: dict[str, Any],
    final_path: Path,
) -> None:
    result_dir = _resolve_execution_result_dir(
        cfg,
        run_id=context["runId"],
        attempt_id=context["attemptId"],
        lease_generation=context["leaseGeneration"],
    ).resolve()
    if not _is_relative_to(final_path.resolve(), result_dir):
        raise ValueError("FINAL_OUTPUT_PROMOTION_OUTPUT_PATH_UNMANAGED")


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
        raise ValueError("FINAL_OUTPUT_PROMOTION_STAGED_TARGET_UNMANAGED")
    return target


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


def _require_run_revision(connection: Any, *, run_id: str, workflow_revision_id: str) -> dict[str, Any]:
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise KeyError(run_id)
    if str(run["workflow_revision_id"] or "") != workflow_revision_id:
        raise ValueError("RULE_CACHE_RESTORE_WORKFLOW_REVISION_MISMATCH")
    return dict(run)


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


def _public_result(
    schema_version: str,
    *,
    context: dict[str, Any],
    status: str,
    target_count: int,
    final_output_count: int,
    prepared_final_output_count: int,
    created_final_output_count: int,
    reused_final_output_count: int,
    candidate_output_count: int,
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
        "finalOutputCount": final_output_count,
        "preparedFinalOutputCount": prepared_final_output_count,
        "createdFinalOutputCount": created_final_output_count,
        "reusedFinalOutputCount": reused_final_output_count,
        "candidateOutputCount": candidate_output_count,
        "finalOutputMutated": status == "applied",
        "candidateOutputRecorded": status == "applied",
        "runStateMutated": False,
        "artifactLedgerMutated": False,
        "finalOutputOverwriteAllowed": False,
        "pathExposed": False,
        "storageUriExposed": False,
        "cacheKeyExposed": False,
        "ownerIdExposed": False,
    }
    if evidence_id:
        result["evidenceId"] = evidence_id
    return result


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


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
        raise ValueError("FINAL_OUTPUT_PROMOTION_LEASE_GENERATION_REQUIRED") from exc
    if generation < 1:
        raise ValueError("FINAL_OUTPUT_PROMOTION_LEASE_GENERATION_REQUIRED")
    return generation
