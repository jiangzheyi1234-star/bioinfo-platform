from __future__ import annotations

import re
from typing import Any

from .config import RemoteRunnerConfig
from .execution_job_records import run_job_row_to_dict
from .storage_core import get_connection


RUN_RESUME_CLAIM_PREFLIGHT_SCHEMA_VERSION = "run-resume-claim-preflight.v1"
RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION = "run-job-execution-options.v1"
SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_VERSION = "snakemake-run-resume-options.v1"
RUN_RESUME_EXECUTION_SCOPE_SCHEMA_VERSION = "run-resume-execution-scope.v1"
READY_REASON = "RUN_RESUME_CLAIM_PREFLIGHT_READY"

_PLAN_HASH = re.compile(r"^[a-f0-9]{64}$")
_SAFE_OUTPUT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_RESUMABLE_SOURCE_ATTEMPT_STATES = {"failed", "fenced", "canceled", "cancelled"}
_UNSAFE_RUN_RESUME_FLAGS = {"--forceall", "--touch", "--ignore-incomplete", "--forcerun"}


def build_run_resume_execution_options(resume_plan: dict[str, Any]) -> dict[str, Any]:
    plan = _dict_value(resume_plan)
    snakemake = _dict_value(plan.get("snakemakeOptions"))
    latest_attempt = _dict_value(plan.get("latestAttempt"))
    workdir = _dict_value(plan.get("workdirEvidence"))
    output_audit = _dict_value(plan.get("incompleteOutputAudit"))
    adoption = _dict_value(plan.get("artifactAdoptionBoundary"))
    orchestration = _dict_value(plan.get("executorOrchestration"))
    output_keys = _output_audit_keys(output_audit)

    blockers: list[str] = []
    plan_hash = str(plan.get("planHash") or "").strip()
    if not _PLAN_HASH.fullmatch(plan_hash):
        blockers.append("RUN_RESUME_SOURCE_PLAN_HASH_REQUIRED")
    if plan.get("commandPreviewAvailable") is not True:
        blockers.append("RUN_RESUME_COMMAND_PREVIEW_REQUIRED")
    if snakemake.get("schemaVersion") != SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_VERSION:
        blockers.append("SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_UNSUPPORTED")
    if snakemake.get("rerunIncomplete") is not True:
        blockers.append("RUN_RESUME_RERUN_INCOMPLETE_REQUIRED")
    if "--rerun-incomplete" not in _string_list(snakemake.get("argsPreview")):
        blockers.append("RUN_RESUME_RERUN_INCOMPLETE_ARG_REQUIRED")
    if any(flag in _UNSAFE_RUN_RESUME_FLAGS for flag in _string_list(snakemake.get("argsPreview"))):
        blockers.append("RUN_RESUME_UNSAFE_FLAG_FORBIDDEN")
    if str(latest_attempt.get("attemptId") or "").strip() == "":
        blockers.append("RUN_RESUME_SOURCE_ATTEMPT_REQUIRED")
    if _safe_int(latest_attempt.get("leaseGeneration")) <= 0:
        blockers.append("RUN_RESUME_SOURCE_ATTEMPT_LEASE_REQUIRED")
    if str(latest_attempt.get("state") or "").lower() not in _RESUMABLE_SOURCE_ATTEMPT_STATES:
        blockers.append("RUN_RESUME_SOURCE_ATTEMPT_NOT_RESUMABLE")
    if workdir.get("workDirReusable") is not True:
        blockers.append("WORKDIR_REUSE_POLICY_UNPROVEN")
    if workdir.get("pathExposed") is True:
        blockers.append("WORKDIR_REUSE_POLICY_REDACTION_UNSAFE")
    if output_audit.get("available") is not True or not output_keys:
        blockers.append("INCOMPLETE_OUTPUT_AUDIT_UNPROVEN")
    if output_audit.get("pathExposed") is True:
        blockers.append("INCOMPLETE_OUTPUT_AUDIT_REDACTION_UNSAFE")
    if _safe_int(output_audit.get("unsafeOutputCount")) > 0:
        blockers.append("RUN_RESUME_UNSAFE_OUTPUTS_PRESENT")
    if _safe_int(output_audit.get("uncheckedOutputCount")) > 0:
        blockers.append("RUN_RESUME_UNCHECKED_OUTPUTS_PRESENT")
    if _safe_int(output_audit.get("unverifiedOutputCount")) > 0:
        blockers.append("RUN_RESUME_UNVERIFIED_OUTPUTS_PRESENT")
    if adoption.get("available") is not True and adoption.get("enabled") is not True:
        blockers.append("ARTIFACT_ADOPTION_BOUNDARY_UNPROVEN")
    if (
        adoption.get("pathExposed") is True
        or adoption.get("storageUriExposed") is True
        or adoption.get("checksumValueExposed") is True
    ):
        blockers.append("ARTIFACT_ADOPTION_BOUNDARY_REDACTION_UNSAFE")
    if adoption.get("postExecutionAdoptionRequired") is not True:
        blockers.append("RUN_RESUME_POST_EXECUTION_ADOPTION_REQUIRED")
    if orchestration.get("contractReady") is not True:
        blockers.append("RUN_RESUME_EXECUTOR_CONTRACT_UNPROVEN")
    if orchestration.get("executorReady") is not True:
        blockers.append("RUN_RESUME_EXECUTOR_NOT_READY")
    if orchestration.get("queueMutationAllowed") is not True:
        blockers.append("RUN_RESUME_QUEUE_MUTATION_BLOCKED")
    if orchestration.get("runStateMutationAllowed") is not True:
        blockers.append("RUN_RESUME_RUN_STATE_MUTATION_BLOCKED")
    if orchestration.get("mode") != "run-resume":
        blockers.append("RUN_RESUME_EXECUTOR_MODE_UNSUPPORTED")

    unique_blockers = _unique_strings(blockers)
    if unique_blockers:
        raise ValueError(unique_blockers[0])

    return {
        "schemaVersion": RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION,
        "snakemake": {
            "schemaVersion": SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_VERSION,
            "rerunIncomplete": True,
            "forcerunRules": [],
            "argsPreview": ["--rerun-incomplete"],
            "unsafeFlagsProhibited": _string_list(snakemake.get("unsafeFlagsProhibited")),
        },
        "resumeScope": {
            "schemaVersion": RUN_RESUME_EXECUTION_SCOPE_SCHEMA_VERSION,
            "mode": "run-resume",
            "sourcePlanHash": plan_hash,
            "sourceAttempt": {
                "attemptId": str(latest_attempt.get("attemptId") or ""),
                "attemptNumber": _safe_int(latest_attempt.get("attemptNumber")),
                "leaseGeneration": _safe_int(latest_attempt.get("leaseGeneration")),
                "state": str(latest_attempt.get("state") or ""),
            },
            "workdirReusePolicy": {
                "schemaVersion": str(workdir.get("schemaVersion") or ""),
                "workDirReusable": workdir.get("workDirReusable") is True,
                "managedRoot": workdir.get("managedRoot") is True,
                "directoryPresent": workdir.get("directoryPresent") is True,
                "runConfigPresent": workdir.get("runConfigPresent") is True,
                "snakemakeMetadataPresent": workdir.get("snakemakeMetadataPresent") is True,
                "pathExposed": False,
            },
            "outputCount": len(output_keys),
            "outputKeys": output_keys,
            "expectedOutputCount": _safe_int(output_audit.get("expectedOutputCount")),
            "verifiedOutputCount": _safe_int(output_audit.get("verifiedOutputCount")),
            "checksumVerifiedOutputCount": _safe_int(output_audit.get("checksumVerifiedOutputCount")),
            "rerunRequiredOutputCount": _safe_int(output_audit.get("rerunRequiredOutputCount")),
            "unsafeOutputCount": _safe_int(output_audit.get("unsafeOutputCount")),
            "unverifiedOutputCount": _safe_int(output_audit.get("unverifiedOutputCount")),
            "finalizeRunOnAdoption": True,
            "postExecutionAdoptionRequired": True,
            "cacheAdoptionAllowed": False,
            "pathExposed": False,
            "storageUriExposed": False,
            "checksumValueExposed": False,
        },
    }


