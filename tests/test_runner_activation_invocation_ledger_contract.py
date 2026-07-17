from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from core.contracts.runner_activation_invocation_ledger import (
    RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA,
    RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
    RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA,
    build_empty_runner_activation_invocation_ledger,
    build_runner_activation_invocation_ledger,
    build_runner_activation_invocation_reservation,
    require_runner_activation_invocation_ledger,
    require_runner_activation_invocation_reservation,
    require_runner_activation_invocation_reservation_binding,
    require_runner_activation_lineage_invocations_reserved,
    require_runner_activation_prior_invocation_ledger,
    runner_activation_expected_invocation_reservation_fingerprint,
    runner_activation_invocation_ledger_fingerprint,
    runner_activation_invocation_ledger_identity_sets,
    runner_activation_invocation_reservation_fingerprint,
)


ACTIVATION_ID = "a" * 32
GENERATION_ID = "b" * 32
INVOCATION_ID = "c" * 32
SECOND_ACTIVATION_ID = "d" * 32
SECOND_GENERATION_ID = "e" * 32
SECOND_INVOCATION_ID = "f" * 32
OBSERVED_TRANSITION_FINGERPRINT = "sha256:" + "1" * 64
TARGET_FINGERPRINT = "sha256:" + "2" * 64
SECOND_OBSERVED_TRANSITION_FINGERPRINT = "sha256:" + "3" * 64
SECOND_TARGET_FINGERPRINT = "sha256:" + "4" * 64


class InvocationLedgerError(RuntimeError):
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


def _reservation(
    *,
    activation_id: str = ACTIVATION_ID,
    generation_id: str = GENERATION_ID,
    invocation_id: str = INVOCATION_ID,
    observed_transition_fingerprint: str = (OBSERVED_TRANSITION_FINGERPRINT),
    target_fingerprint: str = TARGET_FINGERPRINT,
    previous_reservation: object | None = None,
) -> dict[str, object]:
    return build_runner_activation_invocation_reservation(
        activation_id=activation_id,
        generation_id=generation_id,
        invocation_id=invocation_id,
        observed_transition_fingerprint=observed_transition_fingerprint,
        previous_reservation=previous_reservation,
        systemd_unit=f"h2ometa-remote@{activation_id}.service",
        target_fingerprint=target_fingerprint,
    )


def _full_ledger() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    first = _reservation()
    second = _reservation(
        activation_id=SECOND_ACTIVATION_ID,
        generation_id=SECOND_GENERATION_ID,
        invocation_id=SECOND_INVOCATION_ID,
        observed_transition_fingerprint=(SECOND_OBSERVED_TRANSITION_FINGERPRINT),
        target_fingerprint=SECOND_TARGET_FINGERPRINT,
        previous_reservation=first,
    )
    return first, second, build_runner_activation_invocation_ledger([first, second])


def _second_binding_kwargs() -> dict[str, object]:
    return {
        "activation_id": SECOND_ACTIVATION_ID,
        "generation_id": SECOND_GENERATION_ID,
        "invocation_id": SECOND_INVOCATION_ID,
        "observed_transition_fingerprint": (SECOND_OBSERVED_TRANSITION_FINGERPRINT),
        "systemd_unit": (f"h2ometa-remote@{SECOND_ACTIVATION_ID}.service"),
        "target_fingerprint": SECOND_TARGET_FINGERPRINT,
    }


def test_public_invocation_ledger_contract_constants_are_exact() -> None:
    assert RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA == (
        "h2ometa.runner-activation-invocation-ledger.v1"
    )
    assert RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA == (
        "h2ometa.runner-activation-invocation-reservation.v1"
    )
    assert RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE == "h2ometa-remote"


def test_empty_ledger_is_exact_and_has_domain_separated_fingerprint() -> None:
    payload = build_empty_runner_activation_invocation_ledger()

    assert payload == {
        "reservations": [],
        "schemaVersion": RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA,
        "service": RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
    }
    assert runner_activation_invocation_ledger_fingerprint(payload) == (
        _domain_fingerprint(
            RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA,
            payload,
        )
    )
    assert runner_activation_invocation_ledger_identity_sets(payload) == (
        frozenset(),
        frozenset(),
    )


