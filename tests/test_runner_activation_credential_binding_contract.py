from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
from types import MappingProxyType

import pytest

from core.contracts.runner_activation_keyring import (
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_ALGORITHM,
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_DESCRIPTOR_SCHEMA,
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES,
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_PURPOSE,
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY,
    RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_STORAGE_KIND,
    RUNNER_ACTIVATION_TOKEN_REF_PREFIX,
    RunnerActivationGenerationCredentialBinding,
    build_runner_activation_config_integrity_key_descriptor,
    build_runner_activation_installation,
    build_runner_activation_token_ref,
    require_runner_activation_config_integrity_key_descriptor,
    require_runner_activation_config_integrity_key_material,
    require_runner_activation_generation_credential_binding,
    runner_activation_config_integrity_key_descriptor_canonical_json,
    runner_activation_config_integrity_key_descriptor_fingerprint,
    runner_activation_config_integrity_key_path,
    runner_activation_installation_fingerprint,
    runner_activation_token_ref_fingerprint,
)
from core.contracts.runner_activation_target import (
    runner_activation_generation_fingerprint,
)
from tests.helpers.runner_activation_contract import ROOT, generation


INSTALLATION_ID = "1" * 32
OTHER_INSTALLATION_ID = "2" * 32
TOKEN_GENERATION_ID = "3" * 32
OTHER_TOKEN_GENERATION_ID = "4" * 32
CONFIG_INTEGRITY_KEY_ID = "5" * 32
OTHER_CONFIG_INTEGRITY_KEY_ID = "6" * 32
SECRET_SENTINEL = "credential-material-must-never-appear"


class CredentialBindingContractError(Exception):
    pass


def _installation(
    *,
    installation_id: str = INSTALLATION_ID,
    runner_root: str = ROOT,
) -> dict[str, object]:
    return build_runner_activation_installation(
        runner_installation_id=installation_id,
        runner_root=runner_root,
    )


def _token_ref(
    installation: object | None = None,
    *,
    token_generation_id: str = TOKEN_GENERATION_ID,
) -> str:
    return build_runner_activation_token_ref(
        installation=_installation() if installation is None else installation,
        token_generation_id=token_generation_id,
    )


def _descriptor(
    installation: object | None = None,
    *,
    config_integrity_key_id: str = CONFIG_INTEGRITY_KEY_ID,
) -> dict[str, object]:
    return build_runner_activation_config_integrity_key_descriptor(
        installation=_installation() if installation is None else installation,
        config_integrity_key_id=config_integrity_key_id,
    )


