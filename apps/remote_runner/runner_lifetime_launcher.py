"""Fixed runner launcher that acquires the lifetime fence before mutation."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import subprocess
import sys
from typing import NoReturn, Protocol

from .process_lifetime_lock import (
    RunnerProcessLifetimeLockError,
    acquire_runner_process_lifetime_lock,
)
from .process_pid_file import (
    remove_runner_pid_file_if_owned,
    write_runner_pid_file_atomic,
)
from .runner_protocol_startup import load_remote_runner_config_from_startup_preflight


class ProcessLifetimeLauncherConfig(Protocol):
    release_dir: str
    runner_python: str
    runtime_state_path: str


def launch_remote_runner() -> NoReturn:
    """Acquire once, prepare the runtime, then exec the runner with the same PID."""

    cfg = load_remote_runner_config_from_startup_preflight()
    lifetime_lock = acquire_runner_process_lifetime_lock(cfg)
    try:
        write_runner_pid_file_atomic(cfg)
        environment = _build_runtime_environment(cfg, os.environ)
        _prepare_bundled_runtime(
            cfg,
            environment,
            lock_pass_fds=lifetime_lock.mutation_subprocess_pass_fds(),
        )
        exec_environment = lifetime_lock.build_exec_environment(environment)
        _exec_remote_runner(cfg, exec_environment)
        raise RuntimeError("REMOTE_RUNNER_EXEC_RETURNED")
    except BaseException:
        try:
            remove_runner_pid_file_if_owned(cfg)
        finally:
            lifetime_lock.release()
        raise


def main() -> int:
    try:
        launch_remote_runner()
    except RunnerProcessLifetimeLockError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_status


def _build_runtime_environment(
    cfg: ProcessLifetimeLauncherConfig,
    environ: Mapping[str, str],
) -> dict[str, str]:
    environment = dict(environ)
    shared_root = Path(cfg.runtime_state_path).parent.parent
    tools_bin = shared_root / "tools" / "bin"
    if tools_bin.is_dir():
        current_path = str(environment.get("PATH") or "")
        environment["PATH"] = (
            f"{tools_bin}{os.pathsep}{current_path}" if current_path else str(tools_bin)
        )
    return environment


def _prepare_bundled_runtime(
    cfg: ProcessLifetimeLauncherConfig,
    environment: Mapping[str, str],
    *,
    lock_pass_fds: tuple[int, ...],
) -> None:
    runner_python = Path(cfg.runner_python)
    runtime_root = runner_python.parent.parent
    conda_unpack = runtime_root / "bin" / "conda-unpack"
    unpacked_marker = runtime_root / ".h2ometa-conda-unpacked"
    if (
        conda_unpack.is_file()
        and os.access(conda_unpack, os.X_OK)
        and not unpacked_marker.is_file()
    ):
        subprocess.run(
            [str(runner_python), str(conda_unpack)],
            check=True,
            cwd=str(Path(cfg.release_dir).parent),
            env=dict(environment),
            pass_fds=lock_pass_fds,
        )
        unpacked_marker.touch(exist_ok=True)


def _exec_remote_runner(
    cfg: ProcessLifetimeLauncherConfig,
    environment: Mapping[str, str],
) -> NoReturn:
    executable = str(Path(cfg.runner_python))
    os.execve(
        executable,
        [executable, "-B", "-m", "remote_runner.run"],
        dict(environment),
    )
    raise RuntimeError("REMOTE_RUNNER_EXEC_RETURNED")  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["launch_remote_runner", "main"]
