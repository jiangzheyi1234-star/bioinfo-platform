from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

import core.contracts.runner_activation_generation_registry as registry_contract
from core.contracts.runner_activation_generation_registry import (
    RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA,
    RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA,
    build_empty_runner_activation_generation_registry,
    build_runner_activation_generation_registry,
    plan_runner_activation_generation_registry_append,
    require_runner_activation_generation_registration,
    require_runner_activation_generation_registry,
    require_runner_activation_generation_registry_binding,
    runner_activation_generation_registration_canonical_json,
    runner_activation_generation_registration_fingerprint,
    runner_activation_generation_registry_canonical_json,
    runner_activation_generation_registry_fingerprint,
    runner_activation_generation_registry_identity_map,
)
from core.contracts.runner_activation_target import (
    runner_activation_generation_fingerprint,
)
from tests.helpers.runner_activation_contract import generation


FIRST_GENERATION_ID = "1" * 32
FIRST_TOKEN_GENERATION_ID = "2" * 32
FIRST_INTEGRITY_KEY_ID = "3" * 32
SECOND_GENERATION_ID = "4" * 32
SECOND_TOKEN_GENERATION_ID = "5" * 32
SECOND_INTEGRITY_KEY_ID = "6" * 32
SECRET_SENTINEL = "registry-must-never-store-this-secret"


