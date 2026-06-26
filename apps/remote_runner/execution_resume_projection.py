from __future__ import annotations

from typing import Any

from .errors import RemoteRunnerOperationBlockedError


RUN_RESUME_PUBLIC_PLAN_SCHEMA_VERSION = "run-resume-public-plan.v1"


def resume_blocked(plan: dict[str, Any], code: str) -> RemoteRunnerOperationBlockedError:
    return RemoteRunnerOperationBlockedError(code, resume_blocked_payload(plan, code))


def resume_blocked_payload(plan: dict[str, Any], code: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": str(plan.get("message") or "resumePlan is blocked."),
        "resumePlan": public_resume_plan(plan, denial_code=code),
    }


def public_resume_plan(plan: dict[str, Any], *, denial_code: str = "") -> dict[str, Any]:
    workdir = _dict_value(plan.get("workdirEvidence"))
    output_audit = _dict_value(plan.get("incompleteOutputAudit"))
    adoption = _dict_value(plan.get("artifactAdoptionBoundary"))
    orchestration = _dict_value(plan.get("executorOrchestration"))
    snakemake = _dict_value(plan.get("snakemakeOptions"))
    readiness = _dict_value(plan.get("activationReadiness"))
    route_disabled = denial_code == "RUN_RESUME_MUTATION_API_DISABLED"
    return {
        "schemaVersion": RUN_RESUME_PUBLIC_PLAN_SCHEMA_VERSION,
        "planHash": str(plan.get("planHash") or ""),
        "runId": str(plan.get("runId") or ""),
        "workflowRevisionIdPresent": bool(str(plan.get("workflowRevisionId") or "").strip()),
        "strategy": str(plan.get("strategy") or ""),
        "supported": bool(plan.get("supported")),
        "eligible": bool(plan.get("eligible")),
        "eligibleNow": bool(plan.get("eligibleNow")),
        "executionEnabled": False if route_disabled else plan.get("executionEnabled") is True,
        "executionReasonCode": denial_code if route_disabled else str(plan.get("executionReasonCode") or ""),
        "commandPreviewAvailable": bool(plan.get("commandPreviewAvailable")),
        "reasonCode": str(plan.get("reasonCode") or ""),
        "blockedReasonCodes": _blocked_reasons(plan, denial_code),
        "requiresBeforeExecution": _string_list(plan.get("requiresBeforeExecution")),
        "runStatus": str(plan.get("runStatus") or ""),
        "jobState": str(plan.get("jobState") or ""),
        "attemptCount": _safe_int(plan.get("attemptCount")),
        "latestAttempt": _public_latest_attempt(plan.get("latestAttempt")),
        "workdirEvidence": _public_workdir_evidence(workdir),
        "incompleteOutputAudit": _public_output_audit(output_audit),
        "artifactAdoptionBoundary": _public_artifact_adoption_boundary(adoption),
        "executorOrchestration": _public_executor_orchestration(orchestration, route_disabled=route_disabled),
        "snakemakeOptions": _public_snakemake_options(snakemake),
        "activationReadiness": _public_activation_readiness(readiness, route_disabled=route_disabled),
    }


def _public_latest_attempt(value: Any) -> dict[str, Any]:
    attempt = _dict_value(value)
    return {
        "attemptPresent": bool(str(attempt.get("attemptId") or "").strip()),
        "attemptNumber": _safe_int(attempt.get("attemptNumber")),
        "leaseGeneration": _safe_int(attempt.get("leaseGeneration")),
        "state": str(attempt.get("state") or ""),
        "exitCodePresent": attempt.get("exitCode") is not None,
        "finishedAtPresent": bool(str(attempt.get("finishedAt") or "").strip()),
    }


def _public_workdir_evidence(workdir: dict[str, Any]) -> dict[str, Any]:
    latest = _dict_value(workdir.get("latestAttempt"))
    return {
        "schemaVersion": str(workdir.get("schemaVersion") or ""),
        "available": bool(workdir.get("available")),
        "workDirReusable": bool(workdir.get("workDirReusable")),
        "pathExposed": bool(workdir.get("pathExposed")),
        "managedRoot": bool(workdir.get("managedRoot")),
        "directoryPresent": bool(workdir.get("directoryPresent")),
        "runConfigPresent": bool(workdir.get("runConfigPresent")),
        "snakemakeMetadataPresent": bool(workdir.get("snakemakeMetadataPresent")),
        "latestAttempt": {
            "attemptPresent": bool(str(latest.get("attemptId") or "").strip()),
            "attemptNumber": _safe_int(latest.get("attemptNumber")),
            "leaseGeneration": _safe_int(latest.get("leaseGeneration")),
            "state": str(latest.get("state") or ""),
        },
        "reasonCode": str(workdir.get("reasonCode") or ""),
        "blockedReasonCodes": _string_list(workdir.get("blockedReasonCodes")),
    }


