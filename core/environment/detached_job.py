"""Shared helpers for submitting detached remote shell jobs over ssh_run_fn."""

from __future__ import annotations

import base64
from typing import Iterable

from core.remote.server_capabilities import SshRunFn

STATUS_FILES = ("status.txt", "exit_code.txt", "heartbeat.txt")


def expand_home_expr(path: str) -> str:
    """Replace ``~`` with ``$HOME`` for shell-safe eval usage."""
    return path.replace("~", "$HOME")


def expanded_remote_path(path: str) -> str:
    """Return a remote shell expression that resolves ``~`` on the server."""
    return f'"$(eval echo {expand_home_expr(path)})"'


def ensure_remote_dirs(ssh_run_fn: SshRunFn, paths: Iterable[str], timeout: int) -> None:
    for path in paths:
        normalized = str(path or "").strip()
        if not normalized:
            continue
        ssh_run_fn(f"mkdir -p {expanded_remote_path(normalized)}", timeout)


def clear_remote_status_files(
    ssh_run_fn: SshRunFn,
    task_dir: str,
    timeout: int,
    filenames: Iterable[str] = STATUS_FILES,
) -> None:
    names = [str(name or "").strip() for name in filenames if str(name or "").strip()]
    if not names:
        return
    base_dir = expanded_remote_path(task_dir)
    joined = " ".join(f"{base_dir}/{name}" for name in names)
    ssh_run_fn(f"rm -f {joined}", timeout)


def write_remote_script(
    ssh_run_fn: SshRunFn,
    remote_path: str,
    script: str,
    timeout: int,
    *,
    label: str,
) -> str:
    """Write a shell script through base64 and mark it executable."""
    remote_path_expanded = expanded_remote_path(remote_path)
    encoded = base64.b64encode(script.encode()).decode()
    rc, _, stderr = ssh_run_fn(
        f"echo '{encoded}' | base64 -d > {remote_path_expanded}",
        timeout,
    )
    if rc != 0:
        raise RuntimeError(f"写入{label}失败: {stderr[:200]}")
    ssh_run_fn(f"chmod +x {remote_path_expanded}", timeout)
    return remote_path_expanded


def start_screen_script(
    ssh_run_fn: SshRunFn,
    job_id: str,
    script_path: str,
    timeout: int,
    *,
    error_prefix: str,
) -> None:
    """Restart a detached screen session and run the target script."""
    ssh_run_fn(f"screen -S {job_id} -X quit 2>/dev/null || true", timeout)
    rc, _, stderr = ssh_run_fn(f"screen -dmS {job_id} bash {script_path}", timeout)
    if rc != 0:
        raise RuntimeError(f"{error_prefix}: {stderr[:200]}")
