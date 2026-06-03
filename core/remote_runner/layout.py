from __future__ import annotations

REMOTE_RUNNER_RELATIVE_ROOT = ".h2ometa/runner"
REMOTE_RUNNER_SERVICE_NAME = "h2ometa-remote.service"
REMOTE_RUNNER_PROFILE_NAME = "profile.v9+.yaml"

REMOTE_RUNNER_ROOT_SHELL_PATH = f"$HOME/{REMOTE_RUNNER_RELATIVE_ROOT}"
REMOTE_RUNNER_SHARED_SHELL_PATH = f"{REMOTE_RUNNER_ROOT_SHELL_PATH}/shared"
REMOTE_RUNNER_RUNTIME_STATE_SHELL_PATH = f"{REMOTE_RUNNER_SHARED_SHELL_PATH}/runtime/runner-state.json"
REMOTE_RUNNER_STOP_SCRIPT_SHELL_PATH = f"{REMOTE_RUNNER_ROOT_SHELL_PATH}/current/stop_service.sh"

REMOTE_STOP_SYSTEMD_OUTPUT = "/tmp/h2ometa-stop-systemd.out"
REMOTE_STOP_SCRIPT_OUTPUT = "/tmp/h2ometa-stop-script.out"
REMOTE_STOP_PROCESS_OUTPUT = "/tmp/h2ometa-stop-pkill.out"


def remote_runner_root(home_dir: str) -> str:
    return f"{home_dir}/{REMOTE_RUNNER_RELATIVE_ROOT}"


def remote_runner_shared(home_dir: str) -> str:
    return f"{remote_runner_root(home_dir)}/shared"


def remote_runner_config(home_dir: str) -> str:
    return f"{remote_runner_shared(home_dir)}/config/runner.json"


def remote_runner_runtime_state(home_dir: str) -> str:
    return f"{remote_runner_shared(home_dir)}/runtime/runner-state.json"


def remote_runner_log(home_dir: str) -> str:
    return f"{remote_runner_shared(home_dir)}/logs/runner.log"


def remote_runner_release(home_dir: str, version: str) -> str:
    return f"{remote_runner_root(home_dir)}/releases/{version}"


def remote_runner_current(home_dir: str) -> str:
    return f"{remote_runner_root(home_dir)}/current"


def remote_runner_start_command(home_dir: str, remote_config: str | None = None, remote_log: str | None = None) -> str:
    config = remote_config or remote_runner_config(home_dir)
    log = remote_log or remote_runner_log(home_dir)
    return f"bash {remote_runner_current(home_dir)}/start_service.sh {config} {log}"
