from types import SimpleNamespace
import uuid
from unittest.mock import patch

from config import get_ssh_key_dir, make_ssh_password_ref, resolve_ssh_password
from core.app_runtime.service import RuntimeService, ServiceLocator
from core.remote.ssh_service import SSHService


class DummyTransport:
    def is_active(self) -> bool:
        return True


class DummyClient:
    def get_transport(self) -> DummyTransport:
        return DummyTransport()

    def close(self) -> None:
        return None


class ReadyRemoteRunnerManager:
    def bootstrap(self, **kwargs):
        return {
            "bootstrap_version": "phase1-test",
            "runner_mode": "background_process",
            "tunnel_port": 18765,
            "service_port": 43127,
            "token_ref": "runner://srv_test",
            "health": {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-21T12:00:00Z",
            },
        }


class RecoveringRemoteRunnerManager:
    def __init__(self) -> None:
        self.health_calls = 0
        self.bootstrap_calls = 0

    def get_health(self, **kwargs):
        self.health_calls += 1
        raise RuntimeError("remote runner process is not reachable")

    def bootstrap(self, **kwargs):
        self.bootstrap_calls += 1
        return {
            "bootstrap_version": "phase1-test",
            "runner_mode": "background_process",
            "tunnel_port": 18765,
            "service_port": 43127,
            "token_ref": "runner://srv_test",
            "health": {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-21T12:00:00Z",
            },
            "bootstrap_metadata": {"deployment_action": "recovered"},
        }




class MutableTransport:
    def __init__(self, active: bool = True) -> None:
        self.active = active

    def is_active(self) -> bool:
        return self.active


class MutableClient:
    def __init__(self, transport: MutableTransport):
        self._transport = transport

    def get_transport(self) -> MutableTransport:
        return self._transport

    def close(self) -> None:
        return None


def test_resolve_ssh_password_returns_keyring_secret() -> None:
    cfg = {"ssh": {"password_ref": "ssh://tester@192.0.2.10:22", "auth_mode": "password_ref"}}
    with patch("config.keyring.get_password", return_value="secret") as get_password:
        assert resolve_ssh_password(cfg) == "secret"
    get_password.assert_called_once()


def test_startup_auto_connect_uses_saved_password_ref_when_flag_set() -> None:
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
        }
    }
    service = RuntimeService(service_locator=ServiceLocator(remote_runner_manager=ReadyRemoteRunnerManager()))

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.resolve_ssh_password", return_value="secret"
    ), patch(
        "core.app_runtime.service.ssh_connect"
    ) as connect_mock:
        service.initialize()

    connect_mock.assert_called_once_with(
        ip="192.0.2.10",
        port=22,
        user="tester",
        password="secret",
        key_file="",
        use_agent=False,
        timeout=5,
    )


def test_status_refresh_recovers_runner_when_ssh_stays_connected() -> None:
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
                "runner_mode": "background_process",
                "tunnel_port": 18000,
                "service_port": 43127,
                "token_ref": "runner://srv_test",
                "last_health_snapshot": {
                    "startup": {"ok": True, "message": "Remote runner config loaded."},
                    "live": {"ok": True, "message": "Remote runner process is alive."},
                    "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                    "reasonCode": "",
                    "checkedAt": "2026-04-21T12:00:00Z",
                },
            }
        },
    }
    manager = RecoveringRemoteRunnerManager()
    locator = ServiceLocator(remote_runner_manager=manager)
    locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    service = RuntimeService(service_locator=locator)
    service._initialized = True

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        cfg.clear()
        cfg.update(snapshot)

    def ensure_now(next_server_id: str) -> None:
        service.ensure_remote_runner_ready(next_server_id)

    with patch("core.app_runtime.service.get_config", lambda: cfg), patch(
        "core.app_runtime.service.save_config", save_capture
    ), patch.object(service, "_ensure_runner_ready_in_background", side_effect=ensure_now):
        status = service.get_ssh_status()

    assert status["connected"] is True
    assert manager.health_calls == 1
    assert manager.bootstrap_calls == 1
    assert status["runner"]["state"] == "ready"
    assert status["runner"]["deploymentAction"] == "recovered"




