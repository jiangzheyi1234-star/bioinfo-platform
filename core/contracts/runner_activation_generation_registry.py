"""Append-only identities for immutable remote-runner generations.

The control plane must rebuild this registry from the complete trusted,
no-replace registration journal before planning an append.  These pure
validators prove exact generation-record identity and hash-chain continuity;
they do not prove journal durability, actual artifact bytes, or that a
registered generation directory was published.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .runner_activation_target import (
    RUNNER_ACTIVATION_SERVICE,
    require_runner_activation_generation,
    runner_activation_generation_fingerprint,
)
from .runner_activation_validation import (
    canonical_json as _canonical_json,
    fingerprint as _fingerprint,
    require_exact_string as _require_exact_string,
    require_fingerprint as _require_fingerprint,
    require_id as _require_id,
    require_mapping as _require_mapping,
    require_optional_fingerprint as _require_optional_fingerprint,
    require_positive_integer as _require_positive_integer,
)


RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA = (
    "h2ometa.runner-activation-generation-registry.v1"
)
RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA = (
    "h2ometa.runner-activation-generation-registration.v1"
)
RUNNER_ACTIVATION_GENERATION_REGISTRY_SERVICE = RUNNER_ACTIVATION_SERVICE

_REGISTRY_FIELDS = frozenset({"registrations", "schemaVersion", "service"})
_REGISTRATION_FIELDS = frozenset(
    {
        "generation",
        "generationFingerprint",
        "generationId",
        "previousRegistrationFingerprint",
        "revision",
        "schemaVersion",
        "service",
    }
)
_REGISTRY_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA.encode(
    "ascii"
)
_REGISTRATION_FINGERPRINT_DOMAIN = (
    RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA.encode("ascii")
)


def build_empty_runner_activation_generation_registry() -> dict[str, object]:
    """Return the exact empty registry envelope."""

    return {
        "registrations": [],
        "schemaVersion": RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA,
        "service": RUNNER_ACTIVATION_GENERATION_REGISTRY_SERVICE,
    }


def _build_runner_activation_generation_registration(
    *,
    generation: object,
    previous_registration: object | None = None,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Derive the only registration that can follow ``previous_registration``."""

    normalized_generation = require_runner_activation_generation(
        generation,
        make_error=make_error,
    )
    if previous_registration is None:
        revision = 1
        previous_fingerprint = ""
    else:
        previous = require_runner_activation_generation_registration(
            previous_registration,
            make_error=make_error,
        )
        revision = int(previous["revision"]) + 1
        previous_fingerprint = runner_activation_generation_registration_fingerprint(
            previous,
            make_error=make_error,
        )
    return require_runner_activation_generation_registration(
        {
            "generation": normalized_generation,
            "generationFingerprint": runner_activation_generation_fingerprint(
                normalized_generation
            ),
            "generationId": normalized_generation["generationId"],
            "previousRegistrationFingerprint": previous_fingerprint,
            "revision": revision,
            "schemaVersion": RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA,
            "service": RUNNER_ACTIVATION_GENERATION_REGISTRY_SERVICE,
        },
        make_error=make_error,
    )


