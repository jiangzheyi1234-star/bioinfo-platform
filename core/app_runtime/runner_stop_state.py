from __future__ import annotations

from typing import Any, Callable

from core.app_runtime.errors import RuntimeServiceError


MANUAL_RUNNER_STOP_REASON = "RUNNER_STOPPED"
RUNNER_STOP_INTENT_REQUIRED_REASON = "RUNNER_STOP_INTENT_REQUIRED"
MANUAL_RUNNER_STOP_INTENT_KEY = "runner_stop_intent"
MANUAL_RUNNER_STOP_INTENT_SCHEMA = "h2ometa.runner-stop-intent.v1"
MANUAL_RUNNER_STOP_MESSAGE = (
    "Remote runner was manually stopped. Use the explicit start action before submitting runs."
)
RUNNER_STOP_INTENT_REQUIRED_MESSAGE = (
    "Runner stop state is missing explicit runner_stop_intent. Use the explicit start action to repair it."
)


def build_manual_runner_stop_intent(*, server_id: str, stopped_at: str) -> dict[str, Any]:
    return {
        "schemaVersion": MANUAL_RUNNER_STOP_INTENT_SCHEMA,
        "active": True,
        "reasonCode": MANUAL_RUNNER_STOP_REASON,
        "serverId": server_id,
        "stoppedAt": stopped_at,
        "source": "explicit-stop",
    }


def build_runner_stop_cleared_intent(*, action: str, cleared_at: str) -> dict[str, Any]:
    return {
        "schemaVersion": MANUAL_RUNNER_STOP_INTENT_SCHEMA,
        "active": False,
        "reasonCode": "",
        "clearedAt": cleared_at,
        "clearedByAction": action,
    }


def is_runner_manually_stopped(record: dict[str, Any]) -> bool:
    intent = record.get(MANUAL_RUNNER_STOP_INTENT_KEY)
    if not isinstance(intent, dict):
        return False
    return bool(intent.get("active")) and str(intent.get("reasonCode") or "") == MANUAL_RUNNER_STOP_REASON


def has_unsupported_runner_stop_snapshot(record: dict[str, Any]) -> bool:
    if is_runner_manually_stopped(record):
        return False
    snapshot = record.get("last_health_snapshot")
    reason_code = str(snapshot.get("reasonCode") or "") if isinstance(snapshot, dict) else ""
    return reason_code == MANUAL_RUNNER_STOP_REASON


def requires_explicit_runner_start(record: dict[str, Any]) -> bool:
    return is_runner_manually_stopped(record) or has_unsupported_runner_stop_snapshot(record)


def raise_if_runner_manually_stopped(*, server_id: str, record: dict[str, Any]) -> None:
    if is_runner_manually_stopped(record):
        raise RuntimeServiceError(
            MANUAL_RUNNER_STOP_MESSAGE,
            status_code=409,
            detail={
                "reasonCode": MANUAL_RUNNER_STOP_REASON,
                "serverId": server_id,
                "nextAction": "START_RUNNER",
            },
        )
    if has_unsupported_runner_stop_snapshot(record):
        raise RuntimeServiceError(
            RUNNER_STOP_INTENT_REQUIRED_MESSAGE,
            status_code=409,
            detail={
                "reasonCode": RUNNER_STOP_INTENT_REQUIRED_REASON,
                "serverId": server_id,
                "nextAction": "START_RUNNER",
            },
        )


def unsupported_runner_stop_health(
    server_id: str,
    registry_entry: dict[str, Any],
    get_saved_snapshot: Callable[..., dict[str, Any] | None],
) -> dict[str, Any]:
    snapshot = get_saved_snapshot(server_id=server_id, registry_entry=registry_entry)
    startup = {"ok": True, "message": "Runner stop state requires explicit lifecycle repair."}
    live = {"ok": False, "message": "Remote runner stop intent is missing."}
    workflow_runtime: dict[str, Any] = {}
    pipeline_registry: dict[str, Any] = {}
    if snapshot is not None:
        startup = snapshot["startup"]
        live = snapshot["live"]
        workflow_runtime = dict(snapshot.get("workflowRuntime") or {})
        pipeline_registry = dict(snapshot.get("pipelineRegistry") or {})
    return {
        "serverId": server_id,
        "state": "repair_needed",
        "startup": startup,
        "live": live,
        "ready": {"ok": False, "message": RUNNER_STOP_INTENT_REQUIRED_MESSAGE},
        "workflowRuntime": workflow_runtime,
        "pipelineRegistry": pipeline_registry,
        "reasonCode": RUNNER_STOP_INTENT_REQUIRED_REASON,
    }



def manual_runner_stop_health(
    server_id: str,
    registry_entry: dict[str, Any],
    get_saved_snapshot: Callable[..., dict[str, Any] | None],
) -> dict[str, Any]:
    snapshot = get_saved_snapshot(server_id=server_id, registry_entry=registry_entry)
    if snapshot is None:
        return {
            "startup": {"ok": True, "message": "Remote runner stop state is recorded."},
            "live": {"ok": False, "message": "Remote runner is manually stopped."},
            "readyOk": False,
            "readyMessage": MANUAL_RUNNER_STOP_MESSAGE,
            "reasonCode": MANUAL_RUNNER_STOP_REASON,
            "workflowRuntime": {},
            "pipelineRegistry": {},
        }
    return {
        "startup": snapshot["startup"],
        "live": snapshot["live"],
        "readyOk": bool(snapshot["ready"]["ok"]),
        "readyMessage": str(snapshot["ready"]["message"]),
        "reasonCode": MANUAL_RUNNER_STOP_REASON,
        "workflowRuntime": dict(snapshot.get("workflowRuntime") or {}),
        "pipelineRegistry": dict(snapshot.get("pipelineRegistry") or {}),
    }
