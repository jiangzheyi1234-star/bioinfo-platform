from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from apps.remote_runner.sqlite_migrations import CURRENT_SCHEMA_VERSION
from apps.remote_runner.tool_prepare_process_marker import (
    TOOL_PREPARE_PROCESS_MARKER_SCHEMA,
)
from core.contracts.runner_protocol import (
    RUNNER_PROTOCOL_CAPABILITIES,
    RUNNER_PROTOCOL_COVERED_WRITER_SCOPES,
    RUNNER_PROTOCOL_DATABASE_SCHEMA_VERSION,
    RUNNER_PROTOCOL_DESCRIPTOR_SCHEMA,
    RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA,
    RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SURFACES,
    RUNNER_PROTOCOL_TOOL_PREPARE_PROCESS_MARKER_SCHEMA,
    RUNNER_PROTOCOL_VERSION,
    RUNNER_PROTOCOL_WRITER_SCOPES,
    build_runner_protocol_descriptor,
    require_runner_protocol_descriptor,
    runner_protocol_descriptor_canonical_json,
    runner_protocol_descriptor_fingerprint,
)


def test_runner_protocol_database_schema_version_tracks_migration_contract() -> None:
    assert RUNNER_PROTOCOL_DATABASE_SCHEMA_VERSION == CURRENT_SCHEMA_VERSION


def test_runner_protocol_process_marker_schema_tracks_tool_prepare_contract() -> None:
    assert (
        RUNNER_PROTOCOL_TOOL_PREPARE_PROCESS_MARKER_SCHEMA
        == TOOL_PREPARE_PROCESS_MARKER_SCHEMA
    )


def test_build_runner_protocol_descriptor_declares_exact_current_coverage() -> None:
    descriptor = build_runner_protocol_descriptor()

    assert descriptor == {
        "capabilities": [
            "artifact-exact-protocol-descriptor-v1",
            "execution-lifecycle-guard-v1",
            "runtime-self-attestation-v1",
            "tool-prepare-process-evidence-fencing-v1",
        ],
        "coverage": {
            "automaticRecoveryEnabled": False,
            "coverageComplete": False,
            "coveredWriterScopes": ["tool-prepare-worker"],
            "runtimeSelfAttestationSchema": (
                "h2ometa.runner-protocol-runtime-self-attestation.v1"
            ),
            "runtimeSelfAttestationSurfaces": [
                "runtime-state",
                "health-startup",
                "health-live",
                "health-ready",
                "health-meta",
            ],
            "toolPrepareProcessMarkerSchema": (
                "h2ometa.tool-prepare-process-marker.v1"
            ),
        },
        "databaseSchemaVersion": 18,
        "protocolVersion": "runner-protocol.v2",
        "schemaVersion": "h2ometa.runner-protocol-descriptor.v2",
        "writerScopes": [
            "artifact-lifecycle-controller",
            "run-worker",
            "tool-prepare-worker",
            "workflow-trigger-readiness-watcher",
            "workflow-trigger-scheduler",
        ],
    }
    assert tuple(descriptor["capabilities"]) == RUNNER_PROTOCOL_CAPABILITIES
    assert tuple(descriptor["writerScopes"]) == RUNNER_PROTOCOL_WRITER_SCOPES
    assert descriptor["coverage"] == {
        "automaticRecoveryEnabled": False,
        "coverageComplete": False,
        "coveredWriterScopes": list(RUNNER_PROTOCOL_COVERED_WRITER_SCOPES),
        "runtimeSelfAttestationSchema": (
            RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA
        ),
        "runtimeSelfAttestationSurfaces": list(
            RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SURFACES
        ),
        "toolPrepareProcessMarkerSchema": (
            RUNNER_PROTOCOL_TOOL_PREPARE_PROCESS_MARKER_SCHEMA
        ),
    }
    assert descriptor["databaseSchemaVersion"] == RUNNER_PROTOCOL_DATABASE_SCHEMA_VERSION
    assert descriptor["protocolVersion"] == RUNNER_PROTOCOL_VERSION
    assert descriptor["schemaVersion"] == RUNNER_PROTOCOL_DESCRIPTOR_SCHEMA


def test_build_runner_protocol_descriptor_returns_detached_nested_values() -> None:
    first = build_runner_protocol_descriptor()
    second = build_runner_protocol_descriptor()

    first["capabilities"].append("not-real")
    first["coverage"]["coveredWriterScopes"].append("not-covered")

    assert second == build_runner_protocol_descriptor()


def test_require_runner_protocol_descriptor_returns_normalized_detached_copy() -> None:
    descriptor = build_runner_protocol_descriptor()

    normalized = require_runner_protocol_descriptor(descriptor)

    assert normalized == descriptor
    assert normalized is not descriptor
    assert normalized["capabilities"] is not descriptor["capabilities"]
    assert normalized["coverage"] is not descriptor["coverage"]


@pytest.mark.parametrize(
    "field",
    [
        "capabilities",
        "coverage",
        "databaseSchemaVersion",
        "protocolVersion",
        "schemaVersion",
        "writerScopes",
    ],
)
def test_require_runner_protocol_descriptor_rejects_missing_top_level_fields(
    field: str,
) -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor.pop(field)

    with pytest.raises(ValueError, match="fields must match"):
        require_runner_protocol_descriptor(descriptor)