def test_full_ledger_and_reservations_have_canonical_fingerprints() -> None:
    first, second, ledger = _full_ledger()

    assert second["revision"] == 2
    assert second["previousReservationFingerprint"] == (
        runner_activation_invocation_reservation_fingerprint(first)
    )
    assert runner_activation_invocation_reservation_fingerprint(first) == (
        _domain_fingerprint(
            RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA,
            first,
        )
    )
    assert runner_activation_invocation_ledger_fingerprint(ledger) == (
        _domain_fingerprint(
            RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA,
            ledger,
        )
    )

    reordered_ledger = dict(reversed(list(ledger.items())))
    reordered_ledger["reservations"] = [
        dict(reversed(list(first.items()))),
        dict(reversed(list(second.items()))),
    ]
    assert runner_activation_invocation_ledger_fingerprint(
        reordered_ledger
    ) == runner_activation_invocation_ledger_fingerprint(ledger)


def test_reservation_is_exact_and_binds_target_unit_and_identities() -> None:
    reservation = _reservation()

    assert reservation == {
        "activationId": ACTIVATION_ID,
        "generationId": GENERATION_ID,
        "invocationId": INVOCATION_ID,
        "observedTransitionFingerprint": (OBSERVED_TRANSITION_FINGERPRINT),
        "previousReservationFingerprint": "",
        "revision": 1,
        "schemaVersion": RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA,
        "service": RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
        "systemdUnit": f"h2ometa-remote@{ACTIVATION_ID}.service",
        "targetFingerprint": TARGET_FINGERPRINT,
    }

    wrong_unit = deepcopy(reservation)
    wrong_unit["systemdUnit"] = f"h2ometa-remote@{SECOND_ACTIVATION_ID}.service"
    with pytest.raises(ValueError, match="systemdUnit"):
        require_runner_activation_invocation_reservation(wrong_unit)

    rebound_target = deepcopy(reservation)
    rebound_target["targetFingerprint"] = SECOND_TARGET_FINGERPRINT
    assert runner_activation_invocation_reservation_fingerprint(
        rebound_target
    ) != runner_activation_invocation_reservation_fingerprint(reservation)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("activationId", "generationId"),
        ("activationId", "invocationId"),
        ("generationId", "invocationId"),
    ],
)
def test_reservation_requires_three_distinct_identities(
    left: str,
    right: str,
) -> None:
    payload = _reservation()
    payload[right] = payload[left]
    if right == "activationId":
        payload["systemdUnit"] = f"h2ometa-remote@{payload[left]}.service"

    with pytest.raises(ValueError, match="identities must be distinct"):
        require_runner_activation_invocation_reservation(payload)


@pytest.mark.parametrize(
    ("factory", "extra_field"),
    [
        (build_empty_runner_activation_invocation_ledger, "headFingerprint"),
        (_reservation, "token"),
    ],
)
def test_contracts_reject_extra_or_missing_fields(
    factory: object,
    extra_field: str,
) -> None:
    payload = factory()
    assert isinstance(payload, dict)
    payload[extra_field] = "must-not-be-accepted"
    validator = (
        require_runner_activation_invocation_ledger
        if "reservations" in payload
        else require_runner_activation_invocation_reservation
    )
    with pytest.raises(ValueError, match="fields must match exactly"):
        validator(payload)

    missing = factory()
    assert isinstance(missing, dict)
    missing.pop("service")
    with pytest.raises(ValueError, match="fields must match exactly"):
        validator(missing)


def test_ledger_returns_a_deeply_detached_normalized_copy() -> None:
    first, second, payload = _full_ledger()
    normalized = require_runner_activation_invocation_ledger(payload)

    assert normalized == payload
    assert normalized is not payload
    assert normalized["reservations"] is not payload["reservations"]
    normalized_reservations = normalized["reservations"]
    payload_reservations = payload["reservations"]
    assert isinstance(normalized_reservations, list)
    assert isinstance(payload_reservations, list)
    assert normalized_reservations[0] is not payload_reservations[0]
    assert normalized_reservations[1] is not payload_reservations[1]

    first["targetFingerprint"] = "sha256:" + "9" * 64
    second["invocationId"] = "0" * 32
    payload_reservations.clear()
    assert len(normalized_reservations) == 2
    assert normalized_reservations[0]["targetFingerprint"] == (TARGET_FINGERPRINT)
    assert normalized_reservations[1]["invocationId"] == (SECOND_INVOCATION_ID)


