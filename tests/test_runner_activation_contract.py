from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from core.contracts.runner_activation import (
    RUNNER_ACTIVATION_EVIDENCE_SCHEMA,
    RUNNER_ACTIVATION_GENERATION_SCHEMA,
    RUNNER_ACTIVATION_GUARD_OWNER_TEMPLATE,
    RUNNER_ACTIVATION_OPERATIONS,
    RUNNER_ACTIVATION_SERVICE,
    RUNNER_ACTIVATION_TARGET_SCHEMA,
    RUNNER_ACTIVATION_UNIT_TEMPLATE,
    RUNNER_ACTIVATION_UNIT_TEMPLATE_FILENAME,
    require_runner_activation_generation,
    require_runner_activation_target,
    runner_activation_generation_canonical_json,
    runner_activation_generation_fingerprint,
    runner_activation_target_canonical_json,
    runner_activation_target_fingerprint,
)
from core.contracts.runner_activation_evidence import (
    build_empty_runner_activation_evidence,
    require_runner_activation_evidence,
)
from tests.helpers.runner_activation_contract import (
    ACTIVATION_ID,
    GENERATION_ID,
    ROOT,
    TOKEN_GENERATION_ID,
    generation,
    generation_root,
    target,
)


def test_public_activation_target_contract_constants_are_exact() -> None:
    assert RUNNER_ACTIVATION_GENERATION_SCHEMA == (
        "h2ometa.runner-activation-generation.v1"
    )
    assert RUNNER_ACTIVATION_TARGET_SCHEMA == ("h2ometa.runner-activation-target.v1")
    assert RUNNER_ACTIVATION_EVIDENCE_SCHEMA == (
        "h2ometa.runner-activation-evidence.v1"
    )
    assert RUNNER_ACTIVATION_SERVICE == "h2ometa-remote"
    assert RUNNER_ACTIVATION_UNIT_TEMPLATE == ("h2ometa-remote@{activation_id}.service")
    assert RUNNER_ACTIVATION_UNIT_TEMPLATE_FILENAME == ("h2ometa-remote@.service")
    assert RUNNER_ACTIVATION_GUARD_OWNER_TEMPLATE == (
        "h2ometa-remote:{operation}:{activation_id}"
    )
    assert RUNNER_ACTIVATION_OPERATIONS == (
        "install",
        "upgrade",
        "token_rotation",
        "repair",
        "rollback",
    )


def test_generation_is_exact_detached_and_contains_no_token_secret() -> None:
    payload = generation()
    normalized = require_runner_activation_generation(payload)

    assert normalized == payload
    assert normalized is not payload
    assert normalized == {
        "configFingerprint": "sha256:" + "2" * 64,
        "configPath": f"{generation_root()}/runner.json",
        "generationId": GENERATION_ID,
        "profileFingerprint": "sha256:" + "3" * 64,
        "profilePath": f"{generation_root()}/profile.v9+.yaml",
        "protocolFingerprint": "sha256:" + "4" * 64,
        "protocolVersion": "runner-protocol.v6",
        "releaseArtifactSha256": "sha256:" + "1" * 64,
        "releasePath": f"{ROOT}/releases/0.2.0-control-plane",
        "runtimeConfigFingerprint": "sha256:" + "6" * 64,
        "schemaVersion": RUNNER_ACTIVATION_GENERATION_SCHEMA,
        "service": "h2ometa-remote",
        "systemdUnitTemplateFingerprint": "sha256:" + "5" * 64,
        "tokenGenerationId": TOKEN_GENERATION_ID,
    }
    serialized = runner_activation_generation_canonical_json(payload)
    assert "tokenGenerationId" in serialized
    assert '"token"' not in serialized.lower()

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_generation({**payload, "token": "secret-value"})


def test_generation_binds_credential_free_config_and_unit_template() -> None:
    baseline = generation()
    runtime_drift = generation(runtime_config_fingerprint="sha256:" + "9" * 64)
    unit_drift = generation(unit_fingerprint="sha256:" + "8" * 64)

    assert runner_activation_generation_fingerprint(runtime_drift) != (
        runner_activation_generation_fingerprint(baseline)
    )
    assert runner_activation_generation_fingerprint(unit_drift) != (
        runner_activation_generation_fingerprint(baseline)
    )