def _public_output_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": str(audit.get("schemaVersion") or ""),
        "available": bool(audit.get("available")),
        "pathExposed": bool(audit.get("pathExposed")),
        "configAvailable": bool(audit.get("configAvailable")),
        "expectedOutputCount": _safe_int(audit.get("expectedOutputCount")),
        "checkedOutputCount": _safe_int(audit.get("checkedOutputCount")),
        "existingOutputCount": _safe_int(audit.get("existingOutputCount")),
        "missingOutputCount": _safe_int(audit.get("missingOutputCount")),
        "verifiedOutputCount": _safe_int(audit.get("verifiedOutputCount")),
        "checksumVerifiedOutputCount": _safe_int(audit.get("checksumVerifiedOutputCount")),
        "rerunRequiredOutputCount": _safe_int(audit.get("rerunRequiredOutputCount")),
        "rerunRequired": bool(audit.get("rerunRequired")),
        "unsafeOutputCount": _safe_int(audit.get("unsafeOutputCount")),
        "uncheckedOutputCount": _safe_int(audit.get("uncheckedOutputCount")),
        "unverifiedOutputCount": _safe_int(audit.get("unverifiedOutputCount")),
        "outputCount": _collection_size(audit.get("outputs")),
        "reasonCode": str(audit.get("reasonCode") or ""),
    }


def _public_artifact_adoption_boundary(adoption: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": str(adoption.get("schemaVersion") or ""),
        "enabled": bool(adoption.get("enabled")),
        "available": bool(adoption.get("available")),
        "reasonCode": str(adoption.get("reasonCode") or ""),
        "verifiedOutputCount": _safe_int(adoption.get("verifiedOutputCount")),
        "checksumVerifiedOutputCount": _safe_int(adoption.get("checksumVerifiedOutputCount")),
        "retainedOutputCount": _safe_int(adoption.get("retainedOutputCount")),
        "rerunRequiredOutputCount": _safe_int(adoption.get("rerunRequiredOutputCount")),
        "unsafeOutputCount": _safe_int(adoption.get("unsafeOutputCount")),
        "unverifiedOutputCount": _safe_int(adoption.get("unverifiedOutputCount")),
        "preExecutionAdoptionAllowed": bool(adoption.get("preExecutionAdoptionAllowed")),
        "postExecutionAdoptionRequired": bool(adoption.get("postExecutionAdoptionRequired")),
        "cacheAdoptionAllowed": bool(adoption.get("cacheAdoptionAllowed")),
        "lineageMutationAllowed": bool(adoption.get("lineageMutationAllowed")),
        "runStateMutationAllowed": bool(adoption.get("runStateMutationAllowed")),
        "pathExposed": bool(adoption.get("pathExposed")),
        "storageUriExposed": bool(adoption.get("storageUriExposed")),
        "checksumValueExposed": bool(adoption.get("checksumValueExposed")),
        "requires": _string_list(adoption.get("requires")),
    }


def _public_executor_orchestration(
    orchestration: dict[str, Any],
    *,
    route_disabled: bool,
) -> dict[str, Any]:
    source = _dict_value(orchestration.get("sourceAttempt"))
    return {
        "schemaVersion": str(orchestration.get("schemaVersion") or ""),
        "mode": str(orchestration.get("mode") or ""),
        "available": bool(orchestration.get("available")),
        "contractReady": bool(orchestration.get("contractReady")),
        "executorReady": False if route_disabled else orchestration.get("executorReady") is True,
        "reasonCode": "RUN_RESUME_MUTATION_API_DISABLED"
        if route_disabled
        else str(orchestration.get("reasonCode") or ""),
        "blockedReasonCodes": _executor_blocked_reasons(orchestration, route_disabled=route_disabled),
        "requiresBeforeExecution": _executor_requires(orchestration, route_disabled=route_disabled),
        "sourceAttempt": {
            "attemptPresent": bool(source.get("attemptPresent")),
            "attemptNumber": _safe_int(source.get("attemptNumber")),
            "leaseGeneration": _safe_int(source.get("leaseGeneration")),
            "state": str(source.get("state") or ""),
        },
        "targetAttemptRequired": bool(orchestration.get("targetAttemptRequired")),
        "activeLeaseRequired": bool(orchestration.get("activeLeaseRequired")),
        "workdirReuseRequired": bool(orchestration.get("workdirReuseRequired")),
        "workdirReusable": bool(orchestration.get("workdirReusable")),
        "resultDirReuseRequired": bool(orchestration.get("resultDirReuseRequired")),
        "runConfigRewriteAllowed": bool(orchestration.get("runConfigRewriteAllowed")),
        "snakemakeMetadataRequired": bool(orchestration.get("snakemakeMetadataRequired")),
        "executionOptionsSchemaVersion": str(orchestration.get("executionOptionsSchemaVersion") or ""),
        "rerunIncompleteRequired": bool(orchestration.get("rerunIncompleteRequired")),
        "forcerunRulesRequired": bool(orchestration.get("forcerunRulesRequired")),
        "cacheAdoptionBypassRequired": bool(orchestration.get("cacheAdoptionBypassRequired")),
        "artifactAdoptionRequired": bool(orchestration.get("artifactAdoptionRequired")),
        "finalizeRunAllowed": bool(orchestration.get("finalizeRunAllowed")),
        "queueMutationAllowed": False,
        "runStateMutationAllowed": False,
        "pathExposed": bool(orchestration.get("pathExposed")),
        "storageUriExposed": bool(orchestration.get("storageUriExposed")),
    }


