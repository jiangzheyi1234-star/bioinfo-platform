from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"

CONTRACT_FILES = {
    "model": COMPONENTS / "ssh-shell-model.ts",
    "ui": COMPONENTS / "ssh-shell-ui.tsx",
    "repair": COMPONENTS / "ssh-runner-repair-panel.tsx",
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
    source = _source("model")

    _assert_contains(
        source,
        'status.runner.state === "recovering"',
        "远程服务正在恢复",
        "正在重建安全通道",
    )


def test_remote_status_panel_exposes_runner_ports_and_stop_action() -> None:
    model_source = _source("model")
    ui_source = _source("ui")
    repair_source = _source("repair")

    _assert_contains(model_source, "serverId?: string")
    _assert_contains(ui_source, "RunnerRepairPanel")
    _assert_contains(
        repair_source,
        "type RunnerRepairStatus",
        "resolveRemoteStatus(status)",
        "Runner Repair",
        "远端服务",
        "本地隧道",
        "runner.servicePort",
        "runner.tunnelPort",
        "停止 Runner",
    )
    _assert_matches(
        repair_source,
        r"`/api/v1/servers/\$\{encodeURIComponent\(serverId\)\}/runner/stop`",
        r"`/api/v1/servers/\$\{encodeURIComponent\(serverId\)\}/listening-ports`",
        r"await\s+onRefreshStatus\(\)",
    )
    _assert_not_contains(ui_source + repair_source, "/api/v1/ssh/remote-service/stop")
    _assert_not_contains(repair_source, "/api/v1/ssh/listening-ports")
    _assert_not_contains(repair_source, "absolute bottom-full")
    _assert_contains(ui_source, 'className="absolute bottom-full left-2 z-30 mb-1 w-[360px]"')


def test_runner_repair_panel_exposes_upgrade_prune_and_operator_diagnostics() -> None:
    source = _source("repair")

    _assert_contains(
        source,
        'data-testid="runner-repair-panel"',
        "/runner/upgrade",
        "/runner/releases/prune/preview",
        "/runner/releases/prune/run",
        "/runner/uninstall/preview",
        "/runner/uninstall/run",
        "/operator-diagnostics",
        'confirmation: "prune-runner-releases"',
        'confirmation: "uninstall-runner-control-plane"',
        "升级 Runner",
        "旧版本清理",
        "控制面卸载",
        "Operator",
        "DestructiveConfirmation",
        "confirmationMatches",
        "stopConfirmation",
        "pruneConfirmation",
        "uninstallConfirmation",
        "输入 ${target}",
        "aria-label={`${action} 确认 serverId`}",
        "useEffect",
        "setPrunePlan(null)",
        "setUninstallPlan(null)",
        "setStopConfirmation(\"\")",
        "}, [serverId])",
    )
    _assert_contains(source, "className?: string", "className = \"\"")
    _assert_contains(source, "diagnosticsOnly?: boolean", "diagnosticsOnly = false")
    _assert_contains(source, "onClose?: () => void", "{onClose ? (")
    _assert_not_contains(source, "type SSHStatus")
    _assert_matches(source, r"disabled=\{!canStopRunner\s*\|\|\s*!stopConfirmed\s*\|\|\s*stopLoading")
    _assert_matches(source, r"disabled=\{\s*!canPrune\s*\|\|\s*pruneLoading\s*\|\|\s*deletableReleaseCount <= 0")
    _assert_matches(source, r"!prunePlan\?\.planHash\s*\|\|\s*!pruneConfirmed")
    _assert_matches(source, r"disabled=\{\s*!canUninstall\s*\|\|\s*")
    _assert_matches(source, r"!uninstallPlan\?\.planHash\s*\|\|\s*!uninstallConfirmed")
    _assert_matches(
        source,
        r"const stopRemoteService = async \(\) => \{.*if \(!canStopRunner \|\| !stopConfirmed \|\| stopLoading\)",
        r"const runPrune = async \(\) => \{.*if \(!canPrune \|\| !planHash \|\| !pruneConfirmed",
        r"const runUninstall = async \(\) => \{.*if \(!canUninstall \|\| !planHash \|\| !uninstallConfirmed",
    )


def test_manual_runner_stop_is_explicit_start_not_repair() -> None:
    model_source = _source("model")
    ui_source = _source("ui")
    repair_source = _source("repair")

    _assert_contains(
        model_source,
        'MANUAL_RUNNER_STOP_REASON = "RUNNER_STOPPED"',
        "isRunnerManuallyStopped",
        "启动远程服务",
        "远程服务已手动停止",
    )
    _assert_contains(
        ui_source + repair_source,
        "isRunnerManuallyStopped(status)",
        "runnerEnsureActionLabel(status, ensureRunnerBusy)",
        "runnerSidebarSubcopy(status)",
    )
    _assert_contains(
        model_source,
        "远程服务已停止",
        "等待手动启动",
    )


def test_remote_status_failed_runner_can_trigger_repair_bootstrap() -> None:
    ui_source = _source("ui")
    repair_source = _source("repair")
    hook_source = _source("connection")
    model_source = _source("model")

    _assert_contains(
        model_source,
        "修复远程服务",
        "准备远程服务",
    )
    _assert_contains(ui_source + repair_source, "runnerEnsureActionLabel(status, ensureRunnerBusy)")
    _assert_matches(
        repair_source,
        r"status\?\.connected\s*&&\s*serverId\s*&&\s*!\s*status\.runner\?\.ready",
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


def test_ssh_host_key_trust_flow_requires_fingerprint_confirmation() -> None:
    hook_source = _source("connection")
    ui_source = _source("ui")
    model_source = _source("model")

    _assert_contains(
        model_source,
        "SSHHostKeyCandidate",
        "hostKeyFingerprintSha256",
        "knownHostsPath",
    )
    _assert_contains(
        hook_source,
        "SSH_HOST_KEY_UNTRUSTED",
        "buildSshHostKeyTargetPayload",
        "/api/v1/ssh/host-key/scan",
        "/host-key/accept",
        'confirmation: "trust-ssh-host-key"',
        "fingerprintSha256: hostKeyCandidate.hostKeyFingerprintSha256",
    )
    host_key_payload = hook_source.split("function buildSshHostKeyTargetPayload", 1)[1].split(
        "function targetLabelForForm", 1
    )[0]
    connect_payload = hook_source.split("function buildSshConnectionPayload", 1)[1].split(
        "function buildSshHostKeyTargetPayload", 1
    )[0]
    _assert_contains(connect_payload, "password: form.password")
    _assert_not_contains(host_key_payload, "password", "identity_ref")
    _assert_contains(ui_source, "信任并连接", "hostKeyCandidate.hostKeyFingerprintSha256")
    _assert_matches(ui_source, r"disabled=\{connectDisabled\s*\|\|\s*Boolean\(hostKeyCandidate\)\}")
