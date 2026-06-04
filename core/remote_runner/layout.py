from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class RemoteRunnerBootstrapLayout:
    root: str
    release: str
    shared: str
    bundle: str
    config: str
    conda_prefix: str
    profile_dir: str
    profile_name: str
    profile_path: str
    wrapper_prefix: str
    runtime_state: str
    log: str
    current: str
    artifact_sha: str
    tools: str
    install_lock: str
    service_python: str

    def workflow_runtime_dir(self, *, version: str, platform: str) -> str:
        return f"{self.tools}/workflow-runtime-{version}-{platform}"

    def workflow_runtime_bundle(self, *, version: str, platform: str) -> str:
        return f"{self.tools}/workflow-runtime-{version}-{platform}.tar.gz"

    def remote_directories(self) -> tuple[str, ...]:
        return (
            f"{self.root}/releases",
            f"{self.shared}/config",
            f"{self.shared}/data",
            f"{self.shared}/logs",
            f"{self.shared}/uploads",
            f"{self.shared}/results",
            f"{self.shared}/work",
            self.conda_prefix,
            self.profile_dir,
            self.tools,
        )


def remote_runner_bootstrap_layout(home_dir: str, version: str) -> RemoteRunnerBootstrapLayout:
    root = remote_runner_root(home_dir)
    release = remote_runner_release(home_dir, version)
    shared = remote_runner_shared(home_dir)
    profile_dir = f"{shared}/config/snakemake/default"
    profile_name = REMOTE_RUNNER_PROFILE_NAME
    return RemoteRunnerBootstrapLayout(
        root=root,
        release=release,
        shared=shared,
        bundle=f"{root}/bundle-{version}.tar.gz",
        config=remote_runner_config(home_dir),
        conda_prefix=f"{shared}/conda-envs",
        profile_dir=profile_dir,
        profile_name=profile_name,
        profile_path=f"{profile_dir}/{profile_name}",
        wrapper_prefix=f"file://{release}/remote_runner/snakemake_wrappers/",
        runtime_state=remote_runner_runtime_state(home_dir),
        log=remote_runner_log(home_dir),
        current=remote_runner_current(home_dir),
        artifact_sha=f"{release}/artifact.sha256",
        tools=f"{root}/tools",
        install_lock=f"{root}/locks/install-{version}.lock",
        service_python=f"{release}/runtime/bin/python",
    )