def require_runner_activation_generation_registration(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate one registration and return a detached normalized copy."""

    mapping = _require_mapping(
        payload,
        expected=_REGISTRATION_FIELDS,
        context="runner activation generation registration",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA,
        field="generationRegistration.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_GENERATION_REGISTRY_SERVICE,
        field="generationRegistration.service",
        make_error=make_error,
    )
    generation = require_runner_activation_generation(
        mapping.get("generation"),
        make_error=make_error,
    )
    generation_id = _require_id(
        mapping.get("generationId"),
        "generationRegistration.generationId",
        make_error,
    )
    if generation_id != generation["generationId"]:
        raise make_error(
            "runner activation generation registration generationId binding is invalid"
        )
    generation_fingerprint = _require_fingerprint(
        mapping.get("generationFingerprint"),
        "generationRegistration.generationFingerprint",
        make_error,
    )
    expected_generation_fingerprint = runner_activation_generation_fingerprint(
        generation
    )
    if generation_fingerprint != expected_generation_fingerprint:
        raise make_error(
            "runner activation generation registration content binding is invalid"
        )
    revision = _require_positive_integer(
        mapping.get("revision"),
        "generationRegistration.revision",
        make_error,
    )
    previous_fingerprint = _require_optional_fingerprint(
        mapping.get("previousRegistrationFingerprint"),
        "generationRegistration.previousRegistrationFingerprint",
        make_error,
    )
    if (revision == 1 and previous_fingerprint) or (
        revision > 1 and not previous_fingerprint
    ):
        raise make_error(
            "runner activation generation registration predecessor is invalid"
        )
    return {
        "generation": generation,
        "generationFingerprint": generation_fingerprint,
        "generationId": generation_id,
        "previousRegistrationFingerprint": previous_fingerprint,
        "revision": revision,
        "schemaVersion": RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA,
        "service": RUNNER_ACTIVATION_GENERATION_REGISTRY_SERVICE,
    }


def runner_activation_generation_registration_canonical_json(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    normalized = require_runner_activation_generation_registration(
        payload,
        make_error=make_error,
    )
    return _canonical_json(normalized)


def runner_activation_generation_registration_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    return _fingerprint(
        _REGISTRATION_FINGERPRINT_DOMAIN,
        runner_activation_generation_registration_canonical_json(
            payload,
            make_error=make_error,
        ),
    )


def build_runner_activation_generation_registry(
    registrations: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Build and validate an exact registry from supplied registrations."""

    return require_runner_activation_generation_registry(
        {
            "registrations": registrations,
            "schemaVersion": RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA,
            "service": RUNNER_ACTIVATION_GENERATION_REGISTRY_SERVICE,
        },
        make_error=make_error,
    )


def require_runner_activation_generation_registry(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate registry continuity and global generation-ID uniqueness."""

    mapping = _require_mapping(
        payload,
        expected=_REGISTRY_FIELDS,
        context="runner activation generation registry",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA,
        field="generationRegistry.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_GENERATION_REGISTRY_SERVICE,
        field="generationRegistry.service",
        make_error=make_error,
    )
    registrations = mapping.get("registrations")
    if not isinstance(registrations, Sequence) or isinstance(
        registrations,
        (str, bytes, bytearray),
    ):
        raise make_error("runner activation generation registry is invalid")

    normalized: list[dict[str, object]] = []
    generation_ids: set[str] = set()
    generation_fingerprints: set[str] = set()
    for index, value in enumerate(registrations):
        registration = require_runner_activation_generation_registration(
            value,
            make_error=make_error,
        )
        if index == 0:
            if registration["revision"] != 1:
                raise make_error(
                    "runner activation generation registry must begin at revision 1"
                )
        else:
            previous = normalized[-1]
            expected_previous_fingerprint = (
                runner_activation_generation_registration_fingerprint(
                    previous,
                    make_error=make_error,
                )
            )
            if (
                registration["revision"] != int(previous["revision"]) + 1
                or registration["previousRegistrationFingerprint"]
                != expected_previous_fingerprint
            ):
                raise make_error(
                    "runner activation generation registry is not contiguous"
                )
        generation_id = str(registration["generationId"])
        generation_fingerprint = str(registration["generationFingerprint"])
        if generation_id in generation_ids:
            raise make_error(
                "runner activation generation registry contains a reused generationId"
            )
        if generation_fingerprint in generation_fingerprints:
            raise make_error(
                "runner activation generation registry contains a reused generationFingerprint"
            )
        generation_ids.add(generation_id)
        generation_fingerprints.add(generation_fingerprint)
        normalized.append(registration)
    return {
        "registrations": normalized,
        "schemaVersion": RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA,
        "service": RUNNER_ACTIVATION_GENERATION_REGISTRY_SERVICE,
    }


def runner_activation_generation_registry_canonical_json(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    normalized = require_runner_activation_generation_registry(
        payload,
        make_error=make_error,
    )
    return _canonical_json(normalized)


def runner_activation_generation_registry_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    return _fingerprint(
        _REGISTRY_FINGERPRINT_DOMAIN,
        runner_activation_generation_registry_canonical_json(
            payload,
            make_error=make_error,
        ),
    )


def runner_activation_generation_registry_identity_map(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, str]:
    """Return detached ``generationId -> generationFingerprint`` bindings."""

    registry = require_runner_activation_generation_registry(
        payload,
        make_error=make_error,
    )
    registrations = registry["registrations"]
    if not isinstance(registrations, list):  # pragma: no cover - validator invariant.
        raise make_error("runner activation generation registry is invalid")
    return {
        str(registration["generationId"]): str(registration["generationFingerprint"])
        for registration in registrations
    }


def plan_runner_activation_generation_registry_append(
    registry_payload: object,
    *,
    generation: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object] | None:
    """Plan the next journal record from the complete authoritative registry.

    ``None`` means this exact generation identity is already permanently
    registered.  It does not prove that the generation directory was published.
    Callers recovering from a crash must rebuild ``registry_payload`` from the
    trusted no-replace journal rather than supply an out-of-band record.
    """

    registry = require_runner_activation_generation_registry(
        registry_payload,
        make_error=make_error,
    )
    normalized_generation = require_runner_activation_generation(
        generation,
        make_error=make_error,
    )
    generation_id = str(normalized_generation["generationId"])
    registrations = registry["registrations"]
    if not isinstance(registrations, list):  # pragma: no cover - validator invariant.
        raise make_error("runner activation generation registry is invalid")
    existing = next(
        (
            registration
            for registration in registrations
            if registration["generationId"] == generation_id
        ),
        None,
    )
    if existing is not None:
        if existing["generation"] != normalized_generation:
            raise make_error(
                "runner activation generationId was reused with different content"
            )
        return None
    previous = registrations[-1] if registrations else None
    return _build_runner_activation_generation_registration(
        generation=normalized_generation,
        previous_registration=previous,
        make_error=make_error,
    )


def require_runner_activation_generation_registry_binding(
    registry_payload: object,
    *,
    generation: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Require the registry to contain the exact supplied generation identity."""

    registry = require_runner_activation_generation_registry(
        registry_payload,
        make_error=make_error,
    )
    normalized_generation = require_runner_activation_generation(
        generation,
        make_error=make_error,
    )
    generation_id = str(normalized_generation["generationId"])
    registrations = registry["registrations"]
    if not isinstance(registrations, list):  # pragma: no cover - validator invariant.
        raise make_error("runner activation generation registry is invalid")
    matching = [
        registration
        for registration in registrations
        if registration["generationId"] == generation_id
    ]
    if len(matching) != 1 or matching[0]["generation"] != normalized_generation:
        raise make_error("runner activation generation registry binding is invalid")
    return runner_activation_generation_registration_fingerprint(
        matching[0],
        make_error=make_error,
    )


__all__ = [
    "RUNNER_ACTIVATION_GENERATION_REGISTRATION_SCHEMA",
    "RUNNER_ACTIVATION_GENERATION_REGISTRY_SCHEMA",
    "RUNNER_ACTIVATION_GENERATION_REGISTRY_SERVICE",
    "build_empty_runner_activation_generation_registry",
    "build_runner_activation_generation_registry",
    "plan_runner_activation_generation_registry_append",
    "require_runner_activation_generation_registration",
    "require_runner_activation_generation_registry",
    "require_runner_activation_generation_registry_binding",
    "runner_activation_generation_registration_canonical_json",
    "runner_activation_generation_registration_fingerprint",
    "runner_activation_generation_registry_canonical_json",
    "runner_activation_generation_registry_fingerprint",
    "runner_activation_generation_registry_identity_map",
]
