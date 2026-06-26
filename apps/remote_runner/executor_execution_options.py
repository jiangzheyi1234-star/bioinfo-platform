from __future__ import annotations

import re
from typing import Any

from .rule_partial_rerun_claim_preflight import rule_partial_rerun_claim_binding_blockers
from .workflow_engine_adapter import WorkflowRuntimeCommandError, normalize_forcerun_rules


RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION = "run-job-execution-options.v1"
SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION = "snakemake-rule-rerun-options.v1"
SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_VERSION = "snakemake-run-resume-options.v1"
RULE_OUTPUT_ADOPTION_SCOPE_SCHEMA_VERSION = "rule-output-adoption-scope.v1"
RUN_RESUME_EXECUTION_SCOPE_SCHEMA_VERSION = "run-resume-execution-scope.v1"
_PLAN_HASH = re.compile(r"^[a-f0-9]{64}$")
_SAFE_OUTPUT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_UNSAFE_RUN_RESUME_FLAGS = {"--forceall", "--touch", "--ignore-incomplete", "--forcerun"}


def _snakemake_execution_options(execution_options: dict | None) -> dict[str, Any]:
    if not execution_options:
        return {"forcerun_rules": None, "rerun_incomplete": False, "output_adoption_scope": None}
    if execution_options.get("schemaVersion") != RUN_JOB_EXECUTION_OPTIONS_SCHEMA_VERSION:
        raise WorkflowRuntimeCommandError("RUN_JOB_EXECUTION_OPTIONS_SCHEMA_UNSUPPORTED")
    snakemake = execution_options.get("snakemake")
    if not isinstance(snakemake, dict):
        return {"forcerun_rules": None, "rerun_incomplete": False, "output_adoption_scope": None}
    schema_version = snakemake.get("schemaVersion")
    if schema_version == SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_VERSION:
        return _run_resume_execution_options(execution_options, snakemake)
    if schema_version != SNAKEMAKE_RULE_RERUN_OPTIONS_SCHEMA_VERSION:
        raise WorkflowRuntimeCommandError("SNAKEMAKE_EXECUTION_OPTIONS_SCHEMA_UNSUPPORTED")
    raw_rules = snakemake.get("forcerunRules")
    if raw_rules is not None and not isinstance(raw_rules, list):
        raise WorkflowRuntimeCommandError("SNAKEMAKE_FORCERUN_RULES_INVALID")
    forcerun_rules = normalize_forcerun_rules(raw_rules)
    rerun_incomplete = bool(snakemake.get("rerunIncomplete"))
    output_adoption_scope = (
        _rule_output_adoption_scope(execution_options)
        if rerun_incomplete or forcerun_rules
        else None
    )
    return {
        "forcerun_rules": forcerun_rules,
        "rerun_incomplete": rerun_incomplete,
        "output_adoption_scope": output_adoption_scope,
    }


def _run_resume_execution_options(execution_options: dict, snakemake: dict) -> dict[str, Any]:
    if snakemake.get("rerunIncomplete") is not True:
        raise WorkflowRuntimeCommandError("RUN_RESUME_RERUN_INCOMPLETE_REQUIRED")
    raw_forcerun_rules = snakemake.get("forcerunRules")
    if raw_forcerun_rules is not None and not isinstance(raw_forcerun_rules, list):
        raise WorkflowRuntimeCommandError("RUN_RESUME_FORCERUN_RULES_INVALID")
    if normalize_forcerun_rules(raw_forcerun_rules):
        raise WorkflowRuntimeCommandError("RUN_RESUME_FORCERUN_RULES_FORBIDDEN")
    args_preview = snakemake.get("argsPreview")
    if not isinstance(args_preview, list) or "--rerun-incomplete" not in {str(item) for item in args_preview}:
        raise WorkflowRuntimeCommandError("RUN_RESUME_RERUN_INCOMPLETE_ARG_REQUIRED")
    if any(str(item) in _UNSAFE_RUN_RESUME_FLAGS - {"--rerun-incomplete"} for item in args_preview):
        raise WorkflowRuntimeCommandError("RUN_RESUME_UNSAFE_FLAG_FORBIDDEN")
    if "outputAdoptionScope" in execution_options:
        raise WorkflowRuntimeCommandError("RUN_RESUME_RULE_OUTPUT_ADOPTION_SCOPE_FORBIDDEN")
    _run_resume_scope(execution_options)
    return {
        "forcerun_rules": [],
        "rerun_incomplete": True,
        "output_adoption_scope": None,
    }


