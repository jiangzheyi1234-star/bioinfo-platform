"""Exact runtime self-attestation for the current remote-runner protocol.

The payload proves only that a responding binary reports the exact protocol
contract expected by this control plane. It is not an authenticator and does
not establish process identity, liveness, exclusive ownership, or death.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hmac

from .runner_protocol import (
    RUNNER_PROTOCOL_DATABASE_SCHEMA_VERSION,
    RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA,
    RUNNER_PROTOCOL_VERSION,
    build_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)


CURRENT_RUNNER_PROTOCOL_FINGERPRINT = runner_protocol_descriptor_fingerprint(
    build_runner_protocol_descriptor()
)

_ATTESTATION_FIELDS = frozenset(
    {
        "automaticRecoveryEnabled",
        "coverageComplete",
        "databaseSchemaVersion",
        "protocolFingerprint",
        "protocolVersion",
        "schemaVersion",
    }
)


def require_current_runner_protocol_expectation(
    protocol_version: object,
    protocol_fingerprint: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> None:
    """Require an explicit, exact control-plane protocol expectation."""

    if not isinstance(protocol_version, str) or not protocol_version:
        raise make_error(
            "REMOTE_RUNNER_PROTOCOL_EXPECTATION_MISSING: runner_protocol_version"
        )
    if protocol_version != RUNNER_PROTOCOL_VERSION:
        raise make_error(
            "REMOTE_RUNNER_PROTOCOL_EXPECTATION_MISMATCH: runner_protocol_version"
        )
    if not isinstance(protocol_fingerprint, str) or not protocol_fingerprint:
        raise make_error(
            "REMOTE_RUNNER_PROTOCOL_EXPECTATION_MISSING: runner_protocol_fingerprint"
        )
    if not hmac.compare_digest(
        protocol_fingerprint,
        CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
    ):
        raise make_error(
            "REMOTE_RUNNER_PROTOCOL_EXPECTATION_MISMATCH: runner_protocol_fingerprint"
        )


def build_runner_protocol_runtime_self_attestation() -> dict[str, object]:
    """Build the exact self-reported protocol payload for this binary."""

    descriptor = build_runner_protocol_descriptor()
    coverage = descriptor["coverage"]
    if not isinstance(coverage, dict):  # pragma: no cover - descriptor invariant.
        raise RuntimeError("runner protocol descriptor coverage is invalid")
    return {
        "automaticRecoveryEnabled": coverage["automaticRecoveryEnabled"],
        "coverageComplete": coverage["coverageComplete"],
        "databaseSchemaVersion": RUNNER_PROTOCOL_DATABASE_SCHEMA_VERSION,
        "protocolFingerprint": CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
        "protocolVersion": RUNNER_PROTOCOL_VERSION,
        "schemaVersion": RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA,
    }


def require_runner_protocol_runtime_self_attestation(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate and normalize the exact current runtime self-attestation."""

    if not isinstance(payload, Mapping):
        raise make_error("remote runner runtime protocol self-attestation must be an object")
    if frozenset(payload.keys()) != _ATTESTATION_FIELDS:
        raise make_error(
            "remote runner runtime protocol self-attestation fields must match exactly"
        )
    expected = build_runner_protocol_runtime_self_attestation()
    for field in (
        "schemaVersion",
        "protocolVersion",
        "protocolFingerprint",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not hmac.compare_digest(
            value,
            str(expected[field]),
        ):
            raise make_error(
                f"remote runner runtime protocol self-attestation {field} is invalid"
            )
    database_schema_version = payload.get("databaseSchemaVersion")
    if (
        isinstance(database_schema_version, bool)
        or not isinstance(database_schema_version, int)
        or database_schema_version != expected["databaseSchemaVersion"]
    ):
        raise make_error(
            "remote runner runtime protocol self-attestation databaseSchemaVersion is invalid"
        )
    for field in ("coverageComplete", "automaticRecoveryEnabled"):
        value = payload.get(field)
        if not isinstance(value, bool) or value is not expected[field]:
            raise make_error(
                f"remote runner runtime protocol self-attestation {field} is invalid"
            )
    return expected


__all__ = [
    "CURRENT_RUNNER_PROTOCOL_FINGERPRINT",
    "RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA",
    "build_runner_protocol_runtime_self_attestation",
    "require_current_runner_protocol_expectation",
    "require_runner_protocol_runtime_self_attestation",
]
