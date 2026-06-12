from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.service import RuntimeService, ServiceLocator
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.manager import RemoteRunnerManager


def test_get_health_resyncs_when_stale_service_port_tunnel_fails(monkeypatch) -> None:
    manager = RemoteRunnerManager()

    class FakeSSH:
        def __init__(self) -> None:
            self.tunnels: list[int] = []

        def run(self, cmd: str, timeout: int = 10):
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/tester", ""
            if "cat /home/tester/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return (
                    0,
                    json.dumps(
                        {
                            "service": "h2ometa-remote",
                            "version": REMOTE_RUNNER_VERSION,
                            "bindHost": "127.0.0.1",
                            "bindPort": 36551,
                            "pid": 4242,
                        }
                    ),
                    "",
                )
            if "kill -0 4242" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def ensure_local_tunnel(self, _name: str, *, remote_host: str, remote_port: int):
            assert remote_host == "127.0.0.1"
            self.tunnels.append(remote_port)
            if remote_port == 43127:
                raise RuntimeError("ChannelException(2, 'Connect failed')")
            return SimpleNamespace(local_port=19001)

    class FakeHttpClient:
        def __init__(self, *, base_url: str, token: str, timeout: int) -> None:
            assert base_url == "http://127.0.0.1:19001"
            assert token == "phase2-token"
            assert timeout == 5

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-06-09T14:00:00Z",
            }

    ssh = FakeSSH()
    monkeypatch.setattr("core.remote_runner.proxy.resolve_runner_token", lambda _ref: "phase2-token")
    monkeypatch.setattr("core.remote_runner.proxy.RemoteRunnerHttpClient", FakeHttpClient)

    health = manager.get_health(
        server_id="srv_demo",
        ssh_service=ssh,
        server_record={
            "bootstrap_version": REMOTE_RUNNER_VERSION,
            "runner_mode": "systemd_user",
            "token_ref": "runner://srv_demo",
            "service_port": 43127,
        },
    )

    assert ssh.tunnels == [43127, 36551]
    assert health["ready"]["ok"] is True
    assert health["servicePort"] == 36551
    assert health["tunnelPort"] == 19001
    assert health["runtimeState"]["bindPort"] == 36551
    assert health["connectionResynced"] is True


def test_ssh_status_refresh_persists_resynced_service_port_after_auth_failure() -> None:
    server_id = f"srv_{uuid.uuid5(uuid.NAMESPACE_DNS, '192.0.2.10:22:tester').hex[:12]}"
    cfg = {
        "ssh": {
            "auth_mode": "password_ref",
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "password_ref": "ssh://tester@192.0.2.10:22",
            "identity_ref": "",
            "timeout_sec": 5,
            "auto_connect_on_startup": True,
        },
        "servers": {
            server_id: {
                "bootstrap_version": "phase1-test",
                "runner_mode": "systemd_user",
                "tunnel_port": 18000,
                "service_port": 43127,
                "token_ref": "runner://srv_test",
                "last_health_snapshot": {
                    "startup": {"ok": False, "message": "Old startup failure."},
                    "live": {"ok": False, "message": "Old live failure."},
                    "ready": {"ok": False, "message": "Old ready failure."},
                    "reasonCode": "RUNNER_NOT_READY",
                    "checkedAt": "2026-06-09T13:00:00Z",
                },
            }
        },
    }
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    service._service_locator.remote_runner_manager = SimpleNamespace(
        get_health=lambda **kwargs: (_ for _ in ()).throw(
            RuntimeServiceError(
                "runner http error 401: runner authentication failed",
                status_code=401,
                detail={
                    "message": "runner http error 401: runner authentication failed",
                    "servicePort": 36551,
                    "tunnelPort": 19001,
                    "runtimeState": {
                        "bindPort": 36551,
                        "pid": 4242,
                        "version": "phase1-test",
                    },
                    "connectionResynced": True,
                },
            )
        )
    )
    service._ensure_runner_ready_in_background = lambda _server_id: None

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        cfg.clear()
        cfg.update(snapshot)

    with patch("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg), patch(
        "core.app_runtime.runtime_config.save_runtime_config", save_capture
    ):
        status = service.get_ssh_status()

    assert status["runner"]["state"] == "recovering"
    assert status["runner"]["servicePort"] == 36551
    assert status["runner"]["tunnelPort"] == 19001
    record = cfg["servers"][server_id]
    assert record["service_port"] == 36551
    assert record["tunnel_port"] == 19001
    assert record["last_health_snapshot"]["state"] == "recovering"


def test_get_server_health_path_returns_persisted_resynced_service_port() -> None:
    server_id = f"srv_{uuid.uuid5(uuid.NAMESPACE_DNS, '192.0.2.10:22:tester').hex[:12]}"
    cfg = {
        "ssh": {
            "auth_mode": "password_ref",
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "password_ref": "ssh://tester@192.0.2.10:22",
            "identity_ref": "",
            "timeout_sec": 5,
            "auto_connect_on_startup": True,
        },
        "servers": {
            server_id: {
                "bootstrap_version": "phase1-test",
                "runner_mode": "systemd_user",
                "tunnel_port": 18000,
                "service_port": 43127,
                "token_ref": "runner://srv_test",
                "last_health_snapshot": {
                    "startup": {"ok": True, "message": "Remote runner config loaded."},
                    "live": {"ok": True, "message": "Remote runner process is alive."},
                    "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                    "reasonCode": "",
                    "checkedAt": "2026-06-09T13:00:00Z",
                },
            }
        },
    }
    health = {
        "startup": {"ok": True, "message": "Remote runner config loaded."},
        "live": {"ok": True, "message": "Remote runner process is alive."},
        "ready": {"ok": True, "message": "Remote runner control plane is ready."},
        "reasonCode": "",
        "checkedAt": "2026-06-09T14:00:00Z",
        "servicePort": 36551,
        "tunnelPort": 19001,
        "runtimeState": {
            "bindPort": 36551,
            "pid": 4242,
            "version": "phase1-test",
        },
        "connectionResynced": True,
    }
    service = RuntimeService(
        service_locator=ServiceLocator(
            ssh_service=SimpleNamespace(is_connected=True, close=lambda: None),
            remote_runner_manager=SimpleNamespace(get_health=lambda **_kwargs: health),
        )
    )
    service._initialized = True

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        cfg.clear()
        cfg.update(snapshot)

    with patch("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg), patch(
        "core.app_runtime.runtime_config.save_runtime_config", save_capture
    ):
        server = service.get_server(server_id)

    assert server["health"]["servicePort"] == 36551
    assert server["runner"]["servicePort"] == 36551
    assert server["runner"]["tunnelPort"] == 19001
    record = cfg["servers"][server_id]
    assert record["service_port"] == 36551
    assert record["tunnel_port"] == 19001