def _public_snakemake_options(snakemake: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": str(snakemake.get("schemaVersion") or ""),
        "rerunIncomplete": bool(snakemake.get("rerunIncomplete")),
        "argsPreview": _string_list(snakemake.get("argsPreview")),
        "unsafeFlagsProhibited": _string_list(snakemake.get("unsafeFlagsProhibited")),
    }


def _public_activation_readiness(readiness: dict[str, Any], *, route_disabled: bool) -> dict[str, Any]:
    return {
        "schemaVersion": str(readiness.get("schemaVersion") or ""),
        "runId": str(readiness.get("runId") or ""),
        "workflowRevisionIdPresent": bool(str(readiness.get("workflowRevisionId") or "").strip()),
        "executionReady": False,
        "executionEnabled": False if route_disabled else readiness.get("executionEnabled") is True,
        "reasonCode": "RUN_RESUME_MUTATION_API_DISABLED"
        if route_disabled
        else str(readiness.get("reasonCode") or ""),
        "blockedReasonCodes": _readiness_blocked_reasons(readiness, route_disabled=route_disabled),
        "readyCheckCount": _safe_int(readiness.get("readyCheckCount")),
        "blockedCheckCount": _safe_int(readiness.get("blockedCheckCount")),
        "checks": [_public_readiness_check(item) for item in _list_value(readiness.get("checks"))],
        "summary": _int_mapping(readiness.get("summary")),
        "redactionPolicy": _bool_mapping(
            readiness.get("redactionPolicy"),
            allowed_keys=("rawIdentifiersExposed", "fingerprintsExposed", "storageUrisExposed", "pathsExposed"),
        ),
    }


def _public_readiness_check(value: Any) -> dict[str, Any]:
    check = _dict_value(value)
    return {
        "name": str(check.get("name") or ""),
        "ready": bool(check.get("ready")),
        "reasonCode": str(check.get("reasonCode") or ""),
    }


def _blocked_reasons(plan: dict[str, Any], denial_code: str) -> list[str]:
    return _unique_strings([denial_code, *_string_list(plan.get("blockedReasonCodes"))])


def _executor_blocked_reasons(orchestration: dict[str, Any], *, route_disabled: bool) -> list[str]:
    return _unique_strings(
        [
            "RUN_RESUME_MUTATION_API_DISABLED" if route_disabled else "",
            *_string_list(orchestration.get("blockedReasonCodes")),
        ]
    )


def _executor_requires(orchestration: dict[str, Any], *, route_disabled: bool) -> list[str]:
    return _unique_strings(
        [
            "RUN_RESUME_MUTATION_API_DISABLED" if route_disabled else "",
            *_string_list(orchestration.get("requiresBeforeExecution")),
        ]
    )


def _readiness_blocked_reasons(readiness: dict[str, Any], *, route_disabled: bool) -> list[str]:
    return _unique_strings(
        [
            "RUN_RESUME_MUTATION_API_DISABLED" if route_disabled else "",
            *_string_list(readiness.get("blockedReasonCodes")),
        ]
    )


def _int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _safe_int(raw) for key, raw in value.items() if str(key or "").strip()}


def _bool_mapping(value: Any, *, allowed_keys: tuple[str, ...]) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    return {key: bool(source.get(key)) for key in allowed_keys}


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _list_value(value) if str(item or "").strip()]


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            unique.append(text)
            seen.add(text)
    return unique


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _collection_size(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0
