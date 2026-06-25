from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifact_cache_storage import (
    ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
    ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
    release_artifact_cache_pins_record,
)
from .artifact_io import artifact_payload_stats
from .candidate_output_storage import adopt_verified_candidate_outputs, verify_candidate_outputs
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .execution_plan_hash import stable_plan_hash
from .executor_inputs import _build_run_outputs
from .executor_paths import _resolve_execution_result_dir
from .rule_cache_restore_plan import RULE_CACHE_RESTORE_PLAN_SCHEMA_VERSION
from .rule_restore_pin_policy import restore_pin_owner_id
from .storage_core import get_connection, now_iso
from .workflow_run_storage import StaleRunAttemptError


RULE_CACHE_RESTORE_ADOPTION_APPLIED_EVENT_TYPE = "rule.cache_restore.adoption_applied.v1"
RULE_CACHE_RESTORE_ADOPTION_APPLIED_SCHEMA_NAME = "RuleCacheRestoreAdoptionApplied"


def prepare_rule_cache_restore_adoption(
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
    targets = _adoption_targets(cfg, plan, context)
    adopted_count = sum(1 for target in targets if target["adoptedArtifactId"])
    active_pin_count = sum(len(target["activePinIds"]) for target in targets)
    return _public_result(
        "rule-cache-restore-adoption-prepare-result.v1",
        context=context,
        status="applied" if adopted_count == len(targets) else "ready",
        target_count=len(targets),
        adopted_count=adopted_count,
        pending_count=max(0, len(targets) - adopted_count),
        verified_count=0,
        released_pin_count=0,
        active_pin_count=active_pin_count,
        evidence_id="",
    )


def apply_rule_cache_restore_adoption(
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
    targets = _adoption_targets(cfg, plan, context)
    expected_outputs = {target["artifactKey"]: target["expectedOutput"] for target in targets}
    verification = verify_candidate_outputs(
        cfg,
        run_id=context["runId"],
        attempt_id=context["attemptId"],
        lease_generation=context["leaseGeneration"],
        expected_outputs=expected_outputs,
        output_keys=set(expected_outputs),
        verified_at=occurred_at,
    )
    if verification["rejected"] or verification["missing"]:
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_VERIFICATION_FAILED")

    adopted_before = sum(1 for target in targets if target["adoptedArtifactId"])
    adoption = adopt_verified_candidate_outputs(
        cfg,
        run_id=context["runId"],
        attempt_id=context["attemptId"],
        lease_generation=context["leaseGeneration"],
        expected_outputs=expected_outputs,
        finalize_run=False,
        adopted_at=occurred_at,
        lineage_predicate="h2ometa:cache_adopted",
        lineage_payload_extra={
            "adoptionSource": "rule_cache_restore",
            "planHash": plan_hash,
        },
    )
    pin_ids = sorted({pin_id for target in targets for pin_id in target["activePinIds"]})
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
        release_artifact_cache_pins_record(connection, pin_ids=pin_ids, released_at=occurred_at)
        evidence = append_evidence_event(
            connection,
            event_type=RULE_CACHE_RESTORE_ADOPTION_APPLIED_EVENT_TYPE,
            schema_name=RULE_CACHE_RESTORE_ADOPTION_APPLIED_SCHEMA_NAME,
            subject_kind="run_rule_cache_restore",
            subject_id=context["runId"],
            producer="rule_cache_restore_adoption_storage",
            occurred_at=occurred_at,
            payload={
                "schemaVersion": "rule-cache-restore-adoption-applied.v1",
                "runId": context["runId"],
                "workflowRevisionId": context["workflowRevisionId"],
                "planHash": plan_hash,
                "attemptId": context["attemptId"],
                "leaseGeneration": context["leaseGeneration"],
                "actorPresent": bool(_optional_text(actor)),
                "reasonCode": "rule_cache_restore_adoption_apply",
                "reasonProvided": bool(_optional_text(reason)),
                "targetCount": len(targets),
                "verifiedCandidateOutputCount": len(verification["verified"]),
                "adoptedArtifactCount": len(adoption["artifactIds"]),
                "newlyAdoptedArtifactCount": max(0, len(adoption["artifactIds"]) - adopted_before),
                "alreadyAdoptedArtifactCount": adopted_before,
                "releasedPinCount": len(pin_ids),
                "candidateOutputIds": [target["candidateOutputId"] for target in targets],
                "artifactIds": adoption["artifactIds"],
                "cacheEntryIds": [target["cacheEntryId"] for target in targets],
                "cachePinIds": pin_ids,
                "outputKeys": [target["artifactKey"] for target in targets],
                "outputPaths": [target["expectedOutput"]["path"] for target in targets],
                "sha256": [target["expectedOutput"]["sha256"] for target in targets],
            },
        )
        connection.commit()
    return _public_result(
        "rule-cache-restore-adoption-apply-result.v1",
        context=context,
        status="applied",
        target_count=len(targets),
        adopted_count=len(adoption["artifactIds"]),
        pending_count=0,
        verified_count=len(verification["verified"]),
        released_pin_count=len(pin_ids),
        active_pin_count=0,
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
        "attemptId": _required_text(attempt_id, "RULE_CACHE_RESTORE_ADOPTION_ATTEMPT_ID_REQUIRED"),
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
    promotion = plan.get("finalOutputPromotionState")
    if not isinstance(promotion, dict) or promotion.get("state") != "applied":
        raise ValueError("RULE_CACHE_RESTORE_FINAL_OUTPUT_PROMOTION_REQUIRED")
    eligibility = plan.get("cacheEligibility") if isinstance(plan.get("cacheEligibility"), dict) else {}
    if eligibility.get("outputInvalidationApplied") is not True and not _all_targets_adopted(promotion):
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_OUTPUT_INVALIDATION_REQUIRED")
    policy = plan.get("stagedFilePolicy") if isinstance(plan.get("stagedFilePolicy"), dict) else {}
    if policy.get("attemptFinalOutputPromotionAllowed") is not True and not _all_targets_adopted(promotion):
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_PROMOTION_POLICY_REQUIRED")


def _all_targets_adopted(promotion: dict[str, Any]) -> bool:
    try:
        target_count = int(promotion.get("targetCount") or 0)
        adopted_count = int(promotion.get("adoptedCandidateOutputCount") or 0)
    except (TypeError, ValueError):
        return False
    return target_count > 0 and adopted_count >= target_count


def _adoption_targets(
    cfg: RemoteRunnerConfig,
    plan: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    outputs = _eligible_outputs(plan)
    if not outputs:
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_OUTPUT_EMPTY")
    owner_id = restore_pin_owner_id(context["attemptId"], context["leaseGeneration"])
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
        run_spec = json.loads(run["run_spec_json"] or "{}")
        output_paths = _declared_output_paths(cfg, run_spec=run_spec, context=context)
        output_specs = _output_schema_specs(run_spec)
        targets = [
            _adoption_target(
                connection,
                context=context,
                output=output,
                output_paths=output_paths,
                output_specs=output_specs,
                owner_id=owner_id,
            )
            for output in outputs
        ]
    return targets


def _adoption_target(
    connection: Any,
    *,
    context: dict[str, Any],
    output: dict[str, Any],
    output_paths: dict[str, Path],
    output_specs: dict[str, dict[str, str]],
    owner_id: str,
) -> dict[str, Any]:
    artifact_key = _required_text(output.get("artifactKey"), "RULE_CACHE_RESTORE_ADOPTION_OUTPUT_KEY_REQUIRED")
    entry = output.get("cacheEntry") if isinstance(output.get("cacheEntry"), dict) else {}
    cache_entry_id = _required_text(entry.get("cacheEntryId"), "RULE_CACHE_RESTORE_ADOPTION_CACHE_ENTRY_REQUIRED")
    sha256 = _required_text(entry.get("sha256"), "RULE_CACHE_RESTORE_ADOPTION_SHA_REQUIRED")
    expected_path = output_paths.get(artifact_key)
    if expected_path is None:
        raise ValueError(f"RULE_CACHE_RESTORE_ADOPTION_OUTPUT_PATH_REQUIRED: {artifact_key}")
    spec = output_specs.get(artifact_key)
    if spec is None:
        spec = _cache_entry_output_spec(connection, cache_entry_id=cache_entry_id)
    candidate = _require_candidate(
        connection,
        context=context,
        artifact_key=artifact_key,
        expected_path=expected_path,
        sha256=sha256,
    )
    active_pin_ids = _active_restore_pin_ids(
        connection,
        cache_entry_id=cache_entry_id,
        owner_id=owner_id,
    )
    if not candidate["adoptedArtifactId"] and not active_pin_ids:
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_ACTIVE_PIN_REQUIRED")
    expected = {
        "path": str(expected_path),
        "kind": spec["kind"],
        "mimeType": spec["mimeType"],
        "sha256": sha256,
    }
    step_id = spec.get("stepId") or _optional_text(output.get("stepId"))
    if step_id:
        expected["stepId"] = step_id
    return {
        "artifactKey": artifact_key,
        "cacheEntryId": cache_entry_id,
        "candidateOutputId": candidate["candidateOutputId"],
        "adoptedArtifactId": candidate["adoptedArtifactId"],
        "activePinIds": active_pin_ids,
        "expectedOutput": expected,
    }


def _eligible_outputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in plan.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        for output in rule.get("outputs") or []:
            if not isinstance(output, dict) or output.get("cacheHit") is not True:
                continue
            artifact_key = str(output.get("artifactKey") or "").strip()
            if not artifact_key or artifact_key in seen:
                continue
            cache_entry = output.get("cacheEntry") if isinstance(output.get("cacheEntry"), dict) else {}
            if not cache_entry:
                continue
            outputs.append(output)
            seen.add(artifact_key)
    return outputs


def _require_candidate(
    connection: Any,
    *,
    context: dict[str, Any],
    artifact_key: str,
    expected_path: Path,
    sha256: str,
) -> dict[str, str]:
    row = connection.execute(
        """
        SELECT *
        FROM candidate_outputs
        WHERE run_id = ? AND attempt_id = ? AND lease_generation = ? AND output_key = ?
        """,
        (context["runId"], context["attemptId"], context["leaseGeneration"], artifact_key),
    ).fetchone()
    if row is None:
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_CANDIDATE_REQUIRED")
    if str(row["path"]) != str(expected_path):
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_CANDIDATE_PATH_MISMATCH")
    if str(row["sha256"] or "") != sha256:
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_CANDIDATE_CHECKSUM_MISMATCH")
    size_bytes, current_sha = artifact_payload_stats(expected_path)
    if str(current_sha) != sha256 or int(size_bytes) != int(row["size_bytes"] or -1):
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_CANDIDATE_CHANGED")
    return {
        "candidateOutputId": str(row["candidate_output_id"]),
        "adoptedArtifactId": str(row["adopted_artifact_id"] or ""),
    }


def _active_restore_pin_ids(connection: Any, *, cache_entry_id: str, owner_id: str) -> list[str]:
    rows = connection.execute(
        """
        SELECT cache_pin_id
        FROM artifact_cache_pins
        WHERE cache_entry_id = ?
          AND pin_scope = ?
          AND owner_kind = ?
          AND owner_id = ?
          AND state = 'active'
        ORDER BY cache_pin_id ASC
        """,
        (
            cache_entry_id,
            ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
            ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
            owner_id,
        ),
    ).fetchall()
    return [str(row["cache_pin_id"]) for row in rows]


def _declared_output_paths(
    cfg: RemoteRunnerConfig,
    *,
    run_spec: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Path]:
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
        return {key: _normalize_output_path(value, result_dir=result_dir) for key, value in outputs.items()}
    workflow = run_spec.get("workflow") if isinstance(run_spec.get("workflow"), dict) else {}
    workflow_outputs = workflow.get("outputs") if isinstance(workflow.get("outputs"), dict) else None
    if workflow_outputs:
        return {key: _normalize_output_path(value, result_dir=result_dir) for key, value in workflow_outputs.items()}
    raise ValueError("RULE_CACHE_RESTORE_ADOPTION_OUTPUT_PATHS_REQUIRED")


def _normalize_output_path(value: Any, *, result_dir: Path) -> Path:
    raw = value.get("path") if isinstance(value, dict) else value
    path = Path(_required_text(raw, "RULE_CACHE_RESTORE_ADOPTION_OUTPUT_PATH_REQUIRED"))
    resolved = path if path.is_absolute() else result_dir / path
    return resolved.resolve()


def _output_schema_specs(run_spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    output_schema = run_spec.get("outputSchema")
    if not isinstance(output_schema, dict):
        return _workflow_output_specs(run_spec)
    artifacts = output_schema.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return _workflow_output_specs(run_spec)
    specs: dict[str, dict[str, str]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("RULE_CACHE_RESTORE_ADOPTION_OUTPUT_SCHEMA_INVALID")
        key = _required_text(artifact.get("key"), "RULE_CACHE_RESTORE_ADOPTION_OUTPUT_SCHEMA_KEY_REQUIRED")
        specs[key] = {
            "kind": _required_text(artifact.get("kind"), f"RULE_CACHE_RESTORE_ADOPTION_OUTPUT_KIND_REQUIRED: {key}"),
            "mimeType": _required_text(
                artifact.get("mimeType"),
                f"RULE_CACHE_RESTORE_ADOPTION_OUTPUT_MIME_TYPE_REQUIRED: {key}",
            ),
        }
        step_id = _optional_text(artifact.get("stepId"))
        if step_id:
            specs[key]["stepId"] = step_id
    return specs


def _workflow_output_specs(run_spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    workflow = run_spec.get("workflow") if isinstance(run_spec.get("workflow"), dict) else {}
    outputs = workflow.get("outputs") if isinstance(workflow.get("outputs"), dict) else {}
    specs: dict[str, dict[str, str]] = {}
    for key, value in outputs.items():
        if not isinstance(value, dict):
            continue
        kind = _optional_text(value.get("kind"))
        mime_type = _optional_text(value.get("mimeType"))
        if not kind or not mime_type:
            continue
        specs[_required_text(key, "RULE_CACHE_RESTORE_ADOPTION_OUTPUT_SCHEMA_KEY_REQUIRED")] = {
            "kind": kind,
            "mimeType": mime_type,
            **({"stepId": str(value["step"])} if _optional_text(value.get("step")) else {}),
        }
    return specs


def _cache_entry_output_spec(connection: Any, *, cache_entry_id: str) -> dict[str, str]:
    row = connection.execute(
        """
        SELECT artifacts.kind, artifacts.mime_type, entries.step_id
        FROM artifact_cache_entries AS entries
        LEFT JOIN artifacts
          ON artifacts.artifact_id = entries.artifact_id
        WHERE entries.cache_entry_id = ?
        """,
        (cache_entry_id,),
    ).fetchone()
    if row is None:
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_CACHE_ENTRY_REQUIRED")
    kind = _optional_text(row["kind"])
    mime_type = _optional_text(row["mime_type"])
    if not kind or not mime_type:
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_CACHE_ARTIFACT_METADATA_REQUIRED")
    return {
        "kind": kind,
        "mimeType": mime_type,
        **({"stepId": str(row["step_id"])} if _optional_text(row["step_id"]) else {}),
    }


def _require_active_lease(
    connection: Any,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> None:
    lease = connection.execute(
        """
        SELECT attempt_id, lease_generation, state
        FROM run_leases
        WHERE run_id = ?
        """,
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
    row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    if str(row["workflow_revision_id"] or "") != workflow_revision_id:
        raise ValueError("RULE_CACHE_RESTORE_ADOPTION_WORKFLOW_REVISION_MISMATCH")
    return dict(row)


def _public_result(
    schema_version: str,
    *,
    context: dict[str, Any],
    status: str,
    target_count: int,
    adopted_count: int,
    pending_count: int,
    verified_count: int,
    released_pin_count: int,
    active_pin_count: int,
    evidence_id: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": schema_version,
        "runId": context["runId"],
        "planHash": context["planHash"],
        "status": status,
        "attemptId": context["attemptId"],
        "leaseGeneration": context["leaseGeneration"],
        "targetCount": int(target_count),
        "adoptedArtifactCount": int(adopted_count),
        "pendingAdoptionCount": int(pending_count),
        "verifiedCandidateOutputCount": int(verified_count),
        "releasedPinCount": int(released_pin_count),
        "activePinCount": int(active_pin_count),
        "evidenceId": evidence_id,
        "runStateMutated": False,
        "retryEnqueued": False,
        "artifactIdsExposed": False,
        "pathExposed": False,
        "storageUriExposed": False,
        "cacheKeyExposed": False,
        "ownerIdExposed": False,
    }


def _required_text(value: object, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _required_generation(value: object) -> int:
    try:
        generation = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("LEASE_GENERATION_REQUIRED") from exc
    if generation <= 0:
        raise ValueError("LEASE_GENERATION_REQUIRED")
    return generation


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