def test_connect_ssh_persists_key_mode_only() -> None:
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "password_ref": "",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
            "auto_connect_on_startup": False,
        }
    }
    saved = {}
    result = SimpleNamespace(ok=True, client=DummyClient(), message="")
    service = RuntimeService(service_locator=ServiceLocator(remote_runner_manager=ReadyRemoteRunnerManager()))
    service._initialized = True

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        saved.clear()
        saved.update(snapshot)
        cfg.clear()
        cfg.update(snapshot)

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.save_config", side_effect=save_capture
    ), patch("core.app_runtime.service.ssh_connect", return_value=result):
        status = service.connect_ssh({"auth_mode": "key_file", "identity_ref": "C:/keys/id_ed25519"})

    assert status["connected"] is True
    assert saved["ssh"]["auto_connect_on_startup"] is False
    assert saved["ssh"]["identity_ref"] == "C:/keys/id_ed25519"
    assert saved["ssh"]["auth_mode"] == "key_file"


def test_disconnect_ssh_clears_auto_connect_flag() -> None:
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "password_ref": "",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
            "auto_connect_on_startup": True,
        }
    }
    saved = {}
    locator = ServiceLocator()
    locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    service = RuntimeService(service_locator=locator)
    service._initialized = True

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        saved.clear()
        saved.update(snapshot)
        cfg.clear()
        cfg.update(snapshot)

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.save_config", side_effect=save_capture
    ):
        status = service.disconnect_ssh()

    assert status["connected"] is False
    assert saved["ssh"]["auto_connect_on_startup"] is False


def test_get_ssh_key_dir_uses_app_data_root() -> None:
    key_dir = get_ssh_key_dir()
    assert key_dir.name == "ssh"
    assert key_dir.parent.name in {".h2ometa", "H2OMeta"}


def test_connect_ssh_persists_password_ref_for_password_auth() -> None:
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "password_ref": "",
            "auth_mode": "password_ref",
            "identity_ref": "",
            "timeout_sec": 5,
            "auto_connect_on_startup": False,
        }
    }
    saved = {}
    result = SimpleNamespace(ok=True, client=DummyClient(), message="")
    service = RuntimeService(service_locator=ServiceLocator(remote_runner_manager=ReadyRemoteRunnerManager()))
    service._initialized = True

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        saved.clear()
        saved.update(snapshot)
        cfg.clear()
        cfg.update(snapshot)

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.save_config", side_effect=save_capture
    ), patch(
        "core.app_runtime.service.store_ssh_password",
        return_value=make_ssh_password_ref(host="192.0.2.10", port=22, user="tester"),
    ) as store_password, patch(
        "core.app_runtime.service.ssh_connect", return_value=result
    ):
        status = service.connect_ssh({"password": "secret", "auth_mode": "password_ref"})

    assert status["connected"] is True
    assert saved["ssh"]["password_ref"] == "ssh://tester@192.0.2.10:22"
    assert saved["ssh"]["auto_connect_on_startup"] is False
    assert saved["ssh"]["auth_mode"] == "password_ref"
    store_password.assert_called_once()


def test_connect_ssh_forces_password_auth_auto_connect_off() -> None:
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "password_ref": "",
            "auth_mode": "password_ref",
            "identity_ref": "",
            "timeout_sec": 5,
            "auto_connect_on_startup": False,
        }
    }
    saved = {}
    result = SimpleNamespace(ok=True, client=DummyClient(), message="")
    service = RuntimeService(service_locator=ServiceLocator(remote_runner_manager=ReadyRemoteRunnerManager()))
    service._initialized = True

    def save_capture(next_cfg: dict) -> None:
        saved.clear()
        saved.update(next_cfg)

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.save_config", side_effect=save_capture
    ), patch(
        "core.app_runtime.service.store_ssh_password",
        return_value=make_ssh_password_ref(host="192.0.2.10", port=22, user="tester"),
    ), patch(
        "core.app_runtime.service.ssh_connect", return_value=result
    ):
        status = service.connect_ssh(
            {
                "password": "secret",
                "auth_mode": "password_ref",
                "remember_auth": True,
                "auto_connect_on_startup": True,
            }
        )

    assert status["connected"] is True
    assert saved["ssh"]["auth_mode"] == "password_ref"
    assert saved["ssh"]["auto_connect_on_startup"] is False


