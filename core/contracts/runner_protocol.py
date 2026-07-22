"""Strict descriptor for the current remote-runner protocol.

The descriptor records exact writer coverage, immutable early process-owner
evidence, point-in-time procfs evidence, and a cooperating-process lifetime
fence. None of those surfaces proves listener ownership, process-tree
ownership, liveness, death, or systemd activation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
from typing import Any

from .linux_process_incarnation import LINUX_PROCESS_INCARNATION_SCHEMA
from .runner_process_lifetime import RUNNER_PROCESS_LIFETIME_LOCK_PROFILE
from .runner_process_owner import (
    RUNNER_PROCESS_OWNER_PROFILE,
    RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA,
    RUNNER_PROCESS_OWNER_SCHEMA,
)

RUNNER_PROTOCOL_DESCRIPTOR_SCHEMA = "h2ometa.runner-protocol-descriptor.v5"
RUNNER_PROTOCOL_VERSION = "runner-protocol.v5"
RUNNER_PROTOCOL_DATABASE_SCHEMA_VERSION = 22
RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA = (
    "h2ometa.runner-protocol-runtime-self-attestation.v1"
)
RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SURFACES = (
    "runtime-state",
    "health-startup",
    "health-live",
    "health-ready",
    "health-meta",
)
RUNNER_PROTOCOL_RUNTIME_PROCESS_INCARNATION_SCHEMA = LINUX_PROCESS_INCARNATION_SCHEMA
RUNNER_PROTOCOL_RUNTIME_PROCESS_INCARNATION_SURFACES = ("runtime-state",)
RUNNER_PROTOCOL_PROCESS_LIFETIME_LOCK_PROFILE = RUNNER_PROCESS_LIFETIME_LOCK_PROFILE
RUNNER_PROTOCOL_PROCESS_OWNER_SCHEMA = RUNNER_PROCESS_OWNER_SCHEMA
RUNNER_PROTOCOL_PROCESS_OWNER_PROFILE = RUNNER_PROCESS_OWNER_PROFILE
RUNNER_PROTOCOL_PROCESS_OWNER_REFERENCE_SCHEMA = RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA
RUNNER_PROTOCOL_PROCESS_OWNER_SURFACES = (
    "runner-process-owner-record",
    "current-owner-reference",
    "runtime-state-reference",
)
RUNNER_PROTOCOL_TOOL_PREPARE_PROCESS_MARKER_SCHEMA = (
    "h2ometa.tool-prepare-process-marker.v1"
)

RUNNER_PROTOCOL_CAPABILITIES = (
    "artifact-exact-protocol-descriptor-v1",
    "early-process-owner-evidence-v1",
    "execution-lifecycle-guard-v1",
    "process-lifetime-flock-fence-v1",
    "runtime-process-incarnation-evidence-v1",
    "runtime-self-attestation-v1",
    "tool-prepare-process-evidence-fencing-v1",
)
RUNNER_PROTOCOL_WRITER_SCOPES = (
    "artifact-lifecycle-controller",
    "run-worker",
    "tool-prepare-worker",
    "workflow-trigger-readiness-watcher",
    "workflow-trigger-scheduler",
)
RUNNER_PROTOCOL_COVERED_WRITER_SCOPES = ("tool-prepare-worker",)

_DESCRIPTOR_FIELDS = frozenset(
    {
        "capabilities",
        "coverage",
        "databaseSchemaVersion",
        "protocolVersion",
        "schemaVersion",
        "writerScopes",
    }
)
_COVERAGE_FIELDS = frozenset(
    {
        "automaticRecoveryEnabled",
        "coverageComplete",
        "coveredWriterScopes",
        "processLifetimeLockProfile",
        "processOwnerProfile",
        "processOwnerReferenceSchema",
        "processOwnerSchema",
        "processOwnerSurfaces",
        "runtimeProcessIncarnationSchema",
        "runtimeProcessIncarnationSurfaces",
        "runtimeSelfAttestationSchema",
        "runtimeSelfAttestationSurfaces",
        "toolPrepareProcessMarkerSchema",
    }
)
_FINGERPRINT_DOMAIN = b"h2ometa.runner-protocol-descriptor.v5"


def build_runner_protocol_descriptor() -> dict[str, object]:
    """Build the exact protocol descriptor implemented by the current runner."""

    return {
        "capabilities": list(RUNNER_PROTOCOL_CAPABILITIES),
        "coverage": {
            "automaticRecoveryEnabled": False,
            "coverageComplete": False,
            "coveredWriterScopes": list(RUNNER_PROTOCOL_COVERED_WRITER_SCOPES),
            "processLifetimeLockProfile": (
                RUNNER_PROTOCOL_PROCESS_LIFETIME_LOCK_PROFILE
            ),
            "processOwnerProfile": RUNNER_PROTOCOL_PROCESS_OWNER_PROFILE,
            "processOwnerReferenceSchema": (
                RUNNER_PROTOCOL_PROCESS_OWNER_REFERENCE_SCHEMA
            ),
            "processOwnerSchema": RUNNER_PROTOCOL_PROCESS_OWNER_SCHEMA,
            "processOwnerSurfaces": list(RUNNER_PROTOCOL_PROCESS_OWNER_SURFACES),
            "runtimeProcessIncarnationSchema": (
                RUNNER_PROTOCOL_RUNTIME_PROCESS_INCARNATION_SCHEMA
            ),
            "runtimeProcessIncarnationSurfaces": list(
                RUNNER_PROTOCOL_RUNTIME_PROCESS_INCARNATION_SURFACES
            ),
            "runtimeSelfAttestationSchema": (
                RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA
            ),
            "runtimeSelfAttestationSurfaces": list(
                RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SURFACES
            ),
            "toolPrepareProcessMarkerSchema": (
                RUNNER_PROTOCOL_TOOL_PREPARE_PROCESS_MARKER_SCHEMA
            ),
        },
        "databaseSchemaVersion": RUNNER_PROTOCOL_DATABASE_SCHEMA_VERSION,
        "protocolVersion": RUNNER_PROTOCOL_VERSION,
        "schemaVersion": RUNNER_PROTOCOL_DESCRIPTOR_SCHEMA,
        "writerScopes": list(RUNNER_PROTOCOL_WRITER_SCOPES),
    }


def require_runner_protocol_descriptor(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate an exact descriptor and return a normalized, detached copy."""

    if not isinstance(payload, Mapping):
        raise make_error("runner protocol descriptor must be an object")
    _require_exact_fields(
        payload,
        expected=_DESCRIPTOR_FIELDS,
        context="runner protocol descriptor",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("schemaVersion"),
        expected=RUNNER_PROTOCOL_DESCRIPTOR_SCHEMA,
        field="schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        payload.get("protocolVersion"),
        expected=RUNNER_PROTOCOL_VERSION,
        field="protocolVersion",
        make_error=make_error,
    )
    _require_exact_integer(
        payload.get("databaseSchemaVersion"),
        expected=RUNNER_PROTOCOL_DATABASE_SCHEMA_VERSION,
        field="databaseSchemaVersion",
        make_error=make_error,
    )
    _require_exact_string_list(
        payload.get("capabilities"),
        expected=RUNNER_PROTOCOL_CAPABILITIES,
        field="capabilities",
        make_error=make_error,
    )
    _require_exact_string_list(
        payload.get("writerScopes"),
        expected=RUNNER_PROTOCOL_WRITER_SCOPES,
        field="writerScopes",
        make_error=make_error,
    )

    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping):
        raise make_error("runner protocol descriptor coverage must be an object")
    _require_exact_fields(
        coverage,
        expected=_COVERAGE_FIELDS,
        context="runner protocol descriptor coverage",
        make_error=make_error,
    )
    _require_exact_boolean(
        coverage.get("automaticRecoveryEnabled"),
        expected=False,
        field="coverage.automaticRecoveryEnabled",
        make_error=make_error,
    )
    _require_exact_boolean(
        coverage.get("coverageComplete"),
        expected=False,
        field="coverage.coverageComplete",
        make_error=make_error,
    )
    _require_exact_string_list(
        coverage.get("coveredWriterScopes"),
        expected=RUNNER_PROTOCOL_COVERED_WRITER_SCOPES,
        field="coverage.coveredWriterScopes",
        make_error=make_error,
    )
    _require_exact_string(
        coverage.get("processLifetimeLockProfile"),
        expected=RUNNER_PROTOCOL_PROCESS_LIFETIME_LOCK_PROFILE,
        field="coverage.processLifetimeLockProfile",
        make_error=make_error,
    )
    _require_exact_string(
        coverage.get("processOwnerProfile"),
        expected=RUNNER_PROTOCOL_PROCESS_OWNER_PROFILE,
        field="coverage.processOwnerProfile",
        make_error=make_error,
    )
    _require_exact_string(
        coverage.get("processOwnerReferenceSchema"),
        expected=RUNNER_PROTOCOL_PROCESS_OWNER_REFERENCE_SCHEMA,
        field="coverage.processOwnerReferenceSchema",
        make_error=make_error,
    )
    _require_exact_string(
        coverage.get("processOwnerSchema"),
        expected=RUNNER_PROTOCOL_PROCESS_OWNER_SCHEMA,
        field="coverage.processOwnerSchema",
        make_error=make_error,
    )
    _require_exact_string_list(
        coverage.get("processOwnerSurfaces"),
        expected=RUNNER_PROTOCOL_PROCESS_OWNER_SURFACES,
        field="coverage.processOwnerSurfaces",
        make_error=make_error,
    )
    _require_exact_string(
        coverage.get("runtimeProcessIncarnationSchema"),
        expected=RUNNER_PROTOCOL_RUNTIME_PROCESS_INCARNATION_SCHEMA,
        field="coverage.runtimeProcessIncarnationSchema",
        make_error=make_error,
    )
    _require_exact_string_list(
        coverage.get("runtimeProcessIncarnationSurfaces"),
        expected=RUNNER_PROTOCOL_RUNTIME_PROCESS_INCARNATION_SURFACES,
        field="coverage.runtimeProcessIncarnationSurfaces",
        make_error=make_error,
    )
    _require_exact_string(
        coverage.get("runtimeSelfAttestationSchema"),
        expected=RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA,
        field="coverage.runtimeSelfAttestationSchema",
        make_error=make_error,
    )
    _require_exact_string_list(
        coverage.get("runtimeSelfAttestationSurfaces"),
        expected=RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SURFACES,
        field="coverage.runtimeSelfAttestationSurfaces",
        make_error=make_error,
    )
    _require_exact_string(
        coverage.get("toolPrepareProcessMarkerSchema"),
        expected=RUNNER_PROTOCOL_TOOL_PREPARE_PROCESS_MARKER_SCHEMA,
        field="coverage.toolPrepareProcessMarkerSchema",
        make_error=make_error,
    )
    return build_runner_protocol_descriptor()


