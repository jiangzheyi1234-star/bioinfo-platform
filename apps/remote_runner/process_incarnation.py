"""Capture fail-closed Linux procfs evidence for the runner process."""

from __future__ import annotations

import os
from pathlib import Path

from core.contracts.linux_process_incarnation import (
    build_linux_process_incarnation,
    parse_proc_stat_start_ticks,
)


def capture_linux_process_incarnation(
    *,
    pid: int | None = None,
    proc_root: Path = Path("/proc"),
    boot_id_path: Path = Path("/proc/sys/kernel/random/boot_id"),
) -> dict[str, object]:
    """Read the current boot ID and proc start time for exactly one PID."""

    target_pid = os.getpid() if pid is None else pid
    if isinstance(target_pid, bool) or not isinstance(target_pid, int):
        raise RuntimeError("remote runner process incarnation pid is invalid")
    if target_pid <= 0:
        raise RuntimeError("remote runner process incarnation pid is invalid")
    try:
        boot_id = boot_id_path.read_text(encoding="utf-8").strip().lower()
        stat_text = (proc_root / str(target_pid) / "stat").read_text(
            encoding="utf-8"
        )
        proc_start_ticks = parse_proc_stat_start_ticks(
            stat_text,
            expected_pid=target_pid,
        )
        return build_linux_process_incarnation(
            boot_id=boot_id,
            pid=target_pid,
            proc_start_ticks=proc_start_ticks,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError(
            "remote runner Linux procfs process incarnation is unavailable"
        ) from exc


__all__ = ["capture_linux_process_incarnation"]