def _run_resume_scope(execution_options: dict) -> dict[str, Any]:
    scope = execution_options.get("resumeScope")
    if not isinstance(scope, dict):
        raise WorkflowRuntimeCommandError("RUN_RESUME_EXECUTION_SCOPE_REQUIRED")
    if scope.get("schemaVersion") != RUN_RESUME_EXECUTION_SCOPE_SCHEMA_VERSION:
        raise WorkflowRuntimeCommandError("RUN_RESUME_EXECUTION_SCOPE_SCHEMA_UNSUPPORTED")
    if scope.get("mode") != "run-resume":
        raise WorkflowRuntimeCommandError("RUN_RESUME_EXECUTION_SCOPE_MODE_UNSUPPORTED")
    source_plan_hash = str(scope.get("sourcePlanHash") or "").strip()
    if not _PLAN_HASH.fullmatch(source_plan_hash):
        raise WorkflowRuntimeCommandError("RUN_RESUME_SOURCE_PLAN_HASH_REQUIRED")
    if scope.get("pathExposed") or scope.get("storageUriExposed") or scope.get("checksumValueExposed"):
        raise WorkflowRuntimeCommandError("RUN_RESUME_EXECUTION_SCOPE_REDACTION_UNSAFE")
    if scope.get("finalizeRunOnAdoption") is not True:
        raise WorkflowRuntimeCommandError("RUN_RESUME_FINALIZE_ON_ADOPTION_REQUIRED")
    if scope.get("postExecutionAdoptionRequired") is not True:
        raise WorkflowRuntimeCommandError("RUN_RESUME_POST_EXECUTION_ADOPTION_REQUIRED")
    if scope.get("cacheAdoptionAllowed") is not False:
        raise WorkflowRuntimeCommandError("RUN_RESUME_CACHE_ADOPTION_FORBIDDEN")
    output_keys = _safe_output_key_list(
        _required_list(scope.get("outputKeys"), "RUN_RESUME_OUTPUT_SCOPE_REQUIRED"),
        error_code="RUN_RESUME_OUTPUT_SCOPE_KEY_UNSAFE",
    )
    if not output_keys:
        raise WorkflowRuntimeCommandError("RUN_RESUME_OUTPUT_SCOPE_REQUIRED")
    declared_count = _safe_int(scope.get("outputCount"))
    if declared_count != len(output_keys):
        raise WorkflowRuntimeCommandError("RUN_RESUME_OUTPUT_SCOPE_COUNT_MISMATCH")
    return scope


def _rule_output_adoption_scope(execution_options: dict) -> dict[str, Any]:
    scope = execution_options.get("outputAdoptionScope")
    if not isinstance(scope, dict):
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_REQUIRED")
    binding = execution_options.get("rulePartialRerunClaimBinding")
    if not isinstance(binding, dict):
        raise WorkflowRuntimeCommandError("RULE_PARTIAL_RERUN_CLAIM_BINDING_REQUIRED")
    binding_blockers = rule_partial_rerun_claim_binding_blockers(scope, binding)
    if binding_blockers:
        raise WorkflowRuntimeCommandError(binding_blockers[0])
    if scope.get("schemaVersion") != RULE_OUTPUT_ADOPTION_SCOPE_SCHEMA_VERSION:
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_SCHEMA_UNSUPPORTED")
    if scope.get("mode") != "rule-partial-rerun":
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_MODE_UNSUPPORTED")
    if scope.get("pathExposed") or scope.get("storageUriExposed"):
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_REDACTION_UNSAFE")
    if scope.get("finalizeRunOnAdoption") is not False:
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_FINALIZE_FORBIDDEN")
    source_plan_hash = str(scope.get("sourcePlanHash") or "").strip()
    if not _PLAN_HASH.fullmatch(source_plan_hash):
        raise WorkflowRuntimeCommandError("RULE_PARTIAL_RERUN_SOURCE_PLAN_HASH_REQUIRED")
    output_keys = _scoped_output_keys(scope.get("outputKeys"))
    declared_count = _safe_int(scope.get("outputCount"))
    if declared_count and declared_count != len(output_keys):
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_COUNT_MISMATCH")
    target_output_keys = _target_output_keys(scope.get("targetOutputKeys"), output_keys=output_keys)
    return {"output_keys": output_keys, "target_output_keys": target_output_keys, "finalize_run": False}


