from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"

CONTRACT_FILES = {
    "model": COMPONENTS / "ssh-shell-model.ts",
    "ui": COMPONENTS / "ssh-shell-ui.tsx",
    "connection": COMPONENTS / "ssh-shell-connection.ts",
}


def _source(name: str) -> str:
    return CONTRACT_FILES[name].read_text(encoding="utf-8")


def _assert_contains(source: str, *tokens: str) -> None:
    for token in tokens:
        assert token in source


def _assert_not_contains(source: str, *tokens: str) -> None:
    for token in tokens:
        assert token not in source


def _assert_matches(source: str, *patterns: str) -> None:
    for pattern in patterns:
        assert re.search(pattern, source, re.DOTALL), pattern


def test_remote_status_has_recovering_runner_copy() -> None:
    source = _source("ui")

    _assert_contains(
        source,
        'status.runner.state === "recovering"',
        "远程服务正在恢复",
        "正在重建安全通道",
    )


def test_remote_status_panel_exposes_runner_ports_and_stop_action() -> None:
    model_source = _source("model")
    source = _source("ui")

    _assert_contains(model_source, "serverId?: string")
    _assert_contains(
        source,
        "远端服务端口",
        "远端服务",
        "本地隧道",
        "runner.servicePort",
        "runner.tunnelPort",
        "停止远程服务",
    )
    _assert_matches(
        source,
        r"`/api/v1/servers/\$\{encodeURIComponent\(serverId\)\}/runner/stop`",
        r"await\s+onRefreshStatus\(\)",
    )
    _assert_not_contains(source, "/api/v1/ssh/remote-service/stop")


def test_manual_runner_stop_is_explicit_start_not_repair() -> None:
    model_source = _source("model")
    ui_source = _source("ui")

    _assert_contains(
        model_source,
        'MANUAL_RUNNER_STOP_REASON = "RUNNER_STOPPED"',
        "isRunnerManuallyStopped",
        "启动远程服务",
        "远程服务已手动停止",
    )
    _assert_contains(
        ui_source,
        "isRunnerManuallyStopped(status)",
        "runnerEnsureActionLabel(status, ensureRunnerBusy)",
        "runnerSidebarSubcopy(status)",
        "远程服务已停止",
        "等待手动启动",
    )


def test_remote_status_failed_runner_can_trigger_repair_bootstrap() -> None:
    ui_source = _source("ui")
    hook_source = _source("connection")
    model_source = _source("model")

    _assert_contains(
        model_source,
        "修复远程服务",
        "准备远程服务",
    )
    _assert_contains(ui_source, "runnerEnsureActionLabel(status, ensureRunnerBusy)")
    _assert_matches(
        ui_source,
        r"status\?\.connected\s*&&\s*!\s*status\.runner\?\.ready",
        r"onClick=\{onEnsureRunner\}",
    )
    _assert_contains(
        hook_source,
        "ensure-runner",
        "runner/start",
        "isRunnerManuallyStopped(status)",
        "state: \"repair_needed\"",
    )
    _assert_matches(
        hook_source,
        r"const\s+ensureRunner\s*=\s*useCallback\(async\s*\(\)\s*=>\s*\{",
        r"if\s*\(\s*!status\?\.connected\s*\|\|\s*ensureInFlightRef\.current\s*\)",
        r"setStatus\(\(current\)\s*=>\s*\(current\?\.connected\s*\?",
    )
    _assert_not_contains(
        hook_source,
        "current?.connected && !current.runner",
    )


def test_connecting_status_is_not_reported_as_connected() -> None:
    hook_source = _source("connection")
    preparing_status = hook_source.split("function makePreparingStatus", 1)[1].split(
        "export function useSshConnection", 1
    )[0]

    _assert_contains(preparing_status, "connected: false", "connecting: true")
    _assert_not_contains(preparing_status, "connected: true", "runner:")