def test_ledger_requires_contiguous_revision_and_hash_chain() -> None:
    first, second, _ledger = _full_ledger()

    with pytest.raises(ValueError, match="must begin at revision 1"):
        build_runner_activation_invocation_ledger([second])

    skipped_revision = deepcopy(second)
    skipped_revision["revision"] = 3
    with pytest.raises(ValueError, match="not contiguous"):
        build_runner_activation_invocation_ledger([first, skipped_revision])

    detached_predecessor = deepcopy(second)
    detached_predecessor["previousReservationFingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="not contiguous"):
        build_runner_activation_invocation_ledger([first, detached_predecessor])


@pytest.mark.parametrize("field", ["activationId", "invocationId"])
def test_ledger_rejects_globally_reused_identity(field: str) -> None:
    first = _reservation()
    values = {
        "activation_id": SECOND_ACTIVATION_ID,
        "generation_id": SECOND_GENERATION_ID,
        "invocation_id": SECOND_INVOCATION_ID,
    }
    values["activation_id" if field == "activationId" else "invocation_id"] = str(
        first[field]
    )
    second = _reservation(
        **values,
        previous_reservation=first,
        observed_transition_fingerprint=(SECOND_OBSERVED_TRANSITION_FINGERPRINT),
        target_fingerprint=SECOND_TARGET_FINGERPRINT,
    )

    with pytest.raises(ValueError, match="reused identity"):
        build_runner_activation_invocation_ledger([first, second])


@pytest.mark.parametrize(
    "reservations",
    [
        "not-a-sequence",
        b"not-a-sequence",
        {"0": "not-a-reservation"},
        [None],
        [[]],
    ],
)
def test_ledger_rejects_malformed_reservation_sequences(
    reservations: object,
) -> None:
    payload = build_empty_runner_activation_invocation_ledger()
    payload["reservations"] = reservations

    with pytest.raises(ValueError, match="invocation ledger|reservation"):
        require_runner_activation_invocation_ledger(payload)


def test_prior_ledger_binds_head_and_rejects_reused_activation() -> None:
    _first, _second, ledger = _full_ledger()

    fingerprint, invocation_ids = require_runner_activation_prior_invocation_ledger(
        ledger,
        activation_id="0" * 32,
    )
    assert fingerprint == runner_activation_invocation_ledger_fingerprint(ledger)
    assert invocation_ids == frozenset({INVOCATION_ID, SECOND_INVOCATION_ID})

    with pytest.raises(ValueError, match="reused.*activationId"):
        require_runner_activation_prior_invocation_ledger(
            ledger,
            activation_id=ACTIVATION_ID,
        )


def test_lineage_invocations_must_already_be_reserved() -> None:
    reserved = frozenset({INVOCATION_ID, SECOND_INVOCATION_ID})
    require_runner_activation_lineage_invocations_reserved(
        (INVOCATION_ID, "", SECOND_INVOCATION_ID),
        reserved_invocation_ids=reserved,
    )

    with pytest.raises(ValueError, match="ledger is incomplete"):
        require_runner_activation_lineage_invocations_reserved(
            (INVOCATION_ID, "0" * 32),
            reserved_invocation_ids=reserved,
        )
    with pytest.raises(ValueError, match="lineage invocations are invalid"):
        require_runner_activation_lineage_invocations_reserved(
            [INVOCATION_ID],
            reserved_invocation_ids=reserved,
        )


def test_expected_reservation_fingerprint_is_the_exact_next_entry() -> None:
    first, second, _ledger = _full_ledger()
    empty = build_empty_runner_activation_invocation_ledger()
    prior = build_runner_activation_invocation_ledger([first])

    assert runner_activation_expected_invocation_reservation_fingerprint(
        empty,
        activation_id=ACTIVATION_ID,
        generation_id=GENERATION_ID,
        invocation_id=INVOCATION_ID,
        observed_transition_fingerprint=(OBSERVED_TRANSITION_FINGERPRINT),
        systemd_unit=f"h2ometa-remote@{ACTIVATION_ID}.service",
        target_fingerprint=TARGET_FINGERPRINT,
    ) == runner_activation_invocation_reservation_fingerprint(first)
    assert runner_activation_expected_invocation_reservation_fingerprint(
        prior,
        **_second_binding_kwargs(),
    ) == runner_activation_invocation_reservation_fingerprint(second)


def test_wrong_prior_head_cannot_validate_as_the_exact_next_entry() -> None:
    first, second, ledger = _full_ledger()
    wrong_prior = build_empty_runner_activation_invocation_ledger()

    wrong_expected = runner_activation_expected_invocation_reservation_fingerprint(
        wrong_prior,
        **_second_binding_kwargs(),
    )
    assert wrong_expected != (
        runner_activation_invocation_reservation_fingerprint(second)
    )
    with pytest.raises(ValueError, match="binding is invalid"):
        require_runner_activation_invocation_reservation_binding(
            build_runner_activation_invocation_ledger([first]),
            **_second_binding_kwargs(),
        )

    malformed_head = deepcopy(ledger)
    reservations = malformed_head["reservations"]
    assert isinstance(reservations, list)
    reservations[-1]["previousReservationFingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="not contiguous"):
        runner_activation_expected_invocation_reservation_fingerprint(
            malformed_head,
            activation_id="0" * 32,
            generation_id="1" * 32,
            invocation_id="2" * 32,
            observed_transition_fingerprint="sha256:" + "5" * 64,
            systemd_unit="h2ometa-remote@" + "0" * 32 + ".service",
            target_fingerprint="sha256:" + "6" * 64,
        )


def test_reservation_binding_returns_the_exact_ledger_entry() -> None:
    _first, second, ledger = _full_ledger()

    assert require_runner_activation_invocation_reservation_binding(
        ledger,
        **_second_binding_kwargs(),
    ) == runner_activation_invocation_reservation_fingerprint(second)


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("activation_id", "0" * 32),
        (
            "observed_transition_fingerprint",
            "sha256:" + "5" * 64,
        ),
        ("target_fingerprint", "sha256:" + "6" * 64),
    ],
)
def test_reservation_binding_rejects_wrong_activation_or_observation(
    field: str,
    wrong_value: str,
) -> None:
    _first, _second, ledger = _full_ledger()
    binding = _second_binding_kwargs()
    binding[field] = wrong_value

    with pytest.raises(ValueError, match="binding is invalid"):
        require_runner_activation_invocation_reservation_binding(
            ledger,
            **binding,
        )


