from __future__ import annotations

import hashlib
from typing import Any

from .api_models import WorkflowTriggerReadinessWatcherRunOnceRequest
from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event
from .trigger_readiness_watcher import run_workflow_trigger_readiness_watcher_once


WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE_CONFIRMATION = "run-readiness-watcher-once"
WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE_RESULT_SCHEMA = (
    "h2ometa.workflow-trigger-readiness-watcher-run-once-result.v1"
)


def run_governed_workflow_trigger_readiness_watcher_once(
    cfg: RemoteRunnerConfig,
    request: WorkflowTriggerReadinessWatcherRunOnceRequest,
) -> dict[str, Any]:
    if request.confirmation != WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE_CONFIRMATION:
        raise ValueError("WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE_CONFIRMATION_REQUIRED")
    result = run_workflow_trigger_readiness_watcher_once(cfg, limit=int(request.limit))
    public = _public_run_once_result(result, limit=int(request.limit))
    actor = str(request.actor or cfg.api_token_actor or "remote-runner-api")
    record_governance_audit_event(
        cfg,
        action="workflow_trigger.readiness_watcher.run_once",
        actor=actor,
        subject_kind="workflow_trigger_readiness_watcher",
        subject_id=str(public["runOnceId"]),
        details={
            "schemaVersion": WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE_RESULT_SCHEMA,
            "runOnceId": public["runOnceId"],
            "evaluatedAt": public["evaluatedAt"],
            "limit": public["limit"],
            "readiness": public["readiness"],
            "controlsExposed": False,
        },
    )
    return {"data": public}


def _public_run_once_result(result: dict[str, Any], *, limit: int) -> dict[str, Any]:
    observations = [item for item in result.get("observations") or [] if isinstance(item, dict)]
    errors = [item for item in result.get("errors") or [] if isinstance(item, dict)]
    evaluated_at = _text(result.get("evaluatedAt"))
    return {
        "schemaVersion": WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE_RESULT_SCHEMA,
        "runOnceId": _run_once_id(result, evaluated_at=evaluated_at),
        "evaluatedAt": evaluated_at,
        "limit": _bounded_limit(limit),
        "controlsExposed": False,
        "readiness": {
            "checked": _safe_int(result.get("checked")),
            "skipped": _safe_int(result.get("skipped")),
            "missing": _safe_int(result.get("missing")),
            "ready": _safe_int(result.get("ready")),
            "submitted": _safe_int(result.get("submitted")),
            "unchanged": _safe_int(result.get("unchanged")),
            "observationCount": len(observations),
            "errorCount": len(errors),
            "stateCounts": _value_counts(observation.get("observedState") for observation in observations),
            "sourceTypeCounts": _value_counts(observation.get("sourceType") for observation in observations),
            "resourceTypeCounts": _value_counts(observation.get("resourceType") for observation in observations),
            "watcherAdapterCounts": _value_counts(observation.get("watcherAdapter") for observation in observations),
            "dispatchStateCounts": _value_counts(observation.get("dispatchState") for observation in observations),
            "errorTypes": _value_counts(error.get("errorType") for error in errors),
            "reasonCodes": _value_counts(_reason_code(str(error.get("message") or "")) for error in errors),
        },
    }


def _run_once_id(result: dict[str, Any], *, evaluated_at: str) -> str:
    seed = {
        "evaluatedAt": evaluated_at,
        "checked": _safe_int(result.get("checked")),
        "submitted": _safe_int(result.get("submitted")),
        "unchanged": _safe_int(result.get("unchanged")),
    }
    digest = hashlib.sha256(repr(sorted(seed.items())).encode("utf-8")).hexdigest()[:16]
    return f"wfrw_{digest}"


def _reason_code(message: str) -> str:
    return message.split(":", 1)[0].strip() if message.strip() else ""


def _value_counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return dict(sorted(counts.items()))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bounded_limit(value: int) -> int:
    return min(100, max(1, int(value)))
