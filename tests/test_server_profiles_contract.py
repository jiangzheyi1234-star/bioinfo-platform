from __future__ import annotations

from pathlib import Path

from config import default_config
from core.app_runtime.server_payloads import build_primary_server_identity, compose_ssh_status
from core.app_runtime.server_profiles import (
    DEFAULT_SERVER_PROFILE_ID,
    SERVER_PROFILES_CONFIG_KEY,
    build_default_server_profile,
)


ROOT = Path(__file__).resolve().parents[1]


def test_default_config_declares_default_server_profile() -> None:
    config = default_config()

    assert config["active_server_profile_id"] == DEFAULT_SERVER_PROFILE_ID
    assert SERVER_PROFILES_CONFIG_KEY in config
    assert config[SERVER_PROFILES_CONFIG_KEY][DEFAULT_SERVER_PROFILE_ID]["source"] == "legacy-ssh-config"


def test_default_server_profile_binds_ssh_runner_and_host_key_without_secret_values() -> None:
    config = default_config()
    config["ssh"].update(
        {
            "auth_mode": "password_ref",
            "host": "10.10.0.12",
            "port": 2222,
            "user": "ubuntu",
            "password_ref": "ssh://ubuntu@10.10.0.12:2222",
            "remember_auth": True,
            "auto_connect_on_startup": True,
        }
    )
    ssh_status = compose_ssh_status(
        ssh_config=config["ssh"],
        connected=True,
        connect_in_progress=False,
        auto_connect_attempted=True,
        auto_connect_in_progress=False,
        auto_connect_failed=False,
        auto_connect_error="",
    )
    server = build_primary_server_identity(ssh_status=ssh_status)
    assert server is not None
    config["servers"][server["serverId"]] = {
        "bootstrap_version": "0.1.5-control-plane",
        "runner_mode": "systemd_user",
        "service_port": 18990,
        "tunnel_port": 49001,
        "token_ref": f"runner://{server['serverId']}",
        "host_key_trusted": True,
        "host_key_fingerprint_sha256": "SHA256:test-fingerprint",
        "known_hosts_path": "C:/Users/test/AppData/Roaming/H2OMeta/ssh/known_hosts",
        "last_provisioning_job_id": "remote-provisioning-test",
        "last_provisioning_action": "ensure-runner",
        "last_provisioning_job_status": "succeeded",
        "last_provisioning_job_updated_at": "2026-07-08T00:00:00Z",
        "last_diagnostics_bundle_ref": "diagnostics://srv/bundle.json",
        "last_diagnostics_checked_at": "2026-07-08T00:01:00Z",
        "last_health_snapshot": {
            "serverId": server["serverId"],
            "state": "ready",
            "startup": {"ok": True, "message": "started"},
            "live": {"ok": True, "message": "live"},
            "ready": {"ok": True, "message": "ready"},
            "reasonCode": "",
        },
    }

    profile = build_default_server_profile(
        config=config,
        ssh_status=ssh_status,
        server_action_state={},
        local_tunnels=[],
    )

    assert profile["profileId"] == DEFAULT_SERVER_PROFILE_ID
    assert profile["serverId"] == server["serverId"]
    assert profile["displayName"] == "ubuntu@10.10.0.12"
    assert profile["connection"] == {
        "authMode": "password_ref",
        "sshHostAlias": "",
        "host": "10.10.0.12",
        "port": 2222,
        "user": "ubuntu",
        "identityRef": "",
        "rememberAuth": True,
        "autoConnectOnStartup": True,
        "hasPassword": True,
        "timeoutSec": 5,
    }
    assert profile["hostKeyTrust"]["trusted"] is True
    assert profile["hostKeyTrust"]["fingerprintSha256"] == "SHA256:test-fingerprint"
    assert profile["provisioning"] == {
        "lastJobId": "remote-provisioning-test",
        "lastAction": "ensure-runner",
        "lastStatus": "succeeded",
        "lastUpdatedAt": "2026-07-08T00:00:00Z",
    }
    assert profile["diagnostics"] == {
        "lastBundleRef": "diagnostics://srv/bundle.json",
        "lastCheckedAt": "2026-07-08T00:01:00Z",
    }
    assert profile["runner"]["installedVersion"] == "0.1.5-control-plane"
    assert profile["runner"]["hasTokenRef"] is True
    assert profile["runner"]["tokenRef"] == f"runner://{server['serverId']}"
    serialized = repr(profile)
    assert "passwordRef" not in serialized
    assert "ssh://ubuntu@10.10.0.12:2222" not in serialized
    assert "token-secret" not in serialized


def test_server_profile_api_and_plugin_center_surface_contracts() -> None:
    route_source = (ROOT / "apps" / "api" / "ssh_routes.py").read_text(encoding="utf-8")
    control_source = (ROOT / "apps" / "api" / "ssh_control_service.py").read_text(encoding="utf-8")
    page_source = (ROOT / "apps" / "web" / "app" / "components" / "plugin-center-page.tsx").read_text(
        encoding="utf-8"
    )
    api_source = (ROOT / "apps" / "web" / "app" / "components" / "plugin-center-api.ts").read_text(
        encoding="utf-8"
    )

    assert '"/api/v1/server-profiles"' in route_source
    assert '"/api/v1/server-profiles/{profile_id}"' in route_source
    assert "list_server_profiles_from_request" in control_source
    assert "get_server_profile_from_request" in control_source
    assert '"/api/v1/server-profiles"' in api_source
    assert "fetchServerProfiles" in page_source
    assert 'data-testid="plugin-center-server-profile-summary"' in page_source
    assert "hostKeyTrustLabel(activeServerProfile)" in page_source
    assert "runnerTokenLabel(activeServerProfile)" in page_source
