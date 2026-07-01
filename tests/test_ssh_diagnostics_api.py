from __future__ import annotations

from types import SimpleNamespace

from core.app_runtime.service import RuntimeService, ServiceLocator


def test_ssh_diagnostics_api_returns_dict_steps_without_attribute_adapter(monkeypatch, tmp_path) -> None:
    cfg = {
        "ssh": {
            "auth_mode": "password_ref",
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "password_ref": "ssh://tester@192.0.2.10:22",
            "identity_ref": "",
            "timeout_sec": 5,
        }
    }
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    received_kwargs = {}
    diagnostic_steps = [
        {"name": "DNS/IP", "status": "ok", "message": "192.0.2.10 resolved", "phase": "dns_lookup"},
        {
            "name": "TCP",
            "status": "fail",
            "message": "SSH 端口拒绝连接，请确认远端 sshd 正在监听。",
            "code": "SSH_TCP_REFUSED",
            "phase": "tcp_connect",
        },
    ]

    def fake_run_diagnostics(**kwargs):
        received_kwargs.update(kwargs)
        return diagnostic_steps

    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.ssh_connection.resolve_ssh_password", lambda _cfg: "secret")
    monkeypatch.setattr("core.app_runtime.ssh_connection.run_diagnostics", fake_run_diagnostics)

    result = service.test_ssh_connection({"password": "fresh-secret"})

    assert result["ok"] is False
    assert result["message"] == "SSH diagnostics failed"
    assert result["steps"] == diagnostic_steps
    assert result["status"]["connected"] is False
    assert received_kwargs == {
        "ip": "192.0.2.10",
        "port": 22,
        "user": "tester",
        "password": "fresh-secret",
        "key_file": "",
        "use_agent": False,
        "timeout": 5,
    }


def test_ssh_diagnostics_status_reports_test_target_not_current_session(monkeypatch) -> None:
    cfg = {
        "ssh": {
            "auth_mode": "password_ref",
            "host": "198.51.100.10",
            "port": 22,
            "user": "current",
            "password_ref": "ssh://current@198.51.100.10:22",
            "identity_ref": "",
            "timeout_sec": 5,
        }
    }
    service = RuntimeService(service_locator=ServiceLocator())
    service._initialized = True
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)

    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    monkeypatch.setattr(
        "core.app_runtime.ssh_connection.run_diagnostics",
        lambda **_kwargs: [
            {"name": "DNS/IP", "status": "ok", "message": "192.0.2.10 resolved", "phase": "dns_lookup"}
        ],
    )

    result = service.test_ssh_connection(
        {
            "auth_mode": "password_ref",
            "host": "192.0.2.10",
            "port": 2222,
            "user": "tester",
            "password": "fresh-secret",
        }
    )

    assert result["ok"] is True
    assert result["status"]["connected"] is False
    assert result["status"]["host"] == "192.0.2.10"
    assert result["status"]["port"] == 2222
    assert result["status"]["user"] == "tester"
    assert result["currentStatus"]["connected"] is True
    assert result["currentStatus"]["host"] == "198.51.100.10"
    assert result["currentStatus"]["user"] == "current"
