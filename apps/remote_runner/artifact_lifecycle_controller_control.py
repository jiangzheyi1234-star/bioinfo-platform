from __future__ import annotations

from typing import Any

from .api_models import ArtifactLifecycleControllerRunOnceRequest
from .artifact_lifecycle_controller import (
    ARTIFACT_LIFECYCLE_CONTROLLER_MODE,
    run_artifact_lifecycle_controller_once,
)
from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event


ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE_CONFIRMATION = (
    "run-artifact-lifecycle-controller-once"
)
ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE_RESULT_SCHEMA = (
    "h2ometa.artifact-lifecycle-controller-run-once-result.v1"
)


def run_governed_artifact_lifecycle_controller_once(
    cfg: RemoteRunnerConfig,
    request: ArtifactLifecycleControllerRunOnceRequest,
) -> dict[str, Any]:
    if request.confirmation != ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE_CONFIRMATION:
        raise ValueError("ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE_CONFIRMATION_REQUIRED")
    tick = run_artifact_lifecycle_controller_once(cfg, payload=_policy_payload(request))
    public = _public_run_once_result(tick)
    actor = str(request.actor or cfg.api_token_actor or "remote-runner-api")
    record_governance_audit_event(
        cfg,
        action="artifact.lifecycle.controller.run_once",
        actor=actor,
        subject_kind="artifact_lifecycle_controller",
        subject_id=public["tickId"],
        details={
            "schemaVersion": ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE_RESULT_SCHEMA,
            "tickId": public["tickId"],
            "evidenceId": public["evidenceId"],
            "evaluatedAt": public["evaluatedAt"],
            "executionMode": public["executionMode"],
            "deleteConfirmationRequired": True,
            "deleteExecutionAuthorized": False,
            "controlsExposed": False,
            "candidateCount": _safe_int(public.get("gcPreview", {}).get("candidateCount")),
            "deleteBytes": _safe_int(public.get("gcPreview", {}).get("deleteBytes")),
            "protectedCount": _safe_int(public.get("gcPreview", {}).get("protectedCount")),
            "quotaOverageBytes": _safe_int(public.get("usage", {}).get("quotaOverageBytes")),
            "policyDecision": _text(public.get("policyDecision", {}).get("decision")),
            "policyReasonCode": _text(public.get("policyDecision", {}).get("reasonCode")),
            "batchLimitApplied": bool(public.get("batchSafety", {}).get("maxDeleteBytesApplied")),
        },
    )
    return {"data": public}


def _policy_payload(request: ArtifactLifecycleControllerRunOnceRequest) -> dict[str, Any]:
    body = request.model_dump(mode="json", exclude_none=True, exclude_unset=True)
    body.pop("confirmation", None)
    payload: dict[str, Any] = {}
    if "retentionDays" in body:
        payload["retentionDays"] = int(body["retentionDays"])
    if "eligibleRunStatuses" in body:
        payload["eligibleRunStatuses"] = list(body["eligibleRunStatuses"])
    if "actor" in body:
        payload["actor"] = str(body["actor"] or "remote-runner-api")
    if "reason" in body:
        payload["reason"] = str(body["reason"] or "operator-artifact-lifecycle-controller-run-once")
    if "quotaBytes" in body:
        payload["quotaBytes"] = int(body["quotaBytes"])
    if "maxDeleteBytesPerTick" in body:
        payload["maxDeleteBytesPerTick"] = int(body["maxDeleteBytesPerTick"])
    return payload


def _public_run_once_result(tick: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE_RESULT_SCHEMA,
        "tickId": _text(tick.get("tickId")),
        "evidenceId": _text(tick.get("evidenceId")),
        "evaluatedAt": _text(tick.get("evaluatedAt")),
        "executionMode": ARTIFACT_LIFECYCLE_CONTROLLER_MODE,
        "deleteConfirmationRequired": True,
        "deleteExecutionAuthorized": False,
        "controlsExposed": False,
        "policy": _copy_keys(
            _dict(tick.get("policy")),
            (
                "policyId",
                "policyVersion",
                "policyFingerprint",
                "persisted",
                "retentionDays",
                "eligibleRunStatuses",
                "quotaBytes",
                "maxDeleteBytesPerTick",
            ),
        ),
        "usage": _copy_keys(
            _dict(tick.get("usage")),
            ("activeBytes", "activeStorageObjectCount", "quotaOverageBytes"),
        ),
        "policyDecision": _copy_keys(
            _dict(tick.get("policyDecision")),
            (
                "decision",
                "reasonCode",
                "message",
                "deletionAuthorized",
                "deleteConfirmationRequired",
                "candidateCount",
                "deleteBytes",
            ),
        ),
        "retentionHolds": _public_retention_holds(_dict(tick.get("retentionHolds"))),
        "batchSafety": _copy_keys(
            _dict(tick.get("batchSafety")),
            (
                "schemaVersion",
                "maxDeleteBytes",
                "maxDeleteBytesApplied",
                "candidateCount",
                "candidateBytes",
                "candidateArtifactCount",
                "candidateRunCount",
                "limitedGroupCount",
                "limitedBytes",
            ),
        ),
        "gcPreview": _public_gc_preview(_dict(tick.get("gcPreview"))),
    }


def _public_retention_holds(value: dict[str, Any]) -> dict[str, Any]:
    projected = _copy_keys(
        value,
        ("schemaVersion", "protectedGroupCount", "protectedBytes", "reasonCount"),
    )
    reasons = value.get("reasons")
    projected["reasons"] = [
        _copy_keys(_dict(item), ("reason", "groupCount", "artifactCount", "runCount", "bytes"))
        for item in reasons
        if isinstance(item, dict)
    ] if isinstance(reasons, list) else []
    return projected


def _public_gc_preview(value: dict[str, Any]) -> dict[str, Any]:
    plan_id = _required_text(value.get("planId"), "ARTIFACT_LIFECYCLE_CONTROLLER_TICK_PLAN_ID_REQUIRED")
    plan_fingerprint = _required_text(
        value.get("planFingerprint"),
        "ARTIFACT_LIFECYCLE_CONTROLLER_TICK_PLAN_FINGERPRINT_REQUIRED",
    )
    projected = _copy_keys(
        value,
        (
            "candidateCount",
            "deleteBytes",
            "protectedCount",
            "protectedBytes",
            "candidateArtifactCount",
            "candidateRunCount",
        ),
    )
    return {"planId": plan_id, "planFingerprint": plan_fingerprint, **projected}


def _copy_keys(value: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: value[key] for key in keys if key in value}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _required_text(value: Any, error_code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error_code)
    return value.strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