def test_connect_ssh_failure_does_not_save_config() -> None:
    cfg = {
        "ssh": {
            "host": "",
            "port": 22,
            "user": "",
            "password_ref": "",
            "auth_mode": "password_ref",
            "identity_ref": "",
            "timeout_sec": 5,
            "auto_connect_on_startup": False,
        }
    }
    result = SimpleNamespace(ok=False, client=None, message="[WinError 10061] actively refused")
    service = RuntimeService(service_locator=ServiceLocator(remote_runner_manager=ReadyRemoteRunnerManager()))
    service._initialized = True

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.save_config"
    ) as save_config, patch(
        "core.app_runtime.service.ssh_connect", return_value=result
    ):
        try:
            service.connect_ssh(
                {
                    "password": "secret",
                    "auth_mode": "password_ref",
                    "host": "192.0.2.10",
                    "user": "tester",
                    "auto_connect_on_startup": True,
                }
            )
        except Exception as exc:
            assert "WinError 10061" in str(exc)
        else:
            raise AssertionError("connect_ssh should fail")

    save_config.assert_not_called()


def test_connect_ssh_resolves_ssh_config_alias_and_persists_new_model() -> None:
    cfg = {
        "ssh": {
            "auth_mode": "ssh_config",
            "ssh_host_alias": "prod-box",
            "password_ref": "",
            "identity_ref": "",
            "host": "",
            "port": 22,
            "user": "",
            "timeout_sec": 5,
            "auto_connect_on_startup": False,
        }
    }
    saved = {}
    result = SimpleNamespace(ok=True, client=DummyClient(), message="")
    service = RuntimeService(service_locator=ServiceLocator(remote_runner_manager=ReadyRemoteRunnerManager()))
    service._initialized = True

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        saved.clear()
        saved.update(snapshot)
        cfg.clear()
        cfg.update(snapshot)

    resolved = {
        "auth_mode": "ssh_config",
        "ssh_host_alias": "prod-box",
        "password_ref": "",
        "identity_ref": "C:/keys/id_ed25519",
        "host": "192.0.2.10",
        "port": 22,
        "user": "tester",
        "timeout_sec": 5,
        "auto_connect_on_startup": False,
    }

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.save_config", side_effect=save_capture
    ), patch(
        "core.app_runtime.service.resolve_ssh_config_target", return_value=resolved
    ), patch(
        "core.app_runtime.service.ssh_connect", return_value=result
    ):
        status = service.connect_ssh({"auth_mode": "ssh_config", "ssh_host_alias": "prod-box"})

    assert status["connected"] is True
    assert saved["ssh"]["auth_mode"] == "ssh_config"
    assert saved["ssh"]["ssh_host_alias"] == "prod-box"
    assert saved["ssh"]["identity_ref"] == "C:/keys/id_ed25519"


def test_connect_ssh_uses_agent_mode_without_password_or_identity() -> None:
    cfg = {
        "ssh": {
            "auth_mode": "agent",
            "ssh_host_alias": "",
            "password_ref": "",
            "identity_ref": "",
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "timeout_sec": 5,
            "auto_connect_on_startup": False,
        }
    }
    saved = {}
    result = SimpleNamespace(ok=True, client=DummyClient(), message="")
    service = RuntimeService(service_locator=ServiceLocator(remote_runner_manager=ReadyRemoteRunnerManager()))
    service._initialized = True

    def save_capture(next_cfg: dict) -> None:
        saved.clear()
        saved.update(next_cfg)

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.save_config", side_effect=save_capture
    ), patch(
        "core.app_runtime.service.ssh_connect", return_value=result
    ) as connect_mock:
        status = service.connect_ssh({"auth_mode": "agent", "host": "192.0.2.10", "user": "tester"})

    assert status["connected"] is True
    assert saved["ssh"]["auth_mode"] == "agent"
    assert saved["ssh"]["auto_connect_on_startup"] is False
    connect_mock.assert_called_once()
    assert connect_mock.call_args.kwargs["use_agent"] is True


def test_ssh_reconnect_closes_existing_tunnels() -> None:
    transport = MutableTransport(active=True)
    service = SSHService(initial_client=MutableClient(transport))
    closed = {"count": 0}

    class FakeTunnel:
        def close(self) -> None:
            closed["count"] += 1

    service._tunnels["runner-srv"] = FakeTunnel()
    service._on_reconnect(MutableClient(MutableTransport(active=True)))

    assert closed["count"] == 1
    assert service._tunnels == {}
