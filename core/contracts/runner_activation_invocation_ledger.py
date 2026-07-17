"""Append-only reservations for globally unique systemd InvocationIDs.

The control plane must load the complete ledger from its trusted no-replace
journal.  These pure validators prove internal continuity and exact bindings;
they cannot prove that an untrusted caller supplied the authoritative head.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

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


RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA = (
    "h2ometa.runner-activation-invocation-ledger.v1"
)
RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA = (
    "h2ometa.runner-activation-invocation-reservation.v1"
)
RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE = "h2ometa-remote"

_LEDGER_FIELDS = frozenset({"reservations", "schemaVersion", "service"})
_RESERVATION_FIELDS = frozenset(
    {
        "activationId",
        "generationId",
        "invocationId",
        "observedTransitionFingerprint",
        "previousReservationFingerprint",
        "revision",
        "schemaVersion",
        "service",
        "systemdUnit",
        "targetFingerprint",
    }
)
_LEDGER_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA.encode("ascii")
_RESERVATION_FINGERPRINT_DOMAIN = (
    RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA.encode("ascii")
)


def build_empty_runner_activation_invocation_ledger() -> dict[str, object]:
    return {
        "reservations": [],
        "schemaVersion": RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA,
        "service": RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
    }


def build_runner_activation_invocation_reservation(
    *,
    activation_id: object,
    generation_id: object,
    invocation_id: object,
    observed_transition_fingerprint: object,
    systemd_unit: object,
    target_fingerprint: object,
    previous_reservation: object | None = None,
) -> dict[str, object]:
    """Build one reservation appended to the authoritative journal ledger."""

    if previous_reservation is None:
        revision = 1
        previous_fingerprint = ""
    else:
        previous = require_runner_activation_invocation_reservation(
            previous_reservation
        )
        revision = int(previous["revision"]) + 1
        previous_fingerprint = runner_activation_invocation_reservation_fingerprint(
            previous
        )
    return require_runner_activation_invocation_reservation(
        {
            "activationId": activation_id,
            "generationId": generation_id,
            "invocationId": invocation_id,
            "observedTransitionFingerprint": observed_transition_fingerprint,
            "previousReservationFingerprint": previous_fingerprint,
            "revision": revision,
            "schemaVersion": (RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA),
            "service": RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
            "systemdUnit": systemd_unit,
            "targetFingerprint": target_fingerprint,
        }
    )


def require_runner_activation_invocation_reservation(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    mapping = _require_mapping(
        payload,
        expected=_RESERVATION_FIELDS,
        context="runner activation invocation reservation",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA,
        field="invocationReservation.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
        field="invocationReservation.service",
        make_error=make_error,
    )
    activation_id = _require_id(
        mapping.get("activationId"),
        "invocationReservation.activationId",
        make_error,
    )
    generation_id = _require_id(
        mapping.get("generationId"),
        "invocationReservation.generationId",
        make_error,
    )
    invocation_id = _require_id(
        mapping.get("invocationId"),
        "invocationReservation.invocationId",
        make_error,
    )
    if len({activation_id, generation_id, invocation_id}) != 3:
        raise make_error(
            "runner activation invocation reservation identities must be distinct"
        )
    revision = _require_positive_integer(
        mapping.get("revision"),
        "invocationReservation.revision",
        make_error,
    )
    previous_fingerprint = _require_optional_fingerprint(
        mapping.get("previousReservationFingerprint"),
        "invocationReservation.previousReservationFingerprint",
        make_error,
    )
    if (revision == 1 and previous_fingerprint) or (
        revision > 1 and not previous_fingerprint
    ):
        raise make_error(
            "runner activation invocation reservation predecessor is invalid"
        )
    expected_unit = f"h2ometa-remote@{activation_id}.service"
    _require_exact_string(
        mapping.get("systemdUnit"),
        expected=expected_unit,
        field="invocationReservation.systemdUnit",
        make_error=make_error,
    )
    return {
        "activationId": activation_id,
        "generationId": generation_id,
        "invocationId": invocation_id,
        "observedTransitionFingerprint": _require_fingerprint(
            mapping.get("observedTransitionFingerprint"),
            "invocationReservation.observedTransitionFingerprint",
            make_error,
        ),
        "previousReservationFingerprint": previous_fingerprint,
        "revision": revision,
        "schemaVersion": RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA,
        "service": RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
        "systemdUnit": expected_unit,
        "targetFingerprint": _require_fingerprint(
            mapping.get("targetFingerprint"),
            "invocationReservation.targetFingerprint",
            make_error,
        ),
    }


def runner_activation_invocation_reservation_fingerprint(
    payload: object,
) -> str:
    normalized = require_runner_activation_invocation_reservation(payload)
    return _fingerprint(
        _RESERVATION_FINGERPRINT_DOMAIN,
        _canonical_json(normalized),
    )


def build_runner_activation_invocation_ledger(
    reservations: object,
) -> dict[str, object]:
    return require_runner_activation_invocation_ledger(
        {
            "reservations": reservations,
            "schemaVersion": RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA,
            "service": RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
        }
    )


def require_runner_activation_invocation_ledger(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    mapping = _require_mapping(
        payload,
        expected=_LEDGER_FIELDS,
        context="runner activation invocation ledger",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA,
        field="invocationLedger.schemaVersion",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("service"),
        expected=RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
        field="invocationLedger.service",
        make_error=make_error,
    )
    reservations = mapping.get("reservations")
    if not isinstance(reservations, Sequence) or isinstance(
        reservations,
        (str, bytes, bytearray),
    ):
        raise make_error("runner activation invocation ledger is invalid")
    normalized: list[dict[str, object]] = []
    activation_ids: set[str] = set()
    invocation_ids: set[str] = set()
    for index, value in enumerate(reservations):
        reservation = require_runner_activation_invocation_reservation(
            value,
            make_error=make_error,
        )
        if index == 0:
            if reservation["revision"] != 1:
                raise make_error(
                    "runner activation invocation ledger must begin at revision 1"
                )
        else:
            previous = normalized[-1]
            if reservation["revision"] != int(previous["revision"]) + 1 or reservation[
                "previousReservationFingerprint"
            ] != runner_activation_invocation_reservation_fingerprint(previous):
                raise make_error(
                    "runner activation invocation ledger is not contiguous"
                )
        activation_id = str(reservation["activationId"])
        invocation_id = str(reservation["invocationId"])
        if activation_id in activation_ids or invocation_id in invocation_ids:
            raise make_error(
                "runner activation invocation ledger contains a reused identity"
            )
        activation_ids.add(activation_id)
        invocation_ids.add(invocation_id)
        normalized.append(reservation)
    return {
        "reservations": normalized,
        "schemaVersion": RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA,
        "service": RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
    }


def runner_activation_invocation_ledger_fingerprint(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    normalized = require_runner_activation_invocation_ledger(
        payload,
        make_error=make_error,
    )
    return _fingerprint(
        _LEDGER_FINGERPRINT_DOMAIN,
        _canonical_json(normalized),
    )


def runner_activation_invocation_ledger_identity_sets(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> tuple[frozenset[str], frozenset[str]]:
    normalized = require_runner_activation_invocation_ledger(
        payload,
        make_error=make_error,
    )
    reservations = normalized["reservations"]
    if not isinstance(reservations, list):  # pragma: no cover - validator invariant.
        raise make_error("runner activation invocation ledger is invalid")
    return (
        frozenset(str(item["activationId"]) for item in reservations),
        frozenset(str(item["invocationId"]) for item in reservations),
    )


def require_runner_activation_prior_invocation_ledger(
    payload: object,
    *,
    activation_id: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> tuple[str, frozenset[str]]:
    """Validate and bind the authoritative ledger before a new activation."""

    normalized_activation_id = _require_id(
        activation_id,
        "invocationLedger.activationId",
        make_error,
    )
    ledger = require_runner_activation_invocation_ledger(
        payload,
        make_error=make_error,
    )
    activation_ids, invocation_ids = runner_activation_invocation_ledger_identity_sets(
        ledger,
        make_error=make_error,
    )
    if normalized_activation_id in activation_ids:
        raise make_error("runner activation reused an invocation-ledger activationId")
    return (
        runner_activation_invocation_ledger_fingerprint(
            ledger,
            make_error=make_error,
        ),
        invocation_ids,
    )


def require_runner_activation_lineage_invocations_reserved(
    lineage_invocation_ids: object,
    *,
    reserved_invocation_ids: frozenset[str],
    make_error: Callable[[str], Exception] = ValueError,
) -> None:
    if not isinstance(lineage_invocation_ids, tuple) or any(
        not isinstance(invocation_id, str) for invocation_id in lineage_invocation_ids
    ):
        raise make_error("runner activation lineage invocations are invalid")
    if any(
        invocation_id and invocation_id not in reserved_invocation_ids
        for invocation_id in lineage_invocation_ids
    ):
        raise make_error("runner activation prior invocation ledger is incomplete")


def runner_activation_expected_invocation_reservation_fingerprint(
    prior_ledger: object,
    *,
    activation_id: object,
    generation_id: object,
    invocation_id: object,
    observed_transition_fingerprint: object,
    systemd_unit: object,
    target_fingerprint: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Derive the only valid next reservation from a trusted prior ledger."""

    ledger = require_runner_activation_invocation_ledger(
        prior_ledger,
        make_error=make_error,
    )
    reservations = ledger["reservations"]
    if not isinstance(reservations, list):  # pragma: no cover - invariant.
        raise make_error("runner activation invocation ledger is invalid")
    previous = reservations[-1] if reservations else None
    if previous is None:
        revision = 1
        previous_fingerprint = ""
    else:
        revision = int(previous["revision"]) + 1
        previous_fingerprint = runner_activation_invocation_reservation_fingerprint(
            previous
        )
    reservation = require_runner_activation_invocation_reservation(
        {
            "activationId": activation_id,
            "generationId": generation_id,
            "invocationId": invocation_id,
            "observedTransitionFingerprint": observed_transition_fingerprint,
            "previousReservationFingerprint": previous_fingerprint,
            "revision": revision,
            "schemaVersion": (RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA),
            "service": RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE,
            "systemdUnit": systemd_unit,
            "targetFingerprint": target_fingerprint,
        },
        make_error=make_error,
    )
    return runner_activation_invocation_reservation_fingerprint(reservation)