def _target_paths_from_output_keys(
    outputs: dict[str, str] | None,
    *,
    output_adoption_scope: dict[str, Any] | None,
) -> list[str] | None:
    if output_adoption_scope is None:
        return None
    target_output_keys = list(output_adoption_scope.get("target_output_keys") or [])
    if not target_output_keys:
        return None
    if not isinstance(outputs, dict):
        raise WorkflowRuntimeCommandError("RULE_RERUN_TARGET_OUTPUTS_UNAVAILABLE")
    target_paths: list[str] = []
    for output_key in target_output_keys:
        if output_key not in outputs:
            raise WorkflowRuntimeCommandError("RULE_RERUN_TARGET_OUTPUT_UNKNOWN")
        target_path = str(outputs.get(output_key) or "").strip()
        if not target_path:
            raise WorkflowRuntimeCommandError("RULE_RERUN_TARGET_OUTPUT_PATH_INVALID")
        if target_path.startswith("-"):
            raise WorkflowRuntimeCommandError("RULE_RERUN_TARGET_OUTPUT_PATH_UNSAFE")
        target_paths.append(target_path)
    return target_paths


def _finalize_run_after_artifact_collection(
    *,
    attempt_id: str | None,
    output_adoption_scope: dict[str, Any] | None,
) -> bool:
    if attempt_id is None:
        return False
    if output_adoption_scope is None:
        return True
    return bool(output_adoption_scope.get("finalize_run"))


def _scoped_artifact_collection(
    output_schema: dict | None,
    outputs: dict[str, str] | None,
    *,
    output_adoption_scope: dict[str, Any] | None,
) -> tuple[dict | None, dict[str, str] | None]:
    if output_adoption_scope is None:
        return output_schema, outputs
    if not isinstance(output_schema, dict) or not isinstance(outputs, dict):
        return output_schema, outputs
    output_keys = list(output_adoption_scope.get("output_keys") or [])
    output_key_set = set(output_keys)
    artifacts = output_schema.get("artifacts")
    if not isinstance(artifacts, list):
        return output_schema, outputs
    missing_outputs = [key for key in output_keys if key not in outputs]
    if missing_outputs:
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_UNKNOWN_OUTPUT")
    scoped_artifacts = []
    seen_artifact_keys: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_key = str(artifact.get("key") or "").strip()
        if artifact_key in output_key_set:
            scoped_artifacts.append(artifact)
            seen_artifact_keys.add(artifact_key)
    if seen_artifact_keys != output_key_set:
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_UNKNOWN_ARTIFACT")
    return {**output_schema, "artifacts": scoped_artifacts}, {
        key: value for key, value in outputs.items() if key in output_key_set
    }


def _scoped_output_keys(raw_keys: Any) -> list[str]:
    if not isinstance(raw_keys, list):
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_KEYS_INVALID")
    output_keys = _safe_output_key_list(raw_keys, error_code="RULE_RERUN_OUTPUT_ADOPTION_SCOPE_KEY_UNSAFE")
    if not output_keys:
        raise WorkflowRuntimeCommandError("RULE_RERUN_OUTPUT_ADOPTION_SCOPE_REQUIRED")
    return output_keys


def _target_output_keys(raw_keys: Any, *, output_keys: list[str]) -> list[str]:
    if not isinstance(raw_keys, list):
        raise WorkflowRuntimeCommandError("RULE_RERUN_TARGET_OUTPUT_KEYS_REQUIRED")
    target_output_keys = _safe_output_key_list(raw_keys, error_code="RULE_RERUN_TARGET_OUTPUT_KEY_UNSAFE")
    if not target_output_keys:
        raise WorkflowRuntimeCommandError("RULE_RERUN_TARGET_OUTPUT_KEYS_REQUIRED")
    if set(target_output_keys) != set(output_keys):
        raise WorkflowRuntimeCommandError("RULE_RERUN_TARGET_OUTPUT_KEYS_MISMATCH")
    return target_output_keys


def _safe_output_key_list(raw_keys: list[Any], *, error_code: str) -> list[str]:
    output_keys: list[str] = []
    seen: set[str] = set()
    for raw_key in raw_keys:
        output_key = str(raw_key or "").strip()
        if not _SAFE_OUTPUT_KEY.fullmatch(output_key):
            raise WorkflowRuntimeCommandError(error_code)
        if output_key not in seen:
            output_keys.append(output_key)
            seen.add(output_key)
    return output_keys


def _required_list(value: Any, error_code: str) -> list[Any]:
    if not isinstance(value, list):
        raise WorkflowRuntimeCommandError(error_code)
    return value


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
