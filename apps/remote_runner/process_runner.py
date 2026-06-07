from __future__ import annotations

from collections.abc import Callable
import os
import signal
import subprocess
import time


ShouldCancel = Callable[[], bool]
ProcessStarted = Callable[[int], None]


def run_process(
    command: list[str],
    *,
    env: dict[str, str],
    should_cancel: ShouldCancel | None = None,
    on_process_started: ProcessStarted | None = None,
    poll_interval_seconds: float = 0.2,
    terminate_timeout_seconds: float = 5.0,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        **_process_group_kwargs(),
    )
    if on_process_started is not None:
        on_process_started(int(process.pid))
    while True:
        if should_cancel is not None and should_cancel():
            return _terminate_process(
                process,
                command=command,
                timeout_seconds=terminate_timeout_seconds,
                reason="Snakemake process terminated after stale lease.",
            )
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        time.sleep(max(0.0, float(poll_interval_seconds)))


def _process_group_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _terminate_process(
    process: subprocess.Popen[str],
    *,
    command: list[str],
    timeout_seconds: float,
    reason: str,
) -> subprocess.CompletedProcess[str]:
    _terminate_process_group(process)
    try:
        stdout, stderr = process.communicate(timeout=max(0.0, float(timeout_seconds)))
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        stdout, stderr = process.communicate()
    stderr = _append_reason(stderr, reason)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        process.terminate()
        return
    os.killpg(process.pid, signal.SIGTERM)


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        process.kill()
        return
    os.killpg(process.pid, signal.SIGKILL)


def _append_reason(stderr: str | None, reason: str) -> str:
    existing = str(stderr or "").rstrip()
    if not existing:
        return reason
    return f"{existing}\n{reason}"
