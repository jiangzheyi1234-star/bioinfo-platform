"""Capture dormant runner-side systemd invocation and cgroup evidence.

This module is intentionally not wired into startup.  It performs a bounded,
fail-closed read of the current process only and leaves correlation with
controller-issued systemd evidence to a higher-level activation transaction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path, PurePosixPath
import re

from core.contracts.linux_process_incarnation import (
    require_linux_process_incarnation,
)
from core.contracts.runner_systemd_self_observation import (
    build_runner_systemd_self_observation,
)


_INVOCATION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_UNIT_PATTERN = re.compile(r"^h2ometa-remote@[0-9a-f]{32}[.]service$")
_CONTROLLER_TOKEN_PATTERN = re.compile(r"^(?:name=)?[A-Za-z0-9_.-]+$")
_MAX_CGROUP_OUTPUT_BYTES = 64 * 1024
_MAX_CGROUP_LINE_BYTES = 8 * 1024
_MAX_CGROUP_PATH_BYTES = 4096


def parse_runner_systemd_cgroup_candidates(
    raw: object,
    *,
    systemd_unit: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> list[dict[str, object]]:
    """Parse exact v2 and legacy v1-systemd candidates from procfs cgroup data."""

    unit = _require_systemd_unit(systemd_unit, make_error=make_error)
    if not isinstance(raw, str) or not raw or _contains_surrogate(raw):
        raise make_error("remote runner procfs cgroup data is invalid")
    try:
        encoded = raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise make_error("remote runner procfs cgroup data is invalid") from exc
    if len(encoded) > _MAX_CGROUP_OUTPUT_BYTES or "\r" in raw:
        raise make_error("remote runner procfs cgroup data is invalid")
    if any(
        (ord(character) < 0x20 and character != "\n") or ord(character) == 0x7F
        for character in raw
    ):
        raise make_error("remote runner procfs cgroup data is invalid")

    lines = raw.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or any(not line for line in lines):
        raise make_error("remote runner procfs cgroup data is invalid")

    candidates: dict[str, dict[str, object]] = {}
    for line in lines:
        if len(line.encode("utf-8")) > _MAX_CGROUP_LINE_BYTES:
            raise make_error("remote runner procfs cgroup line is invalid")
        fields = line.split(":", 2)
        if len(fields) != 3:
            raise make_error("remote runner procfs cgroup line shape is invalid")
        hierarchy_text, controllers_text, path_text = fields
        hierarchy_id = _parse_canonical_nonnegative_integer(
            hierarchy_text,
            make_error=make_error,
        )
        controllers = _parse_controller_list(
            controllers_text,
            hierarchy_id=hierarchy_id,
            make_error=make_error,
        )
        version = _classify_candidate(
            hierarchy_id=hierarchy_id,
            controllers=controllers,
            make_error=make_error,
        )
        path = _require_safe_proc_cgroup_path(
            path_text,
            allow_root=version is None,
            make_error=make_error,
        )
        if version is None:
            continue
        if PurePosixPath(path).name != unit:
            raise make_error(
                "remote runner procfs cgroup candidate path does not match unit"
            )
        if version in candidates:
            raise make_error(
                "remote runner procfs cgroup candidate is duplicated or ambiguous"
            )
        candidates[version] = {
            "controllers": [] if version == "v2" else ["name=systemd"],
            "hierarchyId": hierarchy_id,
            "path": path,
            "version": version,
        }

    if not candidates:
        raise make_error("remote runner procfs cgroup candidate is unavailable")
    return [candidates[version] for version in ("v2", "v1") if version in candidates]


def capture_runner_systemd_self_observation(
    systemd_unit: object,
    process_incarnation: object,
    environ: Mapping[str, object] | None = None,
    proc_root: Path = Path("/proc"),
) -> dict[str, object]:
    """Capture systemd environment and cgroup evidence for this exact process."""

    try:
        unit = _require_systemd_unit(systemd_unit, make_error=ValueError)
        incarnation = require_linux_process_incarnation(process_incarnation)
        current_pid = os.getpid()
        if incarnation["pid"] != current_pid:
            raise ValueError(
                "remote runner process incarnation does not identify current process"
            )
        environment = os.environ if environ is None else environ
        if not isinstance(environment, Mapping):
            raise ValueError("remote runner systemd environment is invalid")
        invocation_id = _require_invocation_id(
            environment.get("INVOCATION_ID"),
        )
        _require_optional_systemd_exec_pid(
            environment,
            expected_pid=current_pid,
        )
        if not isinstance(proc_root, Path):
            raise ValueError("remote runner procfs root is invalid")
        cgroup_path = proc_root / str(current_pid) / "cgroup"
        with cgroup_path.open("rb") as handle:
            raw_bytes = handle.read(_MAX_CGROUP_OUTPUT_BYTES + 1)
        if len(raw_bytes) > _MAX_CGROUP_OUTPUT_BYTES:
            raise ValueError("remote runner procfs cgroup data is too large")
        raw = raw_bytes.decode("utf-8", errors="strict")
        candidates = parse_runner_systemd_cgroup_candidates(
            raw,
            systemd_unit=unit,
        )
        return build_runner_systemd_self_observation(
            invocation_id=invocation_id,
            unit=unit,
            process_incarnation=incarnation,
            cgroup_candidates=candidates,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError(
            "remote runner systemd self-observation is unavailable"
        ) from exc


def _require_systemd_unit(
    value: object,
    *,
    make_error: Callable[[str], Exception],
) -> str:
    if not isinstance(value, str) or _UNIT_PATTERN.fullmatch(value) is None:
        raise make_error("remote runner systemd unit is invalid")
    return value


def _require_invocation_id(value: object) -> str:
    if not isinstance(value, str) or _INVOCATION_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("remote runner systemd INVOCATION_ID is invalid")
    return value


def _require_optional_systemd_exec_pid(
    environment: Mapping[str, object],
    *,
    expected_pid: int,
) -> None:
    if "SYSTEMD_EXEC_PID" not in environment:
        return
    value = environment.get("SYSTEMD_EXEC_PID")
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or (len(value) > 1 and value.startswith("0"))
    ):
        raise ValueError("remote runner systemd SYSTEMD_EXEC_PID is invalid")
    parsed = int(value)
    if parsed <= 0 or parsed != expected_pid or str(parsed) != value:
        raise ValueError("remote runner systemd SYSTEMD_EXEC_PID does not match")


def _parse_canonical_nonnegative_integer(
    value: str,
    *,
    make_error: Callable[[str], Exception],
) -> int:
    if (
        not value
        or not value.isascii()
        or not value.isdecimal()
        or (len(value) > 1 and value.startswith("0"))
    ):
        raise make_error("remote runner procfs cgroup hierarchy ID is invalid")
    parsed = int(value)
    if parsed < 0 or str(parsed) != value:
        raise make_error("remote runner procfs cgroup hierarchy ID is invalid")
    return parsed


def _parse_controller_list(
    value: str,
    *,
    hierarchy_id: int,
    make_error: Callable[[str], Exception],
) -> list[str]:
    if hierarchy_id == 0:
        if value:
            raise make_error("remote runner procfs cgroup v2 controllers are invalid")
        return []
    if not value:
        raise make_error("remote runner procfs cgroup v1 controllers are invalid")
    controllers = value.split(",")
    if len(set(controllers)) != len(controllers) or any(
        _CONTROLLER_TOKEN_PATTERN.fullmatch(controller) is None
        for controller in controllers
    ):
        raise make_error("remote runner procfs cgroup controllers are invalid")
    return controllers


def _classify_candidate(
    *,
    hierarchy_id: int,
    controllers: list[str],
    make_error: Callable[[str], Exception],
) -> str | None:
    if hierarchy_id == 0:
        return "v2"
    if "name=systemd" not in controllers:
        return None
    if controllers != ["name=systemd"]:
        raise make_error(
            "remote runner procfs cgroup systemd controllers are ambiguous"
        )
    return "v1"


def _require_safe_proc_cgroup_path(
    value: str,
    *,
    allow_root: bool,
    make_error: Callable[[str], Exception],
) -> str:
    if (
        not value
        or value.startswith("//")
        or "\\" in value
        or _contains_surrogate(value)
        or "(deleted)" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise make_error("remote runner procfs cgroup path is invalid")
    try:
        encoded = value.encode("utf-8")
        path = PurePosixPath(value)
    except (UnicodeEncodeError, ValueError) as exc:
        raise make_error("remote runner procfs cgroup path is invalid") from exc
    if (
        len(encoded) > _MAX_CGROUP_PATH_BYTES
        or not path.is_absolute()
        or str(path) != value
        or any(part in {".", ".."} for part in path.parts)
        or (not allow_root and path == PurePosixPath("/"))
    ):
        raise make_error("remote runner procfs cgroup path is invalid")
    return value


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


__all__ = [
    "capture_runner_systemd_self_observation",
    "parse_runner_systemd_cgroup_candidates",
]