def test_generation_canonical_json_and_fingerprint_are_domain_separated() -> None:
    canonical = runner_activation_generation_canonical_json(generation())
    assert canonical == json.dumps(
        generation(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    expected = hashlib.sha256(
        RUNNER_ACTIVATION_GENERATION_SCHEMA.encode("ascii")
        + b"\x00"
        + canonical.encode("utf-8")
    ).hexdigest()
    assert runner_activation_generation_fingerprint(generation()) == (
        f"sha256:{expected}"
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("generationId", "A" * 32, "generationId"),
        ("generationId", "a" * 31, "generationId"),
        ("tokenGenerationId", GENERATION_ID, "must be distinct"),
        ("releaseArtifactSha256", "1" * 64, "releaseArtifactSha256"),
        ("configFingerprint", "sha256:" + "G" * 64, "configFingerprint"),
        ("runtimeConfigFingerprint", "sha256:bad", "runtimeConfigFingerprint"),
        (
            "systemdUnitTemplateFingerprint",
            "sha256:bad",
            "systemdUnitTemplateFingerprint",
        ),
        ("protocolVersion", "runner-protocol.v0", "protocolVersion"),
        ("service", "other-runner", "service"),
    ],
)
def test_generation_rejects_invalid_identity_and_digest_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = generation()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        require_runner_activation_generation(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("releasePath", "relative/releases/0.2.0"),
        ("releasePath", f"{ROOT}//releases/0.2.0"),
        ("releasePath", "//home/runner/.h2ometa/runner/releases/0.2.0"),
        ("releasePath", f"{ROOT}/releases/../0.2.0"),
        ("releasePath", f"{ROOT}\\releases\\0.2.0"),
        ("releasePath", "/" + "é" * 3000),
        ("releasePath", f"{ROOT}/releases/bad\x7fversion"),
        ("releasePath", f"{ROOT}/versions/0.2.0"),
        ("configPath", f"{ROOT}/shared/config/runner.json"),
        ("configPath", f"{generation_root()}/other.json"),
        ("configPath", f"{generation_root()}/runner.json/"),
        ("profilePath", f"{generation_root()}/other.yaml"),
        ("profilePath", f"{generation_root()}/prof\nile.yaml"),
    ],
)
def test_generation_requires_canonical_immutable_posix_layout(
    field: str,
    value: str,
) -> None:
    payload = generation()
    payload[field] = value

    with pytest.raises(ValueError, match=field):
        require_runner_activation_generation(payload)


def test_target_binds_operation_guard_owner_and_unique_unit() -> None:
    selected_generation = generation()
    payload = target(selected_generation=selected_generation)
    normalized = require_runner_activation_target(payload)

    assert normalized == payload
    assert normalized is not payload
    assert normalized["generation"] is not selected_generation
    assert normalized["activationId"] == ACTIVATION_ID
    assert normalized["operation"] == "install"
    assert normalized["lifecycleGuardOwner"] == (
        f"h2ometa-remote:install:{ACTIVATION_ID}"
    )
    assert normalized["systemdUnit"] == (f"h2ometa-remote@{ACTIVATION_ID}.service")
    assert normalized["systemdUnitTemplatePath"] == (
        "/home/runner/.config/systemd/user/h2ometa-remote@.service"
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("operation", "deploy", "operation"),
        ("systemdUnit", "h2ometa-remote.service", "systemdUnit"),
        (
            "systemdUnit",
            "h2ometa-remote@" + "f" * 32 + ".service",
            "systemdUnit",
        ),
        (
            "lifecycleGuardOwner",
            "h2ometa-remote:upgrade:" + ACTIVATION_ID,
            "lifecycleGuardOwner",
        ),
        (
            "systemdUnitTemplatePath",
            "/etc/systemd/system/h2ometa-remote@.service",
            "systemdUnitTemplatePath",
        ),
        (
            "systemdUnitTemplatePath",
            f"/home/runner/.config/systemd/user/h2ometa-remote@{ACTIVATION_ID}.service",
            "systemdUnitTemplatePath",
        ),
        ("currentLinkPath", f"{ROOT}/active", "currentLinkPath"),
        (
            "currentLinkTarget",
            f"{ROOT}/releases/another-release",
            "currentLinkTarget",
        ),
    ],
)
def test_target_rejects_drifted_operation_guard_or_paths(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = target()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        require_runner_activation_target(payload)


def test_target_requires_activation_id_distinct_from_generation_ids() -> None:
    for conflicting_id in (GENERATION_ID, TOKEN_GENERATION_ID):
        payload = target()
        payload["activationId"] = conflicting_id
        payload["lifecycleGuardOwner"] = f"h2ometa-remote:install:{conflicting_id}"
        payload["systemdUnit"] = f"h2ometa-remote@{conflicting_id}.service"
        with pytest.raises(ValueError, match="must be distinct"):
            require_runner_activation_target(payload)


def test_target_canonical_fingerprint_binds_nested_generation() -> None:
    payload = target()
    canonical = runner_activation_target_canonical_json(payload)
    fingerprint = runner_activation_target_fingerprint(payload)
    assert canonical == json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert len(fingerprint) == 71

    drifted = deepcopy(payload)
    drifted["generation"]["runtimeConfigFingerprint"] = "sha256:" + "9" * 64
    assert runner_activation_target_fingerprint(drifted) != fingerprint


def test_evidence_contract_is_exact_and_secret_free() -> None:
    empty = build_empty_runner_activation_evidence()
    assert require_runner_activation_evidence(empty) == empty
    assert empty == {
        "activationVerificationFingerprint": "",
        "authenticatedReadinessFingerprint": "",
        "invocationReservationFingerprint": "",
        "lifecycleGuardReleaseFingerprint": "",
        "processOwnerFingerprint": "",
        "schemaVersion": RUNNER_ACTIVATION_EVIDENCE_SCHEMA,
        "systemdObservationFingerprint": "",
    }
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_evidence(
            {**empty, "authorizationHeader": "Bearer secret"}
        )
