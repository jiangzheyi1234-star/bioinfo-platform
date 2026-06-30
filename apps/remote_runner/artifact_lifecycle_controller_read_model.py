from __future__ import annotations

import json
from typing import Any

from .artifact_lifecycle_controller import (
    ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE,
    ARTIFACT_LIFECYCLE_CONTROLLER_MODE,
    ARTIFACT_LIFECYCLE_CONTROLLER_SCHEMA,
)
from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .storage_core import get_connection


ARTIFACT_LIFECYCLE_CONTROLLER_TICK_READ_MODEL_SCHEMA = (
    "h2ometa.artifact-lifecycle-controller-tick-read-model.v1"
)
DEFAULT_ARTIFACT_LIFECYCLE_CONTROLLER_TICK_LIMIT = 20
MAX_ARTIFACT_LIFECYCLE_CONTROLLER_TICK_LIMIT = 100


def list_governed_artifact_lifecycle_controller_ticks(
    cfg: RemoteRunnerConfig,
    *,
    limit: int = DEFAULT_ARTIFACT_LIFECYCLE_CONTROLLER_TICK_LIMIT,
) -> dict[str, Any]:
    ticks = list_artifact_lifecycle_controller_ticks(cfg, limit=limit)
    record_governance_audit_event(
        cfg,
        action="artifact.lifecycle.controller_ticks.read",
        subject_kind="artifact_lifecycle_controller",
        subject_id="query",
        actor=cfg.api_token_actor or "remote-runner-api",
        details={
            "limit": _bounded_limit(limit),
            "returnedCount": len(ticks["items"]),
            "executionMode": ARTIFACT_LIFECYCLE_CONTROLLER_MODE,
            "deleteConfirmationRequired": True,
        },
    )
    return ticks


def list_artifact_lifecycle_controller_ticks(
    cfg: RemoteRunnerConfig,
    *,
    limit: int = DEFAULT_ARTIFACT_LIFECYCLE_CONTROLLER_TICK_LIMIT,
) -> dict[str, Any]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT event_id, seq, subject_id, payload_json, occurred_at
            FROM evidence_events
            WHERE subject_kind = ?
              AND event_type = ?
            ORDER BY seq DESC
            LIMIT ?
            """,
            (
                "artifact_lifecycle_controller",
                ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE,
                _bounded_limit(limit),
            ),
        ).fetchall()
    return {
        "schemaVersion": ARTIFACT_LIFECYCLE_CONTROLLER_TICK_READ_MODEL_SCHEMA,
        "items": [_project_tick(row) for row in rows],
    }


def _project_tick(row: Any) -> dict[str, Any]:
    payload = json.loads(row["payload_json"] or "{}")
    if not isinstance(payload, dict):
        raise ValueError("ARTIFACT_LIFECYCLE_CONTROLLER_TICK_PAYLOAD_INVALID")
    if payload.get("schemaVersion") != ARTIFACT_LIFECYCLE_CONTROLLER_SCHEMA:
        raise ValueError("ARTIFACT_LIFECYCLE_CONTROLLER_TICK_SCHEMA_UNSUPPORTED")
    if payload.get("executionMode") != ARTIFACT_LIFECYCLE_CONTROLLER_MODE:
        raise ValueError("ARTIFACT_LIFECYCLE_CONTROLLER_TICK_MODE_UNSAFE")
    if payload.get("deleteConfirmationRequired") is not True:
        raise ValueError("ARTIFACT_LIFECYCLE_CONTROLLER_TICK_CONFIRMATION_UNSAFE")
    return {
        "tickId": _text(payload.get("tickId") or row["subject_id"]),
        "evidenceId": _text(row["event_id"]),
        "evidenceSeq": int(row["seq"] or 0),
        "occurredAt": _text(row["occurred_at"]),
        "evaluatedAt": _text(payload.get("evaluatedAt")),
        "executionMode": ARTIFACT_LIFECYCLE_CONTROLLER_MODE,
        "deleteConfirmationRequired": True,
        "policy": _copy_keys(
            _dict(payload.get("policy")),
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
            _dict(payload.get("usage")),
            ("activeBytes", "activeStorageObjectCount", "quotaOverageBytes"),
        ),
        "policyDecision": _copy_keys(
            _dict(payload.get("policyDecision")),
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
        "retentionHolds": _project_retention_holds(_dict(payload.get("retentionHolds"))),
        "batchSafety": _copy_keys(
            _dict(payload.get("batchSafety")),
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
        "gcPreview": _project_gc_preview(_dict(payload.get("gcPreview"))),
    }


def _project_retention_holds(value: dict[str, Any]) -> dict[str, Any]:
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


def _project_gc_preview(value: dict[str, Any]) -> dict[str, Any]:
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


def _bounded_limit(value: int) -> int:
    return min(MAX_ARTIFACT_LIFECYCLE_CONTROLLER_TICK_LIMIT, max(1, int(value)))
