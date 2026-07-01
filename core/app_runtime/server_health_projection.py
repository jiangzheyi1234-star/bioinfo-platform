from __future__ import annotations

import time
from typing import Any, Optional

from core.app_runtime import runner_stop_state
from core.app_runtime.errors import RuntimeServiceError
from core.remote.ssh_service import SSHService


def build_server_health_projection(
    service: Any,
    *,
    server_id: str,
    ssh_status: dict[str, Any],
    registry_entry: dict[str, Any],
    ssh: Optional[SSHService],
) -> dict[str, Any]:
    connected = bool(ssh_status.get("connected"))
    configured = bool(ssh_status.get("host") or ssh_status.get("ssh_host_alias"))
    startup = {
        "ok": configured,
        "message": "Local backend has server configuration." if configured else "No SSH target configured.",
    }
    live = {
        "ok": connected,
        "message": "SSH tunnel reachable." if connected else "SSH connection is not active.",
    }
    reason_code = ""
    ready_ok = False
    ready_message = "Remote runner is not ready."
    workflow_runtime: dict[str, Any] = {}
    pipeline_registry: dict[str, Any] = {}
    if not configured or not connected:
        reason_code = "SSH_NOT_CONNECTED"
        ready_message = "Connect to the remote server before submitting runs."
    elif runner_stop_state.is_runner_manually_stopped(registry_entry):
        stopped = runner_stop_state.manual_runner_stop_health(
            server_id,
            registry_entry,
            service._get_saved_readiness_snapshot,
        )
        startup, live = stopped["startup"], stopped["live"]
        ready_ok, ready_message, reason_code = stopped["readyOk"], stopped["readyMessage"], stopped["reasonCode"]
        workflow_runtime, pipeline_registry = stopped["workflowRuntime"], stopped["pipelineRegistry"]
    elif runner_stop_state.has_unsupported_runner_stop_snapshot(registry_entry):
        unsupported = runner_stop_state.unsupported_runner_stop_health(
            server_id,
            registry_entry,
            service._get_saved_readiness_snapshot,
        )
        startup = unsupported["startup"]
        live = unsupported["live"]
        ready_ok = bool(unsupported["ready"]["ok"])
        ready_message = str(unsupported["ready"]["message"])
        reason_code = str(unsupported["reasonCode"])
        workflow_runtime = dict(unsupported.get("workflowRuntime") or {})
        pipeline_registry = dict(unsupported.get("pipelineRegistry") or {})
    elif not registry_entry.get("bootstrap_version"):
        snapshot = service._get_saved_readiness_snapshot(
            server_id=server_id,
            registry_entry=registry_entry,
        )
        if snapshot is not None:
            startup, live, ready_ok, ready_message, reason_code, workflow_runtime, pipeline_registry = (
                _snapshot_health_parts(snapshot)
            )
        else:
            reason_code = "RUNNER_NOT_READY"
            ready_message = "Prepare the remote workspace before using this server."
    else:
        try:
            if ssh is None or not getattr(ssh, "is_connected", False):
                raise RuntimeServiceError("SSH disconnected")
            remote_health = service._call_remote_runner(
                service._service_locator.remote_runner_manager.get_health,
                server_id=server_id,
                ssh_service=ssh,
                server_record=registry_entry,
            )
            startup = remote_health["startup"]
            live = remote_health["live"]
            ready_ok = bool(remote_health["ready"]["ok"])
            ready_message = str(remote_health["ready"]["message"])
            reason_code = str(remote_health.get("reasonCode", "") or "")
            workflow_runtime = dict(remote_health.get("workflowRuntime") or {})
            pipeline_registry = dict(remote_health.get("pipelineRegistry") or {})
            with service._lock:
                registry_entry.update(service._save_runner_health_snapshot(server_id=server_id, health=remote_health))
        except RuntimeServiceError as exc:
            with service._lock:
                updated_entry = service._save_runner_connection_metadata_from_detail(
                    server_id=server_id,
                    detail=exc.detail,
                )
            if updated_entry is not None:
                registry_entry = updated_entry
            snapshot = service._get_saved_readiness_snapshot(
                server_id=server_id,
                registry_entry=registry_entry,
            )
            if snapshot is not None:
                startup, live, ready_ok, ready_message, reason_code, workflow_runtime, pipeline_registry = (
                    _snapshot_health_parts(snapshot)
                )
            else:
                reason_code = "RUNNER_NOT_READY"
                ready_message = str(exc) or "Remote runner control plane is not reachable."
    return {
        "serverId": server_id,
        "startup": startup,
        "live": live,
        "ready": {"ok": ready_ok, "message": ready_message},
        "workflowRuntime": workflow_runtime,
        "pipelineRegistry": pipeline_registry,
        "reasonCode": reason_code,
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _snapshot_health_parts(
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool, str, str, dict[str, Any], dict[str, Any]]:
    return (
        snapshot["startup"],
        snapshot["live"],
        bool(snapshot["ready"]["ok"]),
        str(snapshot["ready"]["message"]),
        str(snapshot.get("reasonCode", "") or "RUNNER_NOT_READY"),
        dict(snapshot.get("workflowRuntime") or {}),
        dict(snapshot.get("pipelineRegistry") or {}),
    )