def test_require_runner_protocol_descriptor_rejects_unknown_fields() -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor["fingerprint"] = "sha256:not-embedded"

    with pytest.raises(ValueError, match="fields must match"):
        require_runner_protocol_descriptor(descriptor)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("schemaVersion", "h2ometa.runner-protocol-descriptor.v1"),
        ("protocolVersion", "runner-protocol.v1"),
        ("databaseSchemaVersion", 17),
        ("databaseSchemaVersion", True),
    ],
)
def test_require_runner_protocol_descriptor_rejects_wrong_fixed_values(
    field: str,
    replacement: object,
) -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor[field] = replacement

    with pytest.raises(ValueError, match=f"{field} is invalid"):
        require_runner_protocol_descriptor(descriptor)


@pytest.mark.parametrize("field", ["capabilities", "writerScopes"])
def test_require_runner_protocol_descriptor_rejects_non_lists(field: str) -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor[field] = tuple(descriptor[field])

    with pytest.raises(ValueError, match=f"{field} is invalid"):
        require_runner_protocol_descriptor(descriptor)


@pytest.mark.parametrize("field", ["capabilities", "writerScopes"])
def test_require_runner_protocol_descriptor_rejects_reordered_lists(field: str) -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor[field] = list(reversed(descriptor[field]))

    with pytest.raises(ValueError, match=f"{field} is invalid"):
        require_runner_protocol_descriptor(descriptor)


def test_require_runner_protocol_descriptor_rejects_incomplete_capabilities() -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor["capabilities"].pop()

    with pytest.raises(ValueError, match="capabilities is invalid"):
        require_runner_protocol_descriptor(descriptor)


def test_require_runner_protocol_descriptor_rejects_incomplete_writer_scope_universe() -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor["writerScopes"].remove("run-worker")

    with pytest.raises(ValueError, match="writerScopes is invalid"):
        require_runner_protocol_descriptor(descriptor)


def test_require_runner_protocol_descriptor_rejects_invalid_coverage_shape() -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor["coverage"]["unknown"] = False

    with pytest.raises(ValueError, match="coverage fields must match"):
        require_runner_protocol_descriptor(descriptor)


@pytest.mark.parametrize(
    "field",
    [
        "automaticRecoveryEnabled",
        "coverageComplete",
        "coveredWriterScopes",
        "runtimeSelfAttestationSchema",
        "runtimeSelfAttestationSurfaces",
        "toolPrepareProcessMarkerSchema",
    ],
)
def test_require_runner_protocol_descriptor_rejects_missing_coverage_fields(
    field: str,
) -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor["coverage"].pop(field)

    with pytest.raises(ValueError, match="coverage fields must match"):
        require_runner_protocol_descriptor(descriptor)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("automaticRecoveryEnabled", 0),
        ("automaticRecoveryEnabled", True),
        ("coverageComplete", 0),
        ("coverageComplete", True),
        ("coveredWriterScopes", []),
        ("coveredWriterScopes", ["tool-prepare"]),
        ("runtimeSelfAttestationSchema", "old"),
        ("runtimeSelfAttestationSurfaces", []),
        (
            "toolPrepareProcessMarkerSchema",
            "h2ometa.tool-prepare-process-marker.v2",
        ),
    ],
)
def test_require_runner_protocol_descriptor_rejects_inaccurate_coverage(
    field: str,
    replacement: object,
) -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor["coverage"][field] = replacement

    with pytest.raises(ValueError, match=field):
        require_runner_protocol_descriptor(descriptor)


def test_require_runner_protocol_descriptor_uses_requested_error_type() -> None:
    class ProtocolError(RuntimeError):
        pass

    with pytest.raises(ProtocolError, match="must be an object"):
        require_runner_protocol_descriptor([], make_error=ProtocolError)


def test_require_runner_protocol_descriptor_accepts_error_factory() -> None:
    class ProtocolError(RuntimeError):
        pass

    with pytest.raises(
        ProtocolError,
        match="wrapped: runner protocol descriptor must be an object",
    ):
        require_runner_protocol_descriptor(
            [],
            make_error=lambda message: ProtocolError(f"wrapped: {message}"),
        )


def test_runner_protocol_descriptor_canonical_json_is_stable_and_compact() -> None:
    descriptor = build_runner_protocol_descriptor()
    reordered = dict(reversed(tuple(descriptor.items())))

    canonical = runner_protocol_descriptor_canonical_json(reordered)

    assert canonical == json.dumps(
        descriptor,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert runner_protocol_descriptor_canonical_json(descriptor) == canonical


def test_runner_protocol_descriptor_fingerprint_is_domain_separated_and_stable() -> None:
    descriptor = build_runner_protocol_descriptor()
    canonical = runner_protocol_descriptor_canonical_json(descriptor)
    expected = hashlib.sha256(
        b"h2ometa.runner-protocol-descriptor.v2\x00" + canonical.encode("utf-8")
    ).hexdigest()

    assert runner_protocol_descriptor_fingerprint(descriptor) == f"sha256:{expected}"
    assert runner_protocol_descriptor_fingerprint(deepcopy(descriptor)) == (
        f"sha256:{expected}"
    )


def test_runner_protocol_descriptor_fingerprint_rejects_non_current_payloads() -> None:
    descriptor = build_runner_protocol_descriptor()
    descriptor["coverage"]["coverageComplete"] = True

    with pytest.raises(ValueError, match="coverageComplete"):
        runner_protocol_descriptor_fingerprint(descriptor)
