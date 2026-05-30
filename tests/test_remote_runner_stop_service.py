from __future__ import annotations

import asyncio
from pathlib import Path

from apps.api.main import stop_ssh_remote_service
from core.app_runtime.service import RuntimeService, ServiceLocator


def make_service(_tmp_path: Path, ssh_service) -> RuntimeService:
    service = RuntimeService(
        service_locator=ServiceLocator(ssh_service=ssh_service),
    )
    service._initialized = True
    return service


def test_stop_remote_runner_service_runs_explicit_stop_commands(monkeypatch, tmp_path: Path) -> None:
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {},
    }

    class FakeSSH:
        is_connected = True

        def __init__(self) -> None:
            self.commands: list[tuple[str, int]] = []

        def run(self, cmd: str, timeout: int = 10):
            self.commands.append((cmd, timeout))
            return 0, "systemd_user=stopped\nstop_script=stopped\nprocess=not-running\n", ""

    fake_ssh = FakeSSH()
    service = make_service(tmp_path, fake_ssh)

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        cfg.clear()
        cfg.update(snapshot)

    monkeypatch.setattr("core.app_runtime.service.get_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.service.save_config", save_capture)
    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    result = asyncio.run(stop_ssh_remote_service())

    command, timeout = fake_ssh.commands[0]
    assert timeout == 30
    assert "systemctl --user stop h2ometa-remote.service" in command
    assert "sh \"$STOP_SCRIPT\"" in command
    assert "pkill -f '[r]emote_runner.run'" in command
    assert "runner-state.json" in command
    assert result["data"]["ok"] is True
    assert result["item"]["runner"]["reasonCode"] == "RUNNER_STOPPED"
    assert next(iter(cfg["servers"].values()))["last_health_snapshot"]["reasonCode"] == "RUNNER_STOPPED"