def _domain_fingerprint(schema: str, canonical: str) -> str:
    digest = hashlib.sha256(
        schema.encode("ascii") + b"\x00" + canonical.encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def test_config_integrity_descriptor_is_exact_remote_private_file_identity() -> None:
    installation = _installation()
    descriptor = _descriptor(installation)
    expected_path = (
        f"{ROOT}/{RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_RELATIVE_DIRECTORY}/"
        f"{CONFIG_INTEGRITY_KEY_ID}.key"
    )
    expected = {
        "algorithm": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_ALGORITHM,
        "configBlobIntegrityKeyId": CONFIG_INTEGRITY_KEY_ID,
        "keyLengthBytes": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES,
        "materialPath": expected_path,
        "purpose": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_PURPOSE,
        "runnerInstallationId": INSTALLATION_ID,
        "schemaVersion": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_DESCRIPTOR_SCHEMA,
        "service": "h2ometa-remote",
        "storageKind": RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_STORAGE_KIND,
    }

    assert RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_ALGORITHM == "hmac-sha256"
    assert RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_LENGTH_BYTES == 32
    assert RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_STORAGE_KIND == "remote-private-file"
    assert RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_PURPOSE == "config-blob-integrity"
    assert descriptor == expected
    assert (
        runner_activation_config_integrity_key_path(
            installation=installation,
            config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
        )
        == expected_path
    )

    normalized = require_runner_activation_config_integrity_key_descriptor(
        MappingProxyType(descriptor),
        installation=installation,
        config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
    )
    assert normalized == expected
    assert normalized is not descriptor
    descriptor["materialPath"] = "/tampered"
    assert normalized == expected
    assert set(normalized) == set(expected)


def test_config_integrity_descriptor_is_canonical_and_domain_fingerprinted() -> None:
    installation = _installation()
    descriptor = _descriptor(installation)
    canonical = runner_activation_config_integrity_key_descriptor_canonical_json(
        descriptor,
        installation=installation,
        config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
    )
    assert canonical == json.dumps(
        descriptor,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert runner_activation_config_integrity_key_descriptor_fingerprint(
        descriptor,
        installation=installation,
        config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
    ) == _domain_fingerprint(
        RUNNER_ACTIVATION_CONFIG_INTEGRITY_KEY_DESCRIPTOR_SCHEMA,
        canonical,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("algorithm", "sha256"),
        ("configBlobIntegrityKeyId", OTHER_CONFIG_INTEGRITY_KEY_ID),
        ("keyLengthBytes", 31),
        ("keyLengthBytes", 33),
        ("keyLengthBytes", True),
        ("keyLengthBytes", "32"),
        ("materialPath", "/wrong/.h2ometa/runner/key"),
        ("materialPath", SECRET_SENTINEL),
        ("purpose", "token-encryption"),
        ("runnerInstallationId", OTHER_INSTALLATION_ID),
        (
            "schemaVersion",
            "h2ometa.runner-activation-config-integrity-key-descriptor.v2",
        ),
        ("service", "other-service"),
        ("storageKind", "os-keyring"),
    ],
)
def test_config_integrity_descriptor_rejects_tampering(
    field: str,
    value: object,
) -> None:
    installation = _installation()
    payload = _descriptor(installation)
    payload[field] = value

    with pytest.raises(ValueError):
        require_runner_activation_config_integrity_key_descriptor(
            payload,
            installation=installation,
            config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
        )


def test_config_integrity_descriptor_rejects_field_and_context_drift() -> None:
    installation = _installation()
    descriptor = _descriptor(installation)
    extra = dict(descriptor)
    extra["material"] = SECRET_SENTINEL
    missing = dict(descriptor)
    del missing["purpose"]

    for payload in (None, [], extra, missing):
        with pytest.raises(ValueError):
            require_runner_activation_config_integrity_key_descriptor(
                payload,
                installation=installation,
                config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
            )

    with pytest.raises(ValueError):
        require_runner_activation_config_integrity_key_descriptor(
            descriptor,
            installation=_installation(installation_id=OTHER_INSTALLATION_ID),
            config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
        )
    with pytest.raises(ValueError):
        require_runner_activation_config_integrity_key_descriptor(
            descriptor,
            installation=installation,
            config_integrity_key_id=OTHER_CONFIG_INTEGRITY_KEY_ID,
        )

    colliding_installation = _installation(installation_id=CONFIG_INTEGRITY_KEY_ID)
    with pytest.raises(ValueError, match="identifier roles must be distinct"):
        build_runner_activation_config_integrity_key_descriptor(
            installation=colliding_installation,
            config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
        )
    with pytest.raises(ValueError, match="identifier roles must be distinct"):
        require_runner_activation_config_integrity_key_descriptor(
            descriptor,
            installation=colliding_installation,
            config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
        )


@pytest.mark.parametrize(
    "material",
    [
        b"k" * 31,
        b"k" * 33,
        bytearray(b"k" * 32),
        memoryview(b"k" * 32),
        "k" * 32,
        None,
    ],
)
def test_config_integrity_key_material_requires_exact_32_byte_bytes(
    material: object,
) -> None:
    with pytest.raises(ValueError, match="key material is invalid"):
        require_runner_activation_config_integrity_key_material(material)


def test_config_integrity_key_material_returns_a_detached_immutable_bytes_copy() -> (
    None
):
    class SecretBytes(bytes):
        pass

    source = SecretBytes(b"k" * 32)
    normalized = require_runner_activation_config_integrity_key_material(source)

    assert type(normalized) is bytes
    assert normalized == source
    assert normalized is not source


def test_generation_credential_binding_returns_only_nonsecret_fingerprints() -> None:
    selected_generation = generation(
        token_generation_id=TOKEN_GENERATION_ID,
        config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
    )
    installation = _installation()
    token_ref = _token_ref(installation)
    descriptor = _descriptor(installation)

    binding = require_runner_activation_generation_credential_binding(
        installation=installation,
        generation=selected_generation,
        token_ref=token_ref,
        config_integrity_key_descriptor=descriptor,
    )

    assert binding == RunnerActivationGenerationCredentialBinding(
        installation_fingerprint=runner_activation_installation_fingerprint(
            installation
        ),
        generation_fingerprint=runner_activation_generation_fingerprint(
            selected_generation
        ),
        token_ref_fingerprint=runner_activation_token_ref_fingerprint(
            token_ref,
            installation=installation,
            token_generation_id=TOKEN_GENERATION_ID,
        ),
        config_integrity_key_descriptor_fingerprint=(
            runner_activation_config_integrity_key_descriptor_fingerprint(
                descriptor,
                installation=installation,
                config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
            )
        ),
    )
    assert token_ref not in repr(binding)
    assert set(binding.__dict__) == {
        "config_integrity_key_descriptor_fingerprint",
        "generation_fingerprint",
        "installation_fingerprint",
        "token_ref_fingerprint",
    }
    assert all(value.startswith("sha256:") for value in binding.__dict__.values())
    with pytest.raises(FrozenInstanceError):
        binding.token_ref_fingerprint = "sha256:" + "0" * 64


def test_generation_credential_binding_rejects_root_and_identifier_role_drift() -> None:
    selected_generation = generation(
        token_generation_id=TOKEN_GENERATION_ID,
        config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
    )
    wrong_root_installation = _installation(runner_root="/other/.h2ometa/runner")
    with pytest.raises(ValueError, match="runner root is invalid"):
        require_runner_activation_generation_credential_binding(
            installation=wrong_root_installation,
            generation=selected_generation,
            token_ref=_token_ref(wrong_root_installation),
            config_integrity_key_descriptor=_descriptor(wrong_root_installation),
        )

    generation_id = str(selected_generation["generationId"])
    colliding_installation = _installation(installation_id=generation_id)
    with pytest.raises(ValueError, match="identifier roles must be distinct"):
        require_runner_activation_generation_credential_binding(
            installation=colliding_installation,
            generation=selected_generation,
            token_ref=_token_ref(colliding_installation),
            config_integrity_key_descriptor=_descriptor(colliding_installation),
        )

    token_collision_generation = generation(
        generation_id="7" * 32,
        token_generation_id=INSTALLATION_ID,
        config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
    )
    with pytest.raises(ValueError, match="identifier roles must be distinct"):
        require_runner_activation_generation_credential_binding(
            installation=_installation(),
            generation=token_collision_generation,
            token_ref=(
                f"{RUNNER_ACTIVATION_TOKEN_REF_PREFIX}:"
                f"{INSTALLATION_ID}:{INSTALLATION_ID}"
            ),
            config_integrity_key_descriptor=_descriptor(),
        )

    key_collision_generation = generation(
        generation_id="7" * 32,
        token_generation_id=TOKEN_GENERATION_ID,
        config_integrity_key_id=INSTALLATION_ID,
    )
    collision_descriptor = deepcopy(_descriptor())
    collision_descriptor["configBlobIntegrityKeyId"] = INSTALLATION_ID
    with pytest.raises(ValueError, match="identifier roles must be distinct"):
        require_runner_activation_generation_credential_binding(
            installation=_installation(),
            generation=key_collision_generation,
            token_ref=_token_ref(),
            config_integrity_key_descriptor=collision_descriptor,
        )


def test_generation_credential_binding_rejects_wrong_generation_locators() -> None:
    installation = _installation()
    selected_generation = generation(
        token_generation_id=TOKEN_GENERATION_ID,
        config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
    )
    valid_ref = _token_ref(installation)
    valid_descriptor = _descriptor(installation)
    wrong_ref = _token_ref(installation, token_generation_id=OTHER_TOKEN_GENERATION_ID)
    wrong_descriptor = _descriptor(
        installation,
        config_integrity_key_id=OTHER_CONFIG_INTEGRITY_KEY_ID,
    )

    with pytest.raises(ValueError, match="token reference is invalid"):
        require_runner_activation_generation_credential_binding(
            installation=installation,
            generation=selected_generation,
            token_ref=wrong_ref,
            config_integrity_key_descriptor=valid_descriptor,
        )
    with pytest.raises(ValueError, match="identity binding is invalid"):
        require_runner_activation_generation_credential_binding(
            installation=installation,
            generation=selected_generation,
            token_ref=valid_ref,
            config_integrity_key_descriptor=wrong_descriptor,
        )


def test_custom_errors_do_not_echo_secret_values() -> None:
    installation = _installation()
    descriptor = _descriptor(installation)

    def make_error(message: str) -> CredentialBindingContractError:
        return CredentialBindingContractError(f"custom: {message}")

    calls = [
        lambda: runner_activation_config_integrity_key_descriptor_fingerprint(
            {**descriptor, "materialPath": SECRET_SENTINEL},
            installation=installation,
            config_integrity_key_id=CONFIG_INTEGRITY_KEY_ID,
            make_error=make_error,
        ),
        lambda: require_runner_activation_config_integrity_key_material(
            SECRET_SENTINEL.encode(),
            make_error=make_error,
        ),
        lambda: require_runner_activation_generation_credential_binding(
            installation=installation,
            generation={"secret": SECRET_SENTINEL},
            token_ref=SECRET_SENTINEL,
            config_integrity_key_descriptor=descriptor,
            make_error=make_error,
        ),
    ]
    for call in calls:
        with pytest.raises(
            CredentialBindingContractError, match="^custom:"
        ) as captured:
            call()
        assert SECRET_SENTINEL not in str(captured.value)
