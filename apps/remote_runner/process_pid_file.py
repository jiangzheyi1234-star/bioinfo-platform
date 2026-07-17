"""Diagnostic PID-file publication for the remote-runner process.

The PID file is a legacy operational hint consumed by transitional stop/check
scripts. It is not ownership, liveness, or process-incarnation proof. The
cooperating lifetime lock is the only single-instance fence in this slice.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Protocol


RUNNER_PID_FILENAME = "runner.pid"


class ProcessPidFileConfig(Protocol):
    release_dir: str


def get_runner_pid_file_path(cfg: ProcessPidFileConfig) -> Path:
    release_dir = str(cfg.release_dir or "").strip()
    if not release_dir:
        raise ValueError("REMOTE_RUNNER_RELEASE_DIR_MISSING")
    return Path(release_dir).parent / RUNNER_PID_FILENAME


def write_runner_pid_file_atomic(
    cfg: ProcessPidFileConfig,
    *,
    pid: int | None = None,
) -> Path:
    """Atomically publish the winning launcher's PID for diagnostics only."""

    process_pid = _require_process_pid(os.getpid() if pid is None else pid)
    path = get_runner_pid_file_path(cfg)
    fd, raw_temp_path = tempfile.mkstemp(
        prefix=f".{path.name}.{process_pid}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(raw_temp_path)
    fd_open = True
    try:
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd_open = False
            handle.write(f"{process_pid}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        if fd_open:
            os.close(fd)
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return path


def remove_runner_pid_file_if_owned(
    cfg: ProcessPidFileConfig,
    *,
    pid: int | None = None,
) -> bool:
    """Remove only the canonical PID file written for this exact process."""

    return remove_runner_pid_file_path_if_owned(
        get_runner_pid_file_path(cfg),
        pid=pid,
    )


def remove_runner_pid_file_path_if_owned(
    path: Path,
    *,
    pid: int | None = None,
) -> bool:
    """Remove one explicit diagnostic PID path only when this process owns it."""

    process_pid = _require_process_pid(os.getpid() if pid is None else pid)
    try:
        payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    if payload != f"{process_pid}\n":
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    _fsync_directory(path.parent)
    return True


def _require_process_pid(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("REMOTE_RUNNER_PID_INVALID")
    return value


def _fsync_directory(path: Path) -> None:
    try:
        directory_fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


__all__ = [
    "RUNNER_PID_FILENAME",
    "get_runner_pid_file_path",
    "remove_runner_pid_file_if_owned",
    "remove_runner_pid_file_path_if_owned",
    "write_runner_pid_file_atomic",
]