def run_resume_execution_options_requested(execution_options: dict[str, Any] | None) -> bool:
    if not isinstance(execution_options, dict):
        return False
    snakemake = _dict_value(execution_options.get("snakemake"))
    scope = _dict_value(execution_options.get("resumeScope"))
    return (
        snakemake.get("schemaVersion") == SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_VERSION
        or scope.get("mode") == "run-resume"
    )


def build_run_resume_claim_preflight(
    execution_options: dict[str, Any] | None,
    *,
    run_id: str = "",
    attempt_id: str = "",
    lease_generation: int | None = None,
) -> dict[str, Any]:
    options = _dict_value(execution_options)
    snakemake = _dict_value(options.get("snakemake"))
    scope = _dict_value(options.get("resumeScope"))
    source_attempt = _dict_value(scope.get("sourceAttempt"))
    source_plan_hash = str(scope.get("sourcePlanHash") or "").strip()
    output_keys = _safe_output_keys(scope.get("outputKeys"))
    raw_forcerun_rules = snakemake.get("forcerunRules")
    forcerun_rules = _list_value(raw_forcerun_rules)

    blockers: list[str] = []
    if not run_resume_execution_options_requested(options):
        blockers.append("RUN_RESUME_EXECUTION_OPTIONS_NOT_REQUESTED")
    if options.get("schemaVersion") != RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION:
        blockers.append("RUN_JOB_EXECUTION_OPTIONS_SCHEMA_UNSUPPORTED")
    if snakemake.get("schemaVersion") != SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_VERSION:
        blockers.append("SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_UNSUPPORTED")
    if snakemake.get("rerunIncomplete") is not True:
        blockers.append("RUN_RESUME_RERUN_INCOMPLETE_REQUIRED")
    if raw_forcerun_rules is not None and not isinstance(raw_forcerun_rules, list):
        blockers.append("RUN_RESUME_FORCERUN_RULES_INVALID")
    if forcerun_rules:
        blockers.append("RUN_RESUME_FORCERUN_RULES_FORBIDDEN")
    if "--rerun-incomplete" not in _string_list(snakemake.get("argsPreview")):
        blockers.append("RUN_RESUME_RERUN_INCOMPLETE_ARG_REQUIRED")
    if any(flag in _UNSAFE_RUN_RESUME_FLAGS for flag in _string_list(snakemake.get("argsPreview"))):
        blockers.append("RUN_RESUME_UNSAFE_FLAG_FORBIDDEN")
    if scope.get("schemaVersion") != RUN_RESUME_EXECUTION_SCOPE_SCHEMA_VERSION:
        blockers.append("RUN_RESUME_EXECUTION_SCOPE_SCHEMA_UNSUPPORTED")
    if scope.get("mode") != "run-resume":
        blockers.append("RUN_RESUME_EXECUTION_SCOPE_MODE_UNSUPPORTED")
    if not _PLAN_HASH.fullmatch(source_plan_hash):
        blockers.append("RUN_RESUME_SOURCE_PLAN_HASH_REQUIRED")
    if not str(source_attempt.get("attemptId") or "").strip():
        blockers.append("RUN_RESUME_SOURCE_ATTEMPT_REQUIRED")
    if _safe_int(source_attempt.get("leaseGeneration")) <= 0:
        blockers.append("RUN_RESUME_SOURCE_ATTEMPT_LEASE_REQUIRED")
    if str(source_attempt.get("state") or "").lower() not in _RESUMABLE_SOURCE_ATTEMPT_STATES:
        blockers.append("RUN_RESUME_SOURCE_ATTEMPT_NOT_RESUMABLE")
    if not output_keys:
        raw_output_keys = scope.get("outputKeys")
        blockers.append(
            "RUN_RESUME_OUTPUT_SCOPE_REQUIRED"
            if not isinstance(raw_output_keys, list) or not raw_output_keys
            else "RUN_RESUME_OUTPUT_SCOPE_KEY_UNSAFE"
        )
    if _safe_int(scope.get("outputCount")) != len(output_keys):
        blockers.append("RUN_RESUME_OUTPUT_SCOPE_COUNT_MISMATCH")
    if scope.get("finalizeRunOnAdoption") is not True:
        blockers.append("RUN_RESUME_FINALIZE_ON_ADOPTION_REQUIRED")
    if scope.get("postExecutionAdoptionRequired") is not True:
        blockers.append("RUN_RESUME_POST_EXECUTION_ADOPTION_REQUIRED")
    if scope.get("cacheAdoptionAllowed") is not False:
        blockers.append("RUN_RESUME_CACHE_ADOPTION_FORBIDDEN")
    if scope.get("pathExposed") is True or scope.get("storageUriExposed") is True:
        blockers.append("RUN_RESUME_EXECUTION_SCOPE_REDACTION_UNSAFE")
    if scope.get("checksumValueExposed") is True:
        blockers.append("RUN_RESUME_EXECUTION_SCOPE_CHECKSUM_REDACTION_UNSAFE")
    if not str(run_id or "").strip():
        blockers.append("RUN_ID_REQUIRED")
    if not str(attempt_id or "").strip():
        blockers.append("ATTEMPT_ID_REQUIRED")
    if _safe_int(lease_generation) <= 0:
        blockers.append("LEASE_GENERATION_REQUIRED")

    unique_blockers = _unique_strings(blockers)
    return _preflight_result(
        unique_blockers,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        source_plan_hash=source_plan_hash,
        source_attempt=source_attempt,
        output_keys=output_keys,
        rerun_incomplete=snakemake.get("rerunIncomplete") is True,
        forcerun_rule_count=len(forcerun_rules),
        finalize_run=scope.get("finalizeRunOnAdoption") is True,
        path_exposed=scope.get("pathExposed") is True,
        storage_uri_exposed=scope.get("storageUriExposed") is True,
        checksum_value_exposed=scope.get("checksumValueExposed") is True,
    )


