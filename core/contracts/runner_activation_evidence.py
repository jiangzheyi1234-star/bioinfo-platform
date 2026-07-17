"""Exact, secret-free proof references for activation transitions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from .runner_activation_invocation_ledger import (
    require_runner_activation_invocation_reservation,
    require_runner_activation_invocation_reservation_binding,
    runner_activation_expected_invocation_reservation_fingerprint,
    runner_activation_invocation_reservation_fingerprint,
)

from .runner_activation_validation import require_optional_fingerprint


RUNNER_ACTIVATION_EVIDENCE_SCHEMA = "h2ometa.runner-activation-evidence.v1"

_EVIDENCE_FIELDS = frozenset(
    {
        "activationVerificationFingerprint",
        "authenticatedReadinessFingerprint",
        "invocationReservationFingerprint",
        "lifecycleGuardReleaseFingerprint",
        "processOwnerFingerprint",
        "schemaVersion",
        "systemdObservationFingerprint",
    }
)
_VERIFICATION_FIELDS = (
    "activationVerificationFingerprint",
    "authenticatedReadinessFingerprint",
    "invocationReservationFingerprint",
    "processOwnerFingerprint",
    "systemdObservationFingerprint",
)


def build_empty_runner_activation_evidence() -> dict[str, str]:
    return {
        "activationVerificationFingerprint": "",
        "authenticatedReadinessFingerprint": "",
        "invocationReservationFingerprint": "",
        "lifecycleGuardReleaseFingerprint": "",
        "processOwnerFingerprint": "",
        "schemaVersion": RUNNER_ACTIVATION_EVIDENCE_SCHEMA,
        "systemdObservationFingerprint": "",
    }


def require_runner_activation_evidence(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        raise make_error("runner activation evidence must be an object")
    if frozenset(payload.keys()) != _EVIDENCE_FIELDS:
        raise make_error("runner activation evidence fields must match exactly")
    if payload.get("schemaVersion") != RUNNER_ACTIVATION_EVIDENCE_SCHEMA:
        raise make_error("runner activation evidence schemaVersion is invalid")
    normalized = build_empty_runner_activation_evidence()
    for field in _EVIDENCE_FIELDS - {"schemaVersion"}:
        normalized[field] = require_optional_fingerprint(
            payload.get(field),
            f"evidence.{field}",
            make_error,
        )
    return normalized


def require_runner_activation_evidence_for_transition(
    payload: object,
    *,
    from_state: str,
    to_state: str,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, str]:
    evidence = require_runner_activation_evidence(
        payload,
        make_error=make_error,
    )
    populated = {
        field for field, value in evidence.items() if field != "schemaVersion" and value
    }
    verification = set(_VERIFICATION_FIELDS)
    guard_release = "lifecycleGuardReleaseFingerprint"
    if to_state in {"candidate_verified", "committing"}:
        if populated != verification:
            raise make_error(
                "runner activation verified transition evidence is incomplete"
            )
    elif to_state == "committed":
        if populated != verification | {guard_release}:
            raise make_error(
                "runner activation committed transition evidence is incomplete"
            )
    elif to_state == "aborted":
        expected = set() if from_state == "prepared" else {guard_release}
        if populated != expected:
            raise make_error("runner activation aborted transition evidence is invalid")
    elif to_state != "recovery_required" and populated:
        raise make_error("runner activation transition has premature evidence")
    return evidence


def runner_activation_verification_binding(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> tuple[str, ...]:
    evidence = require_runner_activation_evidence(
        payload,
        make_error=make_error,
    )
    return tuple(evidence[field] for field in _VERIFICATION_FIELDS)


def require_runner_activation_invocation_reservation_evidence(
    transitions: Sequence[dict[str, object]],
    *,
    target: dict[str, object],
    prior_invocation_ledger: object,
    current_invocation_reservation: object | None,
    transition_fingerprint: Callable[[object], str],
    target_fingerprint: Callable[[object], str],
    make_error: Callable[[str], Exception] = ValueError,
) -> None:
    observed = next(
        (transition for transition in transitions if transition["systemdInvocationId"]),
        None,
    )
    if observed is None:
        if current_invocation_reservation is not None:
            raise make_error(
                "runner activation has a reservation without an invocation"
            )
        return
    expected = runner_activation_expected_invocation_reservation_fingerprint(
        prior_invocation_ledger,
        activation_id=target["activationId"],
        generation_id=target["generation"]["generationId"],
        invocation_id=observed["systemdInvocationId"],
        observed_transition_fingerprint=transition_fingerprint(observed),
        systemd_unit=target["systemdUnit"],
        target_fingerprint=target_fingerprint(target),
        make_error=make_error,
    )
    supplied_fingerprint = ""
    if current_invocation_reservation is not None:
        supplied = require_runner_activation_invocation_reservation(
            current_invocation_reservation,
            make_error=make_error,
        )
        supplied_fingerprint = runner_activation_invocation_reservation_fingerprint(
            supplied
        )
        if supplied_fingerprint != expected:
            raise make_error(
                "runner activation invocation reservation is not the next entry"
            )
    for transition in transitions:
        evidence = transition["evidence"]
        if not isinstance(evidence, dict):  # pragma: no cover - invariant.
            raise make_error("runner activation transition evidence is invalid")
        reservation_fingerprint = evidence["invocationReservationFingerprint"]
        if reservation_fingerprint and not supplied_fingerprint:
            raise make_error(
                "runner activation invocation reservation evidence has no entry"
            )
        if reservation_fingerprint and reservation_fingerprint != expected:
            raise make_error(
                "runner activation invocation reservation evidence mismatch"
            )


def require_runner_activation_lineage_invocation_reservation(
    prior_invocation_ledger: object,
    *,
    target: dict[str, object],
    transitions: Sequence[dict[str, object]],
    transition_fingerprint: Callable[[object], str],
    target_fingerprint: Callable[[object], str],
    make_error: Callable[[str], Exception] = ValueError,
) -> str:
    observed = next(
        (transition for transition in transitions if transition["systemdInvocationId"]),
        None,
    )
    if observed is None:
        return ""
    return require_runner_activation_invocation_reservation_binding(
        prior_invocation_ledger,
        activation_id=target["activationId"],
        generation_id=target["generation"]["generationId"],
        invocation_id=observed["systemdInvocationId"],
        observed_transition_fingerprint=transition_fingerprint(observed),
        systemd_unit=target["systemdUnit"],
        target_fingerprint=target_fingerprint(target),
        make_error=make_error,
    )


__all__ = [
    "RUNNER_ACTIVATION_EVIDENCE_SCHEMA",
    "build_empty_runner_activation_evidence",
    "require_runner_activation_evidence",
    "require_runner_activation_evidence_for_transition",
    "require_runner_activation_invocation_reservation_evidence",
    "require_runner_activation_lineage_invocation_reservation",
    "runner_activation_verification_binding",
]
