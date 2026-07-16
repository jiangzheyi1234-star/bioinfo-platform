"""Atomic runtime-state publication for the remote runner process."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Protocol

from core.contracts.linux_process_incarnation import (
    require_linux_process_incarnation,
)
from core.contracts.runner_protocol_runtime import (
    build_runner_protocol_runtime_self_attestation,
)

from .process_incarnation import capture_linux_process_incarnation


class RuntimeStateConfig(Protocol):
    service_name: str
    version: str
    runtime_state_path: str


def get_runtime_state_path(cfg: RuntimeStateConfig) -> Path:
    return Path(cfg.runtime_state_path)


def write_runtime_state(
    cfg: RuntimeStateConfig,
    *,
    bind_host: str,
    bind_port: int,
    pid: int | None = None,
    process_incarnation: object | None = None,
) -> dict[str, object]:
    process_pid = os.getpid() if pid is None else pid
    if isinstance(process_pid, bool) or not isinstance(process_pid, int):
        raise ValueError("remote runner runtime state pid is invalid")
    if process_pid <= 0:
        raise ValueError("remote runner runtime state pid is invalid")
    incarnation = (
        capture_linux_process_incarnation(pid=process_pid)
        if process_incarnation is None
        else require_linux_process_incarnation(process_incarnation)
    )
    if incarnation["pid"] != process_pid:
        raise ValueError(
            "remote runner runtime state pid does not match process incarnation"
        )
    state: dict[str, object] = {
        "service": cfg.service_name,
        "version": cfg.version,
        "pid": process_pid,
        "bindHost": bind_host,
        "bindPort": int(bind_port),
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "processIncarnation": incarnation,
        "runnerProtocol": build_runner_protocol_runtime_self_attestation(),
    }
    path = get_runtime_state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    try:
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        directory_fd = None
    if directory_fd is not None:
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return state


__all__ = ["get_runtime_state_path", "write_runtime_state"]
