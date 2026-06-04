from __future__ import annotations

import uuid
from typing import Any


def build_primary_server_identity(*, ssh_status: dict[str, Any]) -> dict[str, Any] | None:
    host = str(ssh_status.get("host", "") or "").strip()
    alias = str(ssh_status.get("ssh_host_alias", "") or "").strip()
    user = str(ssh_status.get("user", "") or "").strip()
    port = int(ssh_status.get("port", 22) or 22)
    if not host and not alias:
        return None
    stable_key = f"{host or alias}:{port}:{user or 'unknown'}"
    server_id = f"srv_{uuid.uuid5(uuid.NAMESPACE_DNS, stable_key).hex[:12]}"
    return {
        "serverId": server_id,
        "label": alias or host,
        "host": host,
        "port": port,
        "user": user,
        "connected": bool(ssh_status.get("connected")),
    }


def get_saved_readiness_snapshot(
    *,
    server_id: str,
    registry_entry: dict[str, Any],
) -> dict[str, Any] | None:
    snapshot = registry_entry.get("last_health_snapshot")
    if not isinstance(snapshot, dict):
        return None
    reason_code = str(snapshot.get("reasonCode") or "").strip()
    ready = snapshot.get("ready")
    startup = snapshot.get("startup")
    live = snapshot.get("live")
    if not reason_code or not isinstance(ready, dict) or not isinstance(startup, dict) or not isinstance(live, dict):
        return None
    return {
        "serverId": str(snapshot.get("serverId") or server_id),
        "startup": startup,
        "live": live,
        "ready": ready,
        "workflowRuntime": snapshot.get("workflowRuntime") if isinstance(snapshot.get("workflowRuntime"), dict) else {},
        "pipelineRegistry": snapshot.get("pipelineRegistry") if isinstance(snapshot.get("pipelineRegistry"), dict) else {},
        "reasonCode": reason_code,
        "checkedAt": str(snapshot.get("checkedAt") or ""),
    }


def compose_server_payload(
    *,
    server: dict[str, Any],
    registry_entry: dict[str, Any],
    health: dict[str, Any],
) -> dict[str, Any]:
    return {
        **server,
        "ready": bool(health["ready"]["ok"]),
        "reasonCode": health.get("reasonCode", ""),
        "message": health["ready"]["message"],
        "health": health,
        "runner": compose_runner_payload(registry_entry=registry_entry, health=health),
        "runnerVersion": registry_entry.get("bootstrap_version", ""),
        "runnerMode": registry_entry.get("runner_mode", ""),
    }


def compose_runner_payload(
    *,
    registry_entry: dict[str, Any],
    health: dict[str, Any],
) -> dict[str, Any]:
    ready = bool((health.get("ready") or {}).get("ok"))
    metadata = registry_entry.get("bootstrap_metadata") if isinstance(registry_entry.get("bootstrap_metadata"), dict) else {}
    deployment_action = str((metadata or {}).get("deployment_action") or "")
    reason_code = str(health.get("reasonCode") or "")
    if ready:
        state = "ready"
    elif str(health.get("state") or "") in {"preparing", "recovering"}:
        state = str(health.get("state") or "")
    elif reason_code:
        state = "repair_needed"
    else:
        state = "preparing"
    return {
        "state": state,
        "ready": ready,
        "message": str((health.get("ready") or {}).get("message") or ""),
        "reasonCode": reason_code,
        "version": registry_entry.get("bootstrap_version", ""),
        "runnerMode": registry_entry.get("runner_mode", ""),
        "deploymentAction": deployment_action,
        "servicePort": registry_entry.get("service_port"),
        "tunnelPort": registry_entry.get("tunnel_port"),
        "bootstrapMetadata": metadata,
    }
