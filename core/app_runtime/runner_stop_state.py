from __future__ import annotations

from typing import Any, Callable

from core.app_runtime.errors import RuntimeServiceError


MANUAL_RUNNER_STOP_REASON = "RUNNER_STOPPED"
MANUAL_RUNNER_STOP_MESSAGE = (
    "Remote runner was manually stopped. Use the explicit start action before submitting runs."
)


def is_runner_manually_stopped(record: dict[str, Any]) -> bool:
    snapshot = record.get("last_health_snapshot")
    reason_code = str(snapshot.get("reasonCode") or "") if isinstance(snapshot, dict) else ""
    return reason_code == MANUAL_RUNNER_STOP_REASON


def raise_if_runner_manually_stopped(*, server_id: str, record: dict[str, Any]) -> None:
    if not is_runner_manually_stopped(record):
        return
    raise RuntimeServiceError(
        MANUAL_RUNNER_STOP_MESSAGE,
        status_code=409,
        detail={
            "reasonCode": MANUAL_RUNNER_STOP_REASON,
            "serverId": server_id,
            "nextAction": "START_RUNNER",
        },
    )


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
