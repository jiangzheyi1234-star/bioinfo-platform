"""Canonical process-incarnation evidence for governed Agent subprocesses."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .agent_contract_hash import agent_contract_hash
from .linux_process_incarnation import (
    LINUX_PROCESS_INCARNATION_SCHEMA,
    require_linux_process_incarnation,
)


AGENT_PROCESS_INCARNATION_HASH_DOMAIN = "agent-process-incarnation.v1"
AGENT_PROCESS_GATE_TOKEN_HASH_DOMAIN = "agent-process-gate-token.v1"
SYNTHETIC_PROCESS_INCARNATION_SCHEMA = "h2ometa.synthetic-process-incarnation.v1"
SYNTHETIC_PROCESS_INCARNATION_EVIDENCE_PROFILE = "synthetic-test-pid-nonce-v1"
WINDOWS_PROCESS_INCARNATION_SCHEMA = "h2ometa.windows-process-incarnation.v1"
WINDOWS_PROCESS_INCARNATION_EVIDENCE_PROFILE = (
    "windows-process-pid-creation-filetime-v1"
)

_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SYNTHETIC_FIELDS = frozenset({"evidenceProfile", "nonce", "pid", "schemaVersion"})
_WINDOWS_FIELDS = frozenset(
    {"creationTimeFiletime", "evidenceProfile", "pid", "schemaVersion"}
)
_WINDOWS_FILETIME_DECIMAL = re.compile(r"^[1-9][0-9]{0,19}$")
_MAX_SQLITE_INTEGER = (1 << 63) - 1
_MAX_WINDOWS_FILETIME = (1 << 64) - 1
_GATE_TOKEN_BYTES = 32


def build_synthetic_process_incarnation(
    *,
    pid: object,
    nonce: object,
) -> dict[str, object]:
    """Build deterministic non-production evidence for storage-level tests."""

    return require_agent_process_incarnation(
        {
            "evidenceProfile": SYNTHETIC_PROCESS_INCARNATION_EVIDENCE_PROFILE,
            "nonce": nonce,
            "pid": pid,
            "schemaVersion": SYNTHETIC_PROCESS_INCARNATION_SCHEMA,
        }
    )


def build_windows_process_incarnation(
    *,
    pid: object,
    creation_time_filetime: object,
) -> dict[str, object]:
    """Build Windows PID-reuse evidence captured from a live process handle."""

    return require_agent_process_incarnation(
        {
            "creationTimeFiletime": _canonical_windows_filetime_decimal(
                creation_time_filetime
            ),
            "evidenceProfile": WINDOWS_PROCESS_INCARNATION_EVIDENCE_PROFILE,
            "pid": pid,
            "schemaVersion": WINDOWS_PROCESS_INCARNATION_SCHEMA,
        }
    )


def require_agent_process_incarnation(payload: object) -> dict[str, object]:
    """Validate one exact supported evidence profile and return a detached copy."""

    if not isinstance(payload, Mapping):
        raise ValueError("AGENT_PROCESS_INCARNATION_OBJECT_REQUIRED")
    schema_version = payload.get("schemaVersion")
    if schema_version == LINUX_PROCESS_INCARNATION_SCHEMA:
        return require_linux_process_incarnation(
            payload,
            make_error=lambda _: ValueError("AGENT_PROCESS_INCARNATION_INVALID"),
        )
    if schema_version == SYNTHETIC_PROCESS_INCARNATION_SCHEMA:
        return _require_synthetic_incarnation(payload)
    if schema_version == WINDOWS_PROCESS_INCARNATION_SCHEMA:
        return _require_windows_incarnation(payload)
    raise ValueError("AGENT_PROCESS_INCARNATION_SCHEMA_UNSUPPORTED")


def agent_process_incarnation_hash(payload: object) -> str:
    """Hash canonical incarnation evidence under an Agent-specific domain."""

    normalized = require_agent_process_incarnation(payload)
    return agent_contract_hash(AGENT_PROCESS_INCARNATION_HASH_DOMAIN, normalized)


def agent_process_gate_token_hash(gate_token: bytes) -> str:
    """Hash one exact 256-bit in-memory gate credential."""

    if not isinstance(gate_token, bytes) or len(gate_token) != _GATE_TOKEN_BYTES:
        raise ValueError("AGENT_PROCESS_GATE_TOKEN_INVALID")
    return agent_contract_hash(
        AGENT_PROCESS_GATE_TOKEN_HASH_DOMAIN,
        {"tokenHex": gate_token.hex()},
    )


def _require_synthetic_incarnation(
    payload: Mapping[object, object],
) -> dict[str, object]:
    if frozenset(payload.keys()) != _SYNTHETIC_FIELDS:
        raise ValueError("AGENT_PROCESS_INCARNATION_FIELDS_INVALID")
    if payload.get("evidenceProfile") != SYNTHETIC_PROCESS_INCARNATION_EVIDENCE_PROFILE:
        raise ValueError("AGENT_PROCESS_INCARNATION_PROFILE_INVALID")
    pid = _positive_sqlite_integer(payload.get("pid"))
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or _LOWER_SHA256.fullmatch(nonce) is None:
        raise ValueError("AGENT_PROCESS_INCARNATION_NONCE_INVALID")
    return {
        "evidenceProfile": SYNTHETIC_PROCESS_INCARNATION_EVIDENCE_PROFILE,
        "nonce": nonce,
        "pid": pid,
        "schemaVersion": SYNTHETIC_PROCESS_INCARNATION_SCHEMA,
    }


def _require_windows_incarnation(
    payload: Mapping[object, object],
) -> dict[str, object]:
    if frozenset(payload.keys()) != _WINDOWS_FIELDS:
        raise ValueError("AGENT_PROCESS_INCARNATION_FIELDS_INVALID")
    if payload.get("evidenceProfile") != WINDOWS_PROCESS_INCARNATION_EVIDENCE_PROFILE:
        raise ValueError("AGENT_PROCESS_INCARNATION_PROFILE_INVALID")
    pid = _positive_sqlite_integer(payload.get("pid"))
    creation_time = _require_windows_filetime_decimal(
        payload.get("creationTimeFiletime")
    )
    return {
        "creationTimeFiletime": creation_time,
        "evidenceProfile": WINDOWS_PROCESS_INCARNATION_EVIDENCE_PROFILE,
        "pid": pid,
        "schemaVersion": WINDOWS_PROCESS_INCARNATION_SCHEMA,
    }


def _canonical_windows_filetime_decimal(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("AGENT_PROCESS_INCARNATION_CREATION_TIME_INVALID")
    if isinstance(value, int):
        if value <= 0 or value > _MAX_WINDOWS_FILETIME:
            raise ValueError("AGENT_PROCESS_INCARNATION_CREATION_TIME_INVALID")
        return str(value)
    return _require_windows_filetime_decimal(value)


def _require_windows_filetime_decimal(value: object) -> str:
    if not isinstance(value, str) or _WINDOWS_FILETIME_DECIMAL.fullmatch(value) is None:
        raise ValueError("AGENT_PROCESS_INCARNATION_CREATION_TIME_INVALID")
    if int(value) > _MAX_WINDOWS_FILETIME:
        raise ValueError("AGENT_PROCESS_INCARNATION_CREATION_TIME_INVALID")
    return value


def _positive_sqlite_integer(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > _MAX_SQLITE_INTEGER
    ):
        raise ValueError("AGENT_PROCESS_INCARNATION_PID_INVALID")
    return value


__all__ = [
    "AGENT_PROCESS_INCARNATION_HASH_DOMAIN",
    "AGENT_PROCESS_GATE_TOKEN_HASH_DOMAIN",
    "SYNTHETIC_PROCESS_INCARNATION_EVIDENCE_PROFILE",
    "SYNTHETIC_PROCESS_INCARNATION_SCHEMA",
    "WINDOWS_PROCESS_INCARNATION_EVIDENCE_PROFILE",
    "WINDOWS_PROCESS_INCARNATION_SCHEMA",
    "agent_process_incarnation_hash",
    "agent_process_gate_token_hash",
    "build_synthetic_process_incarnation",
    "build_windows_process_incarnation",
    "require_agent_process_incarnation",
]