class GenerationRegistryError(RuntimeError):
    pass


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _domain_fingerprint(schema: str, payload: object) -> str:
    digest = hashlib.sha256(
        schema.encode("ascii") + b"\x00" + _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _first_generation() -> dict[str, object]:
    return generation(
        generation_id=FIRST_GENERATION_ID,
        token_generation_id=FIRST_TOKEN_GENERATION_ID,
        config_integrity_key_id=FIRST_INTEGRITY_KEY_ID,
        release_name="0.2.0-registry-a",
    )


def _second_generation() -> dict[str, object]:
    return generation(
        generation_id=SECOND_GENERATION_ID,
        token_generation_id=SECOND_TOKEN_GENERATION_ID,
        config_integrity_key_id=SECOND_INTEGRITY_KEY_ID,
        release_name="0.2.0-registry-b",
        config_integrity_tag="hmac-sha256:" + "7" * 64,
        runtime_config_fingerprint="sha256:" + "8" * 64,
        unit_fingerprint="sha256:" + "9" * 64,
    )


def _planned_registration(
    selected_generation: object | None = None,
    *,
    prior_registrations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    prior = build_runner_activation_generation_registry(prior_registrations or [])
    planned = plan_runner_activation_generation_registry_append(
        prior,
        generation=(
            _first_generation() if selected_generation is None else selected_generation
        ),
    )
    assert isinstance(planned, dict)
    return planned


def _adversarial_registration(
    selected_generation: dict[str, object],
    *,
    previous_registration: dict[str, object],
) -> dict[str, object]:
    """Construct an attacker-controlled journal entry for rejection tests."""

    return require_runner_activation_generation_registration(
        {
            "generation": selected_generation,
            "generationFingerprint": runner_activation_generation_fingerprint(
                selected_generation
            ),
            "generationId": selected_generation["generationId"],
            "previousRegistrationFingerprint": (
                runner_activation_generation_registration_fingerprint(
                    previous_registration
                )
            ),
            "revision": int(previous_registration["revision"]) + 1,
            "schemaVersion": RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA,
            "service": "h2ometa-remote",
        }
    )


def _full_registry() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    first = _planned_registration()
    second = _planned_registration(
        _second_generation(),
        prior_registrations=[first],
    )
    return first, second, build_runner_activation_generation_registry([first, second])


def test_public_registry_contract_schemas_are_exact() -> None:
    assert RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA == (
        "h2ometa.runner-activation-generation-registry.v1"
    )
    assert RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA == (
        "h2ometa.runner-activation-generation-registration.v1"
    )
    assert not hasattr(
        registry_contract,
        "build_runner_activation_generation_registration",
    )
    assert "build_runner_activation_generation_registration" not in (
        registry_contract.__all__
    )


def test_empty_registry_is_exact_and_domain_separated() -> None:
    payload = build_empty_runner_activation_generation_registry()

    assert payload == {
        "registrations": [],
        "schemaVersion": RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA,
        "service": "h2ometa-remote",
    }
    assert runner_activation_generation_registry_canonical_json(payload) == (
        _canonical_json(payload)
    )
    assert runner_activation_generation_registry_fingerprint(payload) == (
        _domain_fingerprint(RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA, payload)
    )
    assert runner_activation_generation_registry_identity_map(payload) == {}


def test_registration_is_exact_and_domain_separated() -> None:
    selected_generation = _first_generation()
    registration = _planned_registration(selected_generation)

    assert registration["generation"] is not selected_generation
    assert registration == {
        "generation": selected_generation,
        "generationFingerprint": runner_activation_generation_fingerprint(
            selected_generation
        ),
        "generationId": FIRST_GENERATION_ID,
        "previousRegistrationFingerprint": "",
        "revision": 1,
        "schemaVersion": RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA,
        "service": "h2ometa-remote",
    }
    assert runner_activation_generation_registration_canonical_json(
        registration
    ) == _canonical_json(registration)
    assert runner_activation_generation_registration_fingerprint(registration) == (
        _domain_fingerprint(
            RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA,
            registration,
        )
    )

    selected_generation["releaseArtifactSha256"] = "sha256:" + "f" * 64
    assert registration["generationFingerprint"] == (
        runner_activation_generation_fingerprint(registration["generation"])
    )


def test_full_registry_has_canonical_hashes_and_identity_map() -> None:
    first, second, registry = _full_registry()

    assert second["revision"] == 2
    assert second["previousRegistrationFingerprint"] == (
        runner_activation_generation_registration_fingerprint(first)
    )
    assert runner_activation_generation_registry_fingerprint(registry) == (
        _domain_fingerprint(RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA, registry)
    )
    assert runner_activation_generation_registry_identity_map(registry) == {
        FIRST_GENERATION_ID: runner_activation_generation_fingerprint(
            first["generation"]
        ),
        SECOND_GENERATION_ID: runner_activation_generation_fingerprint(
            second["generation"]
        ),
    }

    reordered_registry = dict(reversed(list(registry.items())))
    reordered_registry["registrations"] = [
        dict(reversed(list(first.items()))),
        dict(reversed(list(second.items()))),
    ]
    assert runner_activation_generation_registry_fingerprint(
        reordered_registry
    ) == runner_activation_generation_registry_fingerprint(registry)


@pytest.mark.parametrize(
    ("factory", "validator", "extra_field"),
    [
        (
            build_empty_runner_activation_generation_registry,
            require_runner_activation_generation_registry,
            "headFingerprint",
        ),
        (
            _planned_registration,
            require_runner_activation_generation_registration,
            "token",
        ),
    ],
)
def test_registry_contracts_reject_extra_or_missing_fields(
    factory: object,
    validator: object,
    extra_field: str,
) -> None:
    payload = factory()
    assert isinstance(payload, dict)
    payload[extra_field] = SECRET_SENTINEL
    with pytest.raises(ValueError, match="fields must match exactly"):
        validator(payload)

    missing = factory()
    assert isinstance(missing, dict)
    missing.pop("service")
    with pytest.raises(ValueError, match="fields must match exactly"):
        validator(missing)


def test_registry_returns_a_deeply_detached_normalized_copy() -> None:
    _first, _second, payload = _full_registry()
    normalized = require_runner_activation_generation_registry(payload)

    assert normalized == payload
    assert normalized is not payload
    normalized_registrations = normalized["registrations"]
    payload_registrations = payload["registrations"]
    assert isinstance(normalized_registrations, list)
    assert isinstance(payload_registrations, list)
    assert normalized_registrations is not payload_registrations
    assert normalized_registrations[0] is not payload_registrations[0]
    assert (
        normalized_registrations[0]["generation"]
        is not payload_registrations[0]["generation"]
    )

    first_generation = payload_registrations[0]["generation"]
    second_generation = payload_registrations[1]["generation"]
    assert isinstance(first_generation, dict)
    assert isinstance(second_generation, dict)
    first_generation["releaseArtifactSha256"] = "sha256:" + "a" * 64
    second_generation["tokenGenerationId"] = "b" * 32
    payload_registrations.clear()

    assert len(normalized_registrations) == 2
    assert normalized_registrations[0]["generationId"] == FIRST_GENERATION_ID
    assert normalized_registrations[1]["generationId"] == SECOND_GENERATION_ID


def test_registration_requires_embedded_generation_id_and_fingerprint_binding() -> None:
    registration = _planned_registration()

    wrong_id = deepcopy(registration)
    wrong_id["generationId"] = SECOND_GENERATION_ID
    with pytest.raises(ValueError, match="generationId.*binding|binding.*generationId"):
        require_runner_activation_generation_registration(wrong_id)

    wrong_fingerprint = deepcopy(registration)
    wrong_fingerprint["generationFingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(
        ValueError,
        match="generationFingerprint|fingerprint.*binding|content binding",
    ):
        require_runner_activation_generation_registration(wrong_fingerprint)

    changed_generation = deepcopy(registration)
    embedded = changed_generation["generation"]
    assert isinstance(embedded, dict)
    embedded["releaseArtifactSha256"] = "sha256:" + "a" * 64
    with pytest.raises(
        ValueError,
        match="generationFingerprint|fingerprint.*binding|content binding",
    ):
        require_runner_activation_generation_registration(changed_generation)


@pytest.mark.parametrize(
    ("revision", "previous_fingerprint"),
    [
        (True, ""),
        (0, ""),
        (-1, ""),
        (1, "sha256:" + "0" * 64),
        (2, ""),
    ],
)
def test_registration_rejects_invalid_revision_predecessor_shape(
    revision: object,
    previous_fingerprint: str,
) -> None:
    payload = _planned_registration()
    payload["revision"] = revision
    payload["previousRegistrationFingerprint"] = previous_fingerprint

    with pytest.raises(ValueError, match="revision|predecessor"):
        require_runner_activation_generation_registration(payload)


def test_registry_requires_contiguous_revision_and_hash_chain() -> None:
    first, second, _registry = _full_registry()

    with pytest.raises(ValueError, match="must begin at revision 1"):
        build_runner_activation_generation_registry([second])

    skipped_revision = deepcopy(second)
    skipped_revision["revision"] = 3
    with pytest.raises(ValueError, match="not contiguous"):
        build_runner_activation_generation_registry([first, skipped_revision])

    detached_predecessor = deepcopy(second)
    detached_predecessor["previousRegistrationFingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="not contiguous"):
        build_runner_activation_generation_registry([first, detached_predecessor])

    with pytest.raises(ValueError, match="must begin|not contiguous"):
        build_runner_activation_generation_registry([second, first])


def test_registry_rejects_duplicate_generation_id_even_for_exact_content() -> None:
    first, second, _registry = _full_registry()
    duplicate = _adversarial_registration(
        _first_generation(),
        previous_registration=second,
    )

    with pytest.raises(
        ValueError,
        match="reused.*generation(?:Id| identity)|generationId.*reused",
    ):
        build_runner_activation_generation_registry([first, second, duplicate])


def test_registry_rejects_a_b_a_prime_generation_id_drift() -> None:
    first, second, _registry = _full_registry()
    changed_a = generation(
        generation_id=FIRST_GENERATION_ID,
        token_generation_id=FIRST_TOKEN_GENERATION_ID,
        config_integrity_key_id=FIRST_INTEGRITY_KEY_ID,
        release_name="0.2.1-drifted-a",
        runtime_config_fingerprint="sha256:" + "c" * 64,
    )
    drifted_registration = _adversarial_registration(
        changed_a,
        previous_registration=second,
    )

    assert (
        runner_activation_generation_fingerprint(changed_a)
        != (first["generationFingerprint"])
    )
    with pytest.raises(
        ValueError,
        match="reused.*generation(?:Id| identity)|generationId.*reused",
    ):
        build_runner_activation_generation_registry(
            [first, second, drifted_registration]
        )


@pytest.mark.parametrize(
    "registrations",
    [
        "not-a-sequence",
        b"not-a-sequence",
        {"0": "not-a-registration"},
        [None],
        [[]],
    ],
)
def test_registry_rejects_malformed_registration_sequences(
    registrations: object,
) -> None:
    payload = build_empty_runner_activation_generation_registry()
    payload["registrations"] = registrations

    with pytest.raises(ValueError, match="generation registry|registration"):
        require_runner_activation_generation_registry(payload)


def test_plan_builds_only_the_exact_next_registration() -> None:
    empty = build_empty_runner_activation_generation_registry()
    first_generation = _first_generation()
    first = plan_runner_activation_generation_registry_append(
        empty,
        generation=first_generation,
    )
    assert first is not None
    assert first["revision"] == 1
    assert first["previousRegistrationFingerprint"] == ""

    prior = build_runner_activation_generation_registry([first])
    second = plan_runner_activation_generation_registry_append(
        prior,
        generation=_second_generation(),
    )
    assert second is not None
    assert second["revision"] == 2
    assert second["previousRegistrationFingerprint"] == (
        runner_activation_generation_registration_fingerprint(first)
    )


def test_plan_exact_reuse_is_noop_only_after_authoritative_rebuild() -> None:
    empty = build_empty_runner_activation_generation_registry()
    selected_generation = _first_generation()

    orphan_candidate = plan_runner_activation_generation_registry_append(
        empty,
        generation=selected_generation,
    )
    assert orphan_candidate is not None

    # A no-replace journal entry may outlive a crash before later publication.
    # The retry must rebuild the authoritative registry from that journal first.
    rebuilt_registry = build_runner_activation_generation_registry([orphan_candidate])
    reordered_generation = dict(reversed(list(selected_generation.items())))
    assert (
        plan_runner_activation_generation_registry_append(
            rebuilt_registry,
            generation=reordered_generation,
        )
        is None
    )
    assert require_runner_activation_generation_registry_binding(
        rebuilt_registry,
        generation=selected_generation,
    ) == runner_activation_generation_registration_fingerprint(orphan_candidate)


def test_plan_rejects_same_id_with_different_generation_content() -> None:
    first = _planned_registration()
    registry = build_runner_activation_generation_registry([first])
    changed_a = generation(
        generation_id=FIRST_GENERATION_ID,
        token_generation_id=FIRST_TOKEN_GENERATION_ID,
        config_integrity_key_id=FIRST_INTEGRITY_KEY_ID,
        release_name="0.2.1-plan-drift",
        config_integrity_tag="hmac-sha256:" + "d" * 64,
    )

    with pytest.raises(ValueError, match="generationId.*different|identity.*drift"):
        plan_runner_activation_generation_registry_append(
            registry,
            generation=changed_a,
        )


def test_binding_requires_exact_registered_generation() -> None:
    first, _second, registry = _full_registry()

    assert require_runner_activation_generation_registry_binding(
        registry,
        generation=_first_generation(),
    ) == runner_activation_generation_registration_fingerprint(first)

    with pytest.raises(ValueError, match="not registered|binding"):
        require_runner_activation_generation_registry_binding(
            registry,
            generation=generation(
                generation_id="a" * 32,
                token_generation_id="b" * 32,
                config_integrity_key_id="c" * 32,
                release_name="0.2.0-unregistered",
            ),
        )

    drifted_a = generation(
        generation_id=FIRST_GENERATION_ID,
        token_generation_id=FIRST_TOKEN_GENERATION_ID,
        config_integrity_key_id=FIRST_INTEGRITY_KEY_ID,
        release_name="0.2.1-binding-drift",
    )
    with pytest.raises(ValueError, match="binding.*(?:drift|invalid)|different"):
        require_runner_activation_generation_registry_binding(
            registry,
            generation=drifted_a,
        )


def test_registry_contains_only_public_generation_evidence() -> None:
    _first, _second, registry = _full_registry()
    serialized = runner_activation_generation_registry_canonical_json(registry)

    assert SECRET_SENTINEL not in serialized
    for registration in registry["registrations"]:
        assert set(registration) == {
            "generation",
            "generationFingerprint",
            "generationId",
            "previousRegistrationFingerprint",
            "revision",
            "schemaVersion",
            "service",
        }
        embedded = registration["generation"]
        assert isinstance(embedded, dict)
        assert "token" not in embedded
        assert "configBlobIntegrityKey" not in embedded
        assert "credential" not in embedded

    secret_in_registration = deepcopy(registry["registrations"][0])
    secret_in_registration["token"] = SECRET_SENTINEL
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_generation_registration(secret_in_registration)

    secret_in_generation = deepcopy(registry["registrations"][0])
    embedded = secret_in_generation["generation"]
    assert isinstance(embedded, dict)
    embedded["configBlobIntegrityKey"] = SECRET_SENTINEL
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_generation_registration(secret_in_generation)


def test_registry_apis_propagate_the_callers_custom_error_type() -> None:
    def make_error(message: str) -> GenerationRegistryError:
        return GenerationRegistryError(f"custom: {message}")

    malformed_registry = build_empty_runner_activation_generation_registry()
    malformed_registry["registrations"] = "invalid"
    malformed_registration = _planned_registration()
    malformed_registration["generationFingerprint"] = "invalid"
    malformed_nested_registration = _planned_registration()
    malformed_nested_generation = malformed_nested_registration["generation"]
    assert isinstance(malformed_nested_generation, dict)
    malformed_nested_generation["token"] = SECRET_SENTINEL
    malformed_generation = _first_generation()
    malformed_generation["token"] = SECRET_SENTINEL
    valid_empty_registry = build_empty_runner_activation_generation_registry()
    _first, _second, valid_full_registry = _full_registry()

    calls = [
        lambda: require_runner_activation_generation_registration(
            malformed_registration,
            make_error=make_error,
        ),
        lambda: require_runner_activation_generation_registration(
            malformed_nested_registration,
            make_error=make_error,
        ),
        lambda: require_runner_activation_generation_registry(
            malformed_registry,
            make_error=make_error,
        ),
        lambda: runner_activation_generation_registration_canonical_json(
            malformed_registration,
            make_error=make_error,
        ),
        lambda: runner_activation_generation_registry_canonical_json(
            malformed_registry,
            make_error=make_error,
        ),
        lambda: runner_activation_generation_registration_fingerprint(
            malformed_registration,
            make_error=make_error,
        ),
        lambda: runner_activation_generation_registry_fingerprint(
            malformed_registry,
            make_error=make_error,
        ),
        lambda: runner_activation_generation_registry_identity_map(
            malformed_registry,
            make_error=make_error,
        ),
        lambda: build_runner_activation_generation_registry(
            "invalid",
            make_error=make_error,
        ),
        lambda: plan_runner_activation_generation_registry_append(
            valid_empty_registry,
            generation=malformed_generation,
            make_error=make_error,
        ),
        lambda: require_runner_activation_generation_registry_binding(
            valid_full_registry,
            generation=malformed_generation,
            make_error=make_error,
        ),
    ]
    for call in calls:
        with pytest.raises(GenerationRegistryError, match="^custom:"):
            call()
