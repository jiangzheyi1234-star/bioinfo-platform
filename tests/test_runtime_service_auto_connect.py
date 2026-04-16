from types import SimpleNamespace
from unittest.mock import patch

from config import get_ssh_key_dir, resolve_ssh_password
from core.app_runtime.service import RuntimeService, ServiceLocator


class DummyTransport:
    def is_active(self) -> bool:
        return True


class DummyClient:
    def get_transport(self) -> DummyTransport:
        return DummyTransport()

    def close(self) -> None:
        return None


def test_resolve_ssh_password_returns_inline_only() -> None:
    cfg = {"ssh": {"password": "secret", "use_key": False}}
    assert resolve_ssh_password(cfg) == "secret"


def test_startup_auto_connect_requires_key_mode() -> None:
    cfg = {
        "ssh": {
            "host": "192.168.0.10",
            "port": 22,
            "user": "tester",
            "password": "",
            "use_key": False,
            "key_file": "",
            "timeout_sec": 5,
            "auto_connect_on_startup": True,
        }
    }
    service = RuntimeService(service_locator=ServiceLocator())

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.ssh_connect"
    ) as connect_mock:
        service.initialize()

    assert connect_mock.call_count == 0


def test_connect_ssh_persists_key_mode_only() -> None:
    cfg = {
        "ssh": {
            "host": "192.168.0.10",
            "port": 22,
            "user": "tester",
            "password": "",
            "use_key": True,
            "key_file": "C:/keys/id_ed25519",
            "timeout_sec": 5,
            "auto_connect_on_startup": False,
        }
    }
    saved = {}
    result = SimpleNamespace(ok=True, client=DummyClient(), message="")
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True

    def save_capture(next_cfg: dict) -> None:
        saved.clear()
        saved.update(next_cfg)

    with patch("core.app_runtime.service.get_config", return_value=cfg), patch(
        "core.app_runtime.service.save_config", side_effect=save_capture
    ), patch("core.app_runtime.service.ssh_connect", return_value=result):
        status = service.connect_ssh({"use_key": True, "key_file": "C:/keys/id_ed25519"})

    assert status["connected"] is True
    assert saved["ssh"]["auto_connect_on_startup"] is True
    assert saved["ssh"]["key_file"] == "C:/keys/id_ed25519"


def test_disconnect_ssh_clears_auto_connect_flag() -> None:
    cfg = {
        "ssh": {
            "host": "192.168.0.10",
            "port": 22,
            "user": "tester",
            "password": "",
            "use_key": True,
            "key_file": "C:/keys/id_ed25519",
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
        saved.clear()
        saved.update(next_cfg)

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
