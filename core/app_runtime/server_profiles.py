from __future__ import annotations

from typing import Any

from config import get_ssh_known_hosts_path, normalize_ssh_config
from core.app_runtime import runtime_config
from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.server_payloads import build_primary_server_identity, compose_runner_payload

SERVER_PROFILES_CONFIG_KEY = "server_profiles"
DEFAULT_SERVER_PROFILE_ID = "default"


class ServerProfileOperationsMixin:
    def list_server_profiles(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            config = runtime_config.get_runtime_config()
            ssh_status = self._get_ssh_status_unlocked()
            ssh = self._service_locator.ssh_service if bool(ssh_status.get("connected")) else None
            profile = build_default_server_profile(
                config=config,
                ssh_status=ssh_status,
                server_action_state=getattr(self, "_server_action_state", {}),
                local_tunnels=self._local_tunnel_snapshots(ssh),
            )
        return {
            "data": {
                "items": [profile],
                "total": 1,
                "defaultProfileId": DEFAULT_SERVER_PROFILE_ID,
                "activeProfileId": profile["profileId"],
            }
        }

    def get_server_profile(self, profile_id: str) -> dict[str, Any]:
        normalized_profile_id = str(profile_id or "").strip()
        payload = self.list_server_profiles()["data"]
        for profile in payload["items"]:
            if normalized_profile_id in {profile["profileId"], profile.get("serverId", "")}:
                return {"data": profile}
        raise RuntimeServiceError(
            f"Server profile not found: {normalized_profile_id}",
            status_code=404,
            detail={
                "reasonCode": "SERVER_PROFILE_NOT_FOUND",
                "profileId": normalized_profile_id,
            },
        )


def build_default_server_profile(
    *,
    config: dict[str, Any],
    ssh_status: dict[str, Any],
    server_action_state: dict[str, dict[str, Any]] | None = None,
    local_tunnels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ssh_config = normalize_ssh_config(config.get("ssh", {}))
    server = build_primary_server_identity(ssh_status=ssh_status)
    server_id = str(server["serverId"]) if server else ""
    registry_entry = _server_registry_entry(config, server_id)
    action_state = _server_action_state(server_action_state, server_id)
    profile_config = _default_profile_config(config)
    display_name = _display_name(profile_config=profile_config, server=server, ssh_config=ssh_config)
    configured = server is not None
    health = registry_entry.get("last_health_snapshot") if isinstance(registry_entry.get("last_health_snapshot"), dict) else {}

    return {
        "schemaVersion": "server-profile.v1",
        "profileId": DEFAULT_SERVER_PROFILE_ID,
        "serverId": server_id,
        "displayName": display_name,
        "source": "legacy-ssh-config",
        "isDefault": True,
        "configured": configured,
        "connected": bool(ssh_status.get("connected")),
        "connection": _connection_projection(ssh_config=ssh_config, ssh_status=ssh_status),
        "hostKeyTrust": _host_key_trust_projection(registry_entry=registry_entry, action_state=action_state),
        "runner": _runner_projection(
            registry_entry=registry_entry,
            health=health,
            local_tunnels=local_tunnels,
        ),
    }


def _default_profile_config(config: dict[str, Any]) -> dict[str, Any]:
    profiles = config.get(SERVER_PROFILES_CONFIG_KEY)
    if not isinstance(profiles, dict):
        return {}
    default_profile = profiles.get(DEFAULT_SERVER_PROFILE_ID)
    return dict(default_profile) if isinstance(default_profile, dict) else {}


def _server_registry_entry(config: dict[str, Any], server_id: str) -> dict[str, Any]:
    if not server_id:
        return {}
    registry = config.get("servers")
    if not isinstance(registry, dict):
        return {}
    entry = registry.get(server_id)
    return dict(entry) if isinstance(entry, dict) else {}


def _server_action_state(
    server_action_state: dict[str, dict[str, Any]] | None,
    server_id: str,
) -> dict[str, Any]:
    if not server_id or not isinstance(server_action_state, dict):
        return {}
    state = server_action_state.get(server_id)
    return dict(state) if isinstance(state, dict) else {}


def _display_name(
    *,
    profile_config: dict[str, Any],
    server: dict[str, Any] | None,
    ssh_config: dict[str, Any],
) -> str:
    configured_name = str(profile_config.get("display_name") or profile_config.get("displayName") or "").strip()
    if configured_name:
        return configured_name
    if server is not None:
        label = str(server.get("label") or "").strip()
        user = str(server.get("user") or "").strip()
        if label and user:
            return f"{user}@{label}"
        return label or "Default server"
    alias = str(ssh_config.get("ssh_host_alias") or "").strip()
    host = str(ssh_config.get("host") or "").strip()
    user = str(ssh_config.get("user") or "").strip()
    if alias and user:
        return f"{user}@{alias}"
    if host and user:
        return f"{user}@{host}"
    return "Default server"


def _connection_projection(
    *,
    ssh_config: dict[str, Any],
    ssh_status: dict[str, Any],
) -> dict[str, Any]:
    return {
        "authMode": str(ssh_config.get("auth_mode") or "password_ref"),
        "sshHostAlias": str(ssh_config.get("ssh_host_alias") or ""),
        "host": str(ssh_status.get("host") or ssh_config.get("host") or ""),
        "port": int(ssh_status.get("port") or ssh_config.get("port") or 22),
        "user": str(ssh_status.get("user") or ssh_config.get("user") or ""),
        "identityRef": str(ssh_config.get("identity_ref") or ""),
        "rememberAuth": bool(ssh_config.get("remember_auth", True)),
        "autoConnectOnStartup": bool(ssh_config.get("auto_connect_on_startup", False)),
        "hasPassword": bool(ssh_config.get("password_ref")),
        "timeoutSec": int(ssh_config.get("timeout_sec") or 5),
    }


def _host_key_trust_projection(
    *,
    registry_entry: dict[str, Any],
    action_state: dict[str, Any],
) -> dict[str, Any]:
    fingerprint = str(
        registry_entry.get("host_key_fingerprint_sha256")
        or action_state.get("host_key_fingerprint_sha256")
        or ""
    )
    known_hosts_path = str(
        registry_entry.get("known_hosts_path")
        or action_state.get("known_hosts_path")
        or get_ssh_known_hosts_path()
    )
    return {
        "trusted": bool(registry_entry.get("host_key_trusted") or action_state.get("host_key_trusted")),
        "fingerprintSha256": fingerprint,
        "knownHostsPath": known_hosts_path,
    }


def _runner_projection(
    *,
    registry_entry: dict[str, Any],
    health: dict[str, Any],
    local_tunnels: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    runner = compose_runner_payload(
        registry_entry=registry_entry,
        health=health,
        local_tunnels=local_tunnels,
    )
    token_ref = str(registry_entry.get("token_ref") or "")
    return {
        "state": runner["state"],
        "ready": bool(runner["ready"]),
        "message": str(runner["message"] or ""),
        "reasonCode": str(runner["reasonCode"] or ""),
        "installedVersion": str(registry_entry.get("bootstrap_version") or ""),
        "runnerMode": str(registry_entry.get("runner_mode") or ""),
        "deploymentAction": str(runner.get("deploymentAction") or ""),
        "servicePort": registry_entry.get("service_port"),
        "tunnelPort": registry_entry.get("tunnel_port"),
        "localTunnels": runner.get("localTunnels") or [],
        "tokenRef": token_ref,
        "hasTokenRef": bool(token_ref),
        "health": health if health else None,
    }
