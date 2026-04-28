from __future__ import annotations

from pathlib import Path


STATUS_UI = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "app"
    / "components"
    / "ssh-shell-ui.tsx"
)
CONNECTION_HOOK = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "web"
    / "app"
    / "components"
    / "ssh-shell-connection.ts"
)


def test_remote_status_has_recovering_runner_copy() -> None:
    source = STATUS_UI.read_text(encoding="utf-8")

    assert 'status.runner.state === "recovering"' in source
    assert "远程服务正在恢复" in source
    assert "正在重建安全通道" in source


def test_remote_status_panel_shows_runner_ports() -> None:
    source = STATUS_UI.read_text(encoding="utf-8")

    assert "远端服务端口" in source
    assert "远端服务" in source
    assert "本地隧道" in source
    assert "runner.servicePort" in source
    assert "runner.tunnelPort" in source


def test_remote_status_panel_can_stop_remote_service() -> None:
    ui_source = STATUS_UI.read_text(encoding="utf-8")

    assert "停止远程服务" in ui_source
    assert "stopRemoteService" in ui_source
    assert "/api/v1/ssh/remote-service/stop" in ui_source
    assert "onRefreshStatus" in ui_source


def test_remote_status_failed_runner_can_trigger_repair_bootstrap() -> None:
    ui_source = STATUS_UI.read_text(encoding="utf-8")
    hook_source = CONNECTION_HOOK.read_text(encoding="utf-8")

    assert "修复远程服务" in ui_source
    assert "准备远程服务" in ui_source
    assert "onEnsureRunner" in ui_source
    assert "RemoteStatusBar" in ui_source
    assert "ensureRunner" in hook_source
    assert "/ensure-runner" in hook_source
    assert "current?.connected" in hook_source
    assert "current?.connected && !current.runner" not in hook_source
