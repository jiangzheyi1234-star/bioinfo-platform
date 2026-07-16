from __future__ import annotations

from copy import deepcopy

import pytest

from core.contracts.runner_protocol import (
    RUNNER_PROTOCOL_VERSION,
    build_runner_protocol_descriptor,
)
from core.contracts.runner_protocol_runtime import (
    CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
    RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA,
    build_runner_protocol_runtime_self_attestation,
    require_current_runner_protocol_expectation,
    require_runner_protocol_runtime_self_attestation,
)


def test_runtime_self_attestation_tracks_exact_descriptor_without_overclaiming() -> None:
    descriptor = build_runner_protocol_descriptor()
    attestation = build_runner_protocol_runtime_self_attestation()

    assert attestation == {
        "automaticRecoveryEnabled": False,
        "coverageComplete": False,
        "databaseSchemaVersion": descriptor["databaseSchemaVersion"],
        "protocolFingerprint": CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
        "protocolVersion": descriptor["protocolVersion"],
        "schemaVersion": RUNNER_PROTOCOL_RUNTIME_SELF_ATTESTATION_SCHEMA,
    }


def test_runtime_self_attestation_returns_detached_values() -> None:
    first = build_runner_protocol_runtime_self_attestation()
    second = build_runner_protocol_runtime_self_attestation()

    first["protocolVersion"] = "mutated"

    assert second == build_runner_protocol_runtime_self_attestation()


def test_current_protocol_expectation_accepts_only_exact_explicit_values() -> None:
    attestation = build_runner_protocol_runtime_self_attestation()

    require_current_runner_protocol_expectation(
        attestation["protocolVersion"],
        attestation["protocolFingerprint"],
    )


@pytest.mark.parametrize(
    ("version", "fingerprint", "message"),
    [
        ("", CURRENT_RUNNER_PROTOCOL_FINGERPRINT, "EXPECTATION_MISSING.*version"),
        (None, CURRENT_RUNNER_PROTOCOL_FINGERPRINT, "EXPECTATION_MISSING.*version"),
        ("runner-protocol.v0", CURRENT_RUNNER_PROTOCOL_FINGERPRINT, "EXPECTATION_MISMATCH.*version"),
        (RUNNER_PROTOCOL_VERSION, "", "EXPECTATION_MISSING.*fingerprint"),
        (RUNNER_PROTOCOL_VERSION, None, "EXPECTATION_MISSING.*fingerprint"),
        (RUNNER_PROTOCOL_VERSION, "sha256:" + "0" * 64, "EXPECTATION_MISMATCH.*fingerprint"),
    ],
)
def test_current_protocol_expectation_rejects_missing_or_drifted_values(
    version: object,
    fingerprint: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        require_current_runner_protocol_expectation(version, fingerprint)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.pop("protocolVersion"), "fields must match exactly"),
        (lambda payload: payload.__setitem__("unknown", True), "fields must match exactly"),
        (lambda payload: payload.__setitem__("schemaVersion", "old"), "schemaVersion is invalid"),
        (lambda payload: payload.__setitem__("protocolVersion", "old"), "protocolVersion is invalid"),
        (
            lambda payload: payload.__setitem__("protocolFingerprint", "sha256:" + "0" * 64),
            "protocolFingerprint is invalid",
        ),
        (lambda payload: payload.__setitem__("databaseSchemaVersion", True), "databaseSchemaVersion is invalid"),
        (lambda payload: payload.__setitem__("databaseSchemaVersion", 17), "databaseSchemaVersion is invalid"),
        (lambda payload: payload.__setitem__("coverageComplete", True), "coverageComplete is invalid"),
        (
            lambda payload: payload.__setitem__("automaticRecoveryEnabled", True),
            "automaticRecoveryEnabled is invalid",
        ),
    ],
)
def test_runtime_self_attestation_rejects_non_current_payloads(mutation, message: str) -> None:
    payload = deepcopy(build_runner_protocol_runtime_self_attestation())
    mutation(payload)

    with pytest.raises(ValueError, match=message):
        require_runner_protocol_runtime_self_attestation(payload)


def test_runtime_self_attestation_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        require_runner_protocol_runtime_self_attestation([])


def test_runtime_contract_uses_requested_error_type() -> None:
    class ProtocolError(RuntimeError):
        pass

    with pytest.raises(ProtocolError, match="must be an object"):
        require_runner_protocol_runtime_self_attestation(
            None,
            make_error=ProtocolError,
        )