def runner_protocol_descriptor_canonical_json(payload: object) -> str:
    """Return the canonical JSON representation of a valid descriptor."""

    normalized = require_runner_protocol_descriptor(payload)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def runner_protocol_descriptor_fingerprint(payload: object) -> str:
    """Return a domain-separated digest of a valid canonical descriptor."""

    canonical_json = runner_protocol_descriptor_canonical_json(payload)
    digest = hashlib.sha256(
        _FINGERPRINT_DOMAIN + b"\x00" + canonical_json.encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _require_exact_fields(
    payload: Mapping[object, Any],
    *,
    expected: frozenset[str],
    context: str,
    make_error: Callable[[str], Exception],
) -> None:
    actual = frozenset(payload.keys())
    if actual != expected:
        raise make_error(f"{context} fields must match the current protocol exactly")


def _require_exact_string(
    value: object,
    *,
    expected: str,
    field: str,
    make_error: Callable[[str], Exception],
) -> None:
    if not isinstance(value, str) or value != expected:
        raise make_error(f"runner protocol descriptor {field} is invalid")


def _require_exact_integer(
    value: object,
    *,
    expected: int,
    field: str,
    make_error: Callable[[str], Exception],
) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise make_error(f"runner protocol descriptor {field} is invalid")


def _require_exact_boolean(
    value: object,
    *,
    expected: bool,
    field: str,
    make_error: Callable[[str], Exception],
) -> None:
    if not isinstance(value, bool) or value is not expected:
        raise make_error(f"runner protocol descriptor {field} is invalid")


def _require_exact_string_list(
    value: object,
    *,
    expected: tuple[str, ...],
    field: str,
    make_error: Callable[[str], Exception],
) -> None:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        or value != list(expected)
    ):
        raise make_error(f"runner protocol descriptor {field} is invalid")