def test_validators_use_the_callers_custom_error_type() -> None:
    def make_error(message: str) -> InvocationLedgerError:
        return InvocationLedgerError(f"custom: {message}")

    malformed = build_empty_runner_activation_invocation_ledger()
    malformed["reservations"] = "invalid"
    with pytest.raises(InvocationLedgerError, match="^custom:"):
        require_runner_activation_invocation_ledger(
            malformed,
            make_error=make_error,
        )
    with pytest.raises(InvocationLedgerError, match="^custom:"):
        runner_activation_invocation_ledger_fingerprint(
            malformed,
            make_error=make_error,
        )
    with pytest.raises(InvocationLedgerError, match="^custom:"):
        require_runner_activation_lineage_invocations_reserved(
            ("0" * 32,),
            reserved_invocation_ids=frozenset(),
            make_error=make_error,
        )
    with pytest.raises(InvocationLedgerError, match="^custom:"):
        runner_activation_expected_invocation_reservation_fingerprint(
            malformed,
            **_second_binding_kwargs(),
            make_error=make_error,
        )
    with pytest.raises(InvocationLedgerError, match="^custom:"):
        require_runner_activation_invocation_reservation_binding(
            build_empty_runner_activation_invocation_ledger(),
            **_second_binding_kwargs(),
            make_error=make_error,
        )