def require_runner_activation_invocation_reservation_binding(
    ledger_payload: object,
    *,
    activation_id: object,
    generation_id: object,
    invocation_id: object,
    observed_transition_fingerprint: object,
    systemd_unit: object,
    target_fingerprint: object,
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    """Require one ledger entry to bind the exact activation observation."""

    ledger = require_runner_activation_invocation_ledger(
        ledger_payload,
        make_error=make_error,
    )
    reservations = ledger["reservations"]
    if not isinstance(reservations, list):  # pragma: no cover - invariant.
        raise make_error("runner activation invocation ledger is invalid")
    expected = {
        "activationId": activation_id,
        "generationId": generation_id,
        "invocationId": invocation_id,
        "observedTransitionFingerprint": observed_transition_fingerprint,
        "systemdUnit": systemd_unit,
        "targetFingerprint": target_fingerprint,
    }
    matching = [
        reservation
        for reservation in reservations
        if reservation["invocationId"] == invocation_id
    ]
    if len(matching) != 1 or any(
        matching[0][field] != value for field, value in expected.items()
    ):
        raise make_error("runner activation invocation reservation binding is invalid")
    return runner_activation_invocation_reservation_fingerprint(matching[0])


__all__ = [
    "RUNNER_ACTIVATION_INVOCATION_LEDGER_SCHEMA",
    "RUNNER_ACTIVATION_INVOCATION_LEDGER_SERVICE",
    "RUNNER_ACTIVATION_INVOCATION_RESERVATION_SCHEMA",
    "build_empty_runner_activation_invocation_ledger",
    "build_runner_activation_invocation_ledger",
    "build_runner_activation_invocation_reservation",
    "require_runner_activation_invocation_ledger",
    "require_runner_activation_invocation_reservation_binding",
    "require_runner_activation_invocation_reservation",
    "require_runner_activation_lineage_invocations_reserved",
    "require_runner_activation_prior_invocation_ledger",
    "runner_activation_invocation_ledger_fingerprint",
    "runner_activation_invocation_ledger_identity_sets",
    "runner_activation_invocation_reservation_fingerprint",
    "runner_activation_expected_invocation_reservation_fingerprint",
]