def validate_run_resume_claim_preflight(
    execution_options: dict[str, Any] | None,
    *,
    run_id: str = "",
    attempt_id: str = "",
    lease_generation: int | None = None,
) -> dict[str, Any]:
    preflight = build_run_resume_claim_preflight(
        execution_options,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    if preflight.get("claimReady") is not True:
        raise ValueError(str(preflight.get("reasonCode") or "RUN_RESUME_CLAIM_PREFLIGHT_UNPROVEN"))
    return preflight


def validate_run_resume_claim_state(
    cfg: RemoteRunnerConfig,
    execution_options: dict[str, Any] | None,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> dict[str, Any]:
    preflight = build_run_resume_claim_preflight(
        execution_options,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    options = _dict_value(execution_options)
    scope = _dict_value(options.get("resumeScope"))
    source_attempt_ref = _dict_value(scope.get("sourceAttempt"))
    source_attempt_id = str(source_attempt_ref.get("attemptId") or "").strip()
    blockers = list(preflight.get("blockedReasonCodes") or [])
    with get_connection(cfg) as connection:
        job = connection.execute("SELECT * FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        attempt = connection.execute("SELECT * FROM run_attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        lease = connection.execute("SELECT * FROM run_leases WHERE run_id = ?", (run_id,)).fetchone()
        source_attempt = (
            connection.execute("SELECT * FROM run_attempts WHERE attempt_id = ?", (source_attempt_id,)).fetchone()
            if source_attempt_id
            else None
        )
        if job is None:
            blockers.append("RUN_RESUME_CLAIM_JOB_NOT_FOUND")
        elif str(job["state"]) != "claimed":
            blockers.append("RUN_RESUME_CLAIM_JOB_NOT_CLAIMED")
        if attempt is None:
            blockers.append("RUN_RESUME_CLAIM_ATTEMPT_NOT_FOUND")
        else:
            if str(attempt["run_id"]) != run_id:
                blockers.append("RUN_RESUME_CLAIM_ATTEMPT_RUN_MISMATCH")
            if str(attempt["state"]) != "running":
                blockers.append("RUN_RESUME_CLAIM_ATTEMPT_NOT_RUNNING")
            if _safe_int(attempt["lease_generation"]) != _safe_int(lease_generation):
                blockers.append("RUN_RESUME_CLAIM_ATTEMPT_LEASE_MISMATCH")
            if job is not None and str(attempt["job_id"]) != str(job["job_id"]):
                blockers.append("RUN_RESUME_CLAIM_ATTEMPT_JOB_MISMATCH")
        if lease is None:
            blockers.append("RUN_RESUME_CLAIM_ACTIVE_LEASE_REQUIRED")
        else:
            if str(lease["attempt_id"]) != attempt_id:
                blockers.append("RUN_RESUME_CLAIM_ACTIVE_LEASE_ATTEMPT_MISMATCH")
            if _safe_int(lease["lease_generation"]) != _safe_int(lease_generation):
                blockers.append("RUN_RESUME_CLAIM_ACTIVE_LEASE_GENERATION_MISMATCH")
            if str(lease["state"]) != "active":
                blockers.append("RUN_RESUME_CLAIM_ACTIVE_LEASE_NOT_ACTIVE")
        if job is not None and run_job_row_to_dict(job).get("executionOptions") != (execution_options or {}):
            blockers.append("RUN_RESUME_CLAIM_EXECUTION_OPTIONS_MISMATCH")
        if source_attempt is None:
            blockers.append("RUN_RESUME_CLAIM_SOURCE_ATTEMPT_NOT_FOUND")
        else:
            if str(source_attempt["run_id"]) != run_id:
                blockers.append("RUN_RESUME_CLAIM_SOURCE_ATTEMPT_RUN_MISMATCH")
            if str(source_attempt["state"]).lower() not in _RESUMABLE_SOURCE_ATTEMPT_STATES:
                blockers.append("RUN_RESUME_CLAIM_SOURCE_ATTEMPT_NOT_RESUMABLE")
            if _safe_int(source_attempt["lease_generation"]) != _safe_int(source_attempt_ref.get("leaseGeneration")):
                blockers.append("RUN_RESUME_CLAIM_SOURCE_ATTEMPT_LEASE_MISMATCH")
            if str(source_attempt["attempt_id"]) == attempt_id:
                blockers.append("RUN_RESUME_CLAIM_SOURCE_ATTEMPT_REUSED_AS_TARGET")
            if attempt is not None and str(source_attempt["work_dir"]) != str(attempt["work_dir"]):
                blockers.append("RUN_RESUME_CLAIM_WORKDIR_REUSE_UNSATISFIED")

    unique_blockers = _unique_strings([str(item) for item in blockers])
    result = {
        **preflight,
        "claimReady": not unique_blockers,
        "reasonCode": READY_REASON if not unique_blockers else unique_blockers[0],
        "blockedReasonCodes": unique_blockers,
        "jobClaimed": "RUN_RESUME_CLAIM_JOB_NOT_CLAIMED" not in unique_blockers
        and "RUN_RESUME_CLAIM_JOB_NOT_FOUND" not in unique_blockers,
        "attemptRunning": "RUN_RESUME_CLAIM_ATTEMPT_NOT_RUNNING" not in unique_blockers
        and "RUN_RESUME_CLAIM_ATTEMPT_NOT_FOUND" not in unique_blockers,
        "activeLeaseMatchesAttempt": not any(
            item.startswith("RUN_RESUME_CLAIM_ACTIVE_LEASE") for item in unique_blockers
        ),
        "sourceAttemptReusable": not any(
            item.startswith("RUN_RESUME_CLAIM_SOURCE_ATTEMPT") for item in unique_blockers
        ),
        "workdirReuseSatisfied": "RUN_RESUME_CLAIM_WORKDIR_REUSE_UNSATISFIED" not in unique_blockers,
        "persistedExecutionOptionsMatch": "RUN_RESUME_CLAIM_EXECUTION_OPTIONS_MISMATCH" not in unique_blockers,
    }
    if result["claimReady"] is not True:
        raise ValueError(str(result.get("reasonCode") or "RUN_RESUME_CLAIM_PREFLIGHT_UNPROVEN"))
    return result


def _preflight_result(
    blockers: list[str],
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int | None,
    source_plan_hash: str,
    source_attempt: dict[str, Any],
    output_keys: list[str],
    rerun_incomplete: bool,
    forcerun_rule_count: int,
    finalize_run: bool,
    path_exposed: bool,
    storage_uri_exposed: bool,
    checksum_value_exposed: bool,
) -> dict[str, Any]:
    return {
        "schemaVersion": RUN_RESUME_CLAIM_PREFLIGHT_SCHEMA_VERSION,
        "available": True,
        "mode": "run-resume",
        "claimReady": not blockers,
        "reasonCode": READY_REASON if not blockers else blockers[0],
        "blockedReasonCodes": blockers,
        "runIdPresent": bool(str(run_id or "").strip()),
        "attemptIdPresent": bool(str(attempt_id or "").strip()),
        "leaseGenerationPresent": _safe_int(lease_generation) > 0,
        "sourcePlanHash": source_plan_hash,
        "sourcePlanHashPresent": bool(source_plan_hash),
        "sourceAttemptPresent": bool(str(source_attempt.get("attemptId") or "").strip()),
        "sourceAttemptState": str(source_attempt.get("state") or ""),
        "outputScopeReady": not any(item.startswith("RUN_RESUME_OUTPUT_SCOPE") for item in blockers),
        "outputCount": len(output_keys),
        "outputKeys": output_keys,
        "rerunIncomplete": rerun_incomplete,
        "forcerunRuleCount": forcerun_rule_count,
        "finalizeRunOnAdoption": finalize_run,
        "pathExposed": path_exposed,
        "storageUriExposed": storage_uri_exposed,
        "checksumValueExposed": checksum_value_exposed,
    }


def _output_audit_keys(output_audit: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for item in _list_value(output_audit.get("outputs")):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if _SAFE_OUTPUT_KEY.fullmatch(key) and key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def _safe_output_keys(raw_keys: Any) -> list[str]:
    if not isinstance(raw_keys, list):
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for raw_key in raw_keys:
        key = str(raw_key or "").strip()
        if not _SAFE_OUTPUT_KEY.fullmatch(key):
            return []
        if key not in seen:
            keys.append(key)
            seen.add(key)
    return keys


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _list_value(value) if str(item or "").strip()]


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
