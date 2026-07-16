"""Exact Linux procfs evidence for one process incarnation.

The tuple ``(bootId, pid, procStartTicks)`` detects a changed incarnation when
a reused PID has different start ticks, and rejects state carried across a
reboot. It is point-in-time evidence only: it does not prove liveness, listener
ownership, exclusivity, or process death.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import re


LINUX_PROCESS_INCARNATION_SCHEMA = "h2ometa.linux-process-incarnation.v1"
LINUX_PROCESS_INCARNATION_EVIDENCE_PROFILE = (
    "linux-procfs-boot-id-pid-starttime-v1"
)

_BOOT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_PROCESS_INCARNATION_FIELDS = frozenset(
    {
        "bootId",
        "evidenceProfile",
        "pid",
        "procStartTicks",
        "schemaVersion",
    }
)


def build_linux_process_incarnation(
    *,
    boot_id: object,
    pid: object,
    proc_start_ticks: object,
) -> dict[str, object]:
    """Build and validate the exact current procfs evidence payload."""

    return require_linux_process_incarnation(
        {
            "bootId": boot_id,
            "evidenceProfile": LINUX_PROCESS_INCARNATION_EVIDENCE_PROFILE,
            "pid": pid,
            "procStartTicks": proc_start_ticks,
            "schemaVersion": LINUX_PROCESS_INCARNATION_SCHEMA,
        }
    )


def require_linux_process_incarnation(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate exact procfs incarnation evidence and return a detached copy."""

    if not isinstance(payload, Mapping):
        raise make_error("linux process incarnation must be an object")
    if frozenset(payload.keys()) != _PROCESS_INCARNATION_FIELDS:
        raise make_error("linux process incarnation fields must match exactly")

    schema_version = payload.get("schemaVersion")
    if (
        not isinstance(schema_version, str)
        or schema_version != LINUX_PROCESS_INCARNATION_SCHEMA
    ):
        raise make_error("linux process incarnation schemaVersion is invalid")
    evidence_profile = payload.get("evidenceProfile")
    if (
        not isinstance(evidence_profile, str)
        or evidence_profile != LINUX_PROCESS_INCARNATION_EVIDENCE_PROFILE
    ):
        raise make_error("linux process incarnation evidenceProfile is invalid")

    boot_id = payload.get("bootId")
    if not isinstance(boot_id, str) or not _BOOT_ID_PATTERN.fullmatch(boot_id):
        raise make_error("linux process incarnation bootId is invalid")
    pid = _require_positive_integer(payload.get("pid"), "pid", make_error)
    proc_start_ticks = _require_positive_integer(
        payload.get("procStartTicks"),
        "procStartTicks",
        make_error,
    )
    return {
        "bootId": boot_id,
        "evidenceProfile": evidence_profile,
        "pid": pid,
        "procStartTicks": proc_start_ticks,
        "schemaVersion": schema_version,
    }


def parse_proc_stat_start_ticks(raw: str, *, expected_pid: int) -> int:
    """Parse field 22 from ``/proc/<pid>/stat`` without splitting ``comm``."""

    if isinstance(expected_pid, bool) or not isinstance(expected_pid, int):
        raise ValueError("invalid expected proc stat pid")
    if expected_pid <= 0:
        raise ValueError("invalid expected proc stat pid")
    if not isinstance(raw, str):
        raise ValueError("invalid proc stat")
    try:
        stat_pid = int(raw.split(" ", 1)[0])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid proc stat pid") from exc
    if stat_pid != expected_pid:
        raise ValueError("proc stat pid mismatch")
    expected_prefix = f"{expected_pid} ("
    if not raw.startswith(expected_prefix):
        raise ValueError("invalid proc stat")
    closing_paren = raw.rfind(") ")
    if closing_paren < len(expected_prefix):
        raise ValueError("invalid proc stat")
    fields_after_comm = raw[closing_paren + 2 :].strip().split()
    if len(fields_after_comm) <= 19:
        raise ValueError("invalid proc stat")
    start_ticks_text = fields_after_comm[19]
    if not start_ticks_text.isascii() or not start_ticks_text.isdecimal():
        raise ValueError("invalid proc start ticks")
    try:
        start_ticks = int(start_ticks_text)
    except ValueError as exc:
        raise ValueError("invalid proc start ticks") from exc
    if start_ticks <= 0 or start_ticks_text != str(start_ticks):
        raise ValueError("invalid proc start ticks")
    return start_ticks


def _require_positive_integer(
    value: object,
    field: str,
    make_error: Callable[[str], Exception],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise make_error(f"linux process incarnation {field} is invalid")
    return value


__all__ = [
    "LINUX_PROCESS_INCARNATION_EVIDENCE_PROFILE",
    "LINUX_PROCESS_INCARNATION_SCHEMA",
    "build_linux_process_incarnation",
    "parse_proc_stat_start_ticks",
    "require_linux_process_incarnation",
]
