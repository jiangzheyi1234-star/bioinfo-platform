"""Recoverable remote-runner activation transition contracts.

The records bind immutable generations, unique activation targets, verified
systemd invocations, terminal proof references, and append-only lineage. They
describe evidence only; they do not mutate remote state or authenticate the
runner OS identity by themselves.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .runner_activation_evidence import (
    RUNNER_ACTIVATION_EVIDENCE_SCHEMA,
    build_empty_runner_activation_evidence,
    require_runner_activation_evidence_for_transition,
    require_runner_activation_invocation_reservation_evidence,
    require_runner_activation_lineage_invocation_reservation,
    runner_activation_verification_binding,
)
from .runner_activation_invocation_ledger import (
    require_runner_activation_prior_invocation_ledger,
)
from .runner_activation_state import (
    RUNNER_ACTIVATION_INITIAL_STATE,
    RUNNER_ACTIVATION_INVOCATION_FORBIDDEN_STATES,
    RUNNER_ACTIVATION_INVOCATION_REQUIRED_STATES,
    RUNNER_ACTIVATION_STATES,
    RUNNER_ACTIVATION_TERMINAL_STATES,
    require_legal_runner_activation_transition,
    require_runner_activation_embedded_lineage_shape,
    require_runner_activation_state,
)
from .runner_activation_target import (
    RUNNER_ACTIVATION_GENERATION_SCHEMA,
    RUNNER_ACTIVATION_GUARD_OWNER_TEMPLATE,
    RUNNER_ACTIVATION_OPERATIONS,
    RUNNER_ACTIVATION_SERVICE,
    RUNNER_ACTIVATION_TARGET_SCHEMA,
    RUNNER_ACTIVATION_UNIT_TEMPLATE,
    RUNNER_ACTIVATION_UNIT_TEMPLATE_FILENAME,
    build_runner_activation_generation,
    build_runner_activation_target,
    require_runner_activation_generation,
    require_runner_activation_target,
    runner_activation_generation_canonical_json,
    runner_activation_generation_fingerprint,
    runner_activation_target_canonical_json,
    runner_activation_target_fingerprint,
)
from .runner_activation_validation import (
    canonical_json as _canonical_json,
    fingerprint as _fingerprint,
    require_exact_string as _require_exact_string,
    require_fingerprint as _require_fingerprint,
    require_id as _require_id,
    require_mapping as _require_mapping,
    require_optional_fingerprint as _require_optional_fingerprint,
    require_optional_id as _require_optional_id,
    require_positive_integer as _require_positive_integer,
    require_token_rotation_preserves_runtime as _require_token_rotation_preserves_runtime,
)


RUNNER_ACTIVATION_TRANSITION_SCHEMA = "h2ometa.runner-activation-transition.v1"

_TRANSITION_FIELDS = frozenset(
    {
        "activationId",
        "evidence",
        "fromState",
        "generationId",
        "previousCommitFingerprint",
        "priorInvocationLedgerFingerprint",
        "previousTargetFingerprint",
        "previousTransitionFingerprint",
        "recoveryOfTransitionFingerprint",
        "revision",
        "schemaVersion",
        "systemdInvocationId",
        "targetFingerprint",
        "toState",
    }
)
_TRANSITION_FINGERPRINT_DOMAIN = RUNNER_ACTIVATION_TRANSITION_SCHEMA.encode("ascii")


def build_runner_activation_transition(
    *,
    target: object,
    prior_invocation_ledger: object,
    to_state: object,
    evidence: object | None = None,
    previous_transition: object | None = None,
    previous_target: object | None = None,
    previous_commit_chain: object | None = None,
    recovery_of_target: object | None = None,
    recovery_of_chain: object | None = None,
    systemd_invocation_id: object = "",
) -> dict[str, object]:
    """Append one legal transition bound to target, lineage, and prior hash."""

    normalized_target = require_runner_activation_target(target)
    ledger = require_runner_activation_prior_invocation_ledger(
        prior_invocation_ledger,
        activation_id=normalized_target["activationId"],
        make_error=ValueError,
    )
    target_fingerprint = runner_activation_target_fingerprint(normalized_target)
    if previous_transition is None:
        lineage = _require_activation_lineage(
            normalized_target,
            previous_target=previous_target,
            previous_commit_chain=previous_commit_chain,
            recovery_of_target=recovery_of_target,
            recovery_of_chain=recovery_of_chain,
            prior_invocation_ledger=prior_invocation_ledger,
            make_error=ValueError,
        )
        revision = 1
        from_state = RUNNER_ACTIVATION_INITIAL_STATE
        previous_transition_fingerprint = ""
        previous_target_fingerprint = lineage[0]
        previous_commit_fingerprint = lineage[1]
        recovery_of_transition_fingerprint = lineage[2]
        prior_invocation_ledger_fingerprint = ledger[0]
    else:
        previous = require_runner_activation_transition(previous_transition)
        revision = int(previous["revision"]) + 1
        from_state = str(previous["toState"])
        previous_transition_fingerprint = runner_activation_transition_fingerprint(
            previous
        )
        previous_target_fingerprint = str(previous["previousTargetFingerprint"])
        previous_commit_fingerprint = str(previous["previousCommitFingerprint"])
        recovery_of_transition_fingerprint = str(
            previous["recoveryOfTransitionFingerprint"]
        )
        prior_invocation_ledger_fingerprint = str(
            previous["priorInvocationLedgerFingerprint"]
        )
        if prior_invocation_ledger_fingerprint != ledger[0]:
            raise ValueError("runner activation prior invocation ledger binding drift")
        if (
            previous["activationId"] != normalized_target["activationId"]
            or previous["generationId"]
            != normalized_target["generation"]["generationId"]
            or previous["targetFingerprint"] != target_fingerprint
        ):
            raise ValueError("runner activation transition target binding drift")
        supplied_lineage = any(
            item is not None
            for item in (
                previous_target,
                previous_commit_chain,
                recovery_of_target,
                recovery_of_chain,
            )
        )
        if supplied_lineage:
            lineage = _require_activation_lineage(
                normalized_target,
                previous_target=previous_target,
                previous_commit_chain=previous_commit_chain,
                recovery_of_target=recovery_of_target,
                recovery_of_chain=recovery_of_chain,
                prior_invocation_ledger=prior_invocation_ledger,
                make_error=ValueError,
            )
            if lineage[:3] != (
                previous_target_fingerprint,
                previous_commit_fingerprint,
                recovery_of_transition_fingerprint,
            ):
                raise ValueError("runner activation transition lineage binding drift")
    selected_evidence = (
        build_empty_runner_activation_evidence() if evidence is None else evidence
    )
    transition = require_runner_activation_transition(
        {
            "activationId": normalized_target["activationId"],
            "evidence": selected_evidence,
            "fromState": from_state,
            "generationId": normalized_target["generation"]["generationId"],
            "previousCommitFingerprint": previous_commit_fingerprint,
            "priorInvocationLedgerFingerprint": (prior_invocation_ledger_fingerprint),
            "previousTargetFingerprint": previous_target_fingerprint,
            "previousTransitionFingerprint": previous_transition_fingerprint,
            "recoveryOfTransitionFingerprint": (recovery_of_transition_fingerprint),
            "revision": revision,
            "schemaVersion": RUNNER_ACTIVATION_TRANSITION_SCHEMA,
            "systemdInvocationId": systemd_invocation_id,
            "targetFingerprint": target_fingerprint,
            "toState": to_state,
        }
    )
    if transition["systemdInvocationId"] in ledger[1]:
        raise ValueError("runner activation reused reserved invocation")
    return transition


def require_runner_activation_transition(
    payload: object,
    *,
    make_error: Callable[[str], Exception] = ValueError,
) -> dict[str, object]:
    """Validate one transition independently of its append-only chain."""

    mapping = _require_mapping(
        payload,
        expected=_TRANSITION_FIELDS,
        context="runner activation transition",
        make_error=make_error,
    )
    _require_exact_string(
        mapping.get("schemaVersion"),
        expected=RUNNER_ACTIVATION_TRANSITION_SCHEMA,
        field="transition.schemaVersion",
        make_error=make_error,
    )
    activation_id = _require_id(
        mapping.get("activationId"), "transition.activationId", make_error
    )
    generation_id = _require_id(
        mapping.get("generationId"), "transition.generationId", make_error
    )
    if activation_id == generation_id:
        raise make_error("runner activation transition activationId must be distinct")
    revision = _require_positive_integer(
        mapping.get("revision"), "transition.revision", make_error
    )
    from_state = require_runner_activation_state(
        mapping.get("fromState"),
        allow_initial=True,
        make_error=make_error,
    )
    to_state = require_runner_activation_state(
        mapping.get("toState"),
        allow_initial=False,
        make_error=make_error,
    )
    require_legal_runner_activation_transition(
        from_state,
        to_state,
        make_error=make_error,
    )
    previous_transition_fingerprint = _require_optional_fingerprint(
        mapping.get("previousTransitionFingerprint"),
        "transition.previousTransitionFingerprint",
        make_error,
    )
    if revision == 1:
        if (
            from_state != RUNNER_ACTIVATION_INITIAL_STATE
            or to_state != "prepared"
            or previous_transition_fingerprint
        ):
            raise make_error("runner activation genesis transition is invalid")
    elif (
        from_state == RUNNER_ACTIVATION_INITIAL_STATE
        or not previous_transition_fingerprint
    ):
        raise make_error("runner activation appended transition is invalid")
    previous_target_fingerprint = _require_optional_fingerprint(
        mapping.get("previousTargetFingerprint"),
        "transition.previousTargetFingerprint",
        make_error,
    )
    previous_commit_fingerprint = _require_optional_fingerprint(
        mapping.get("previousCommitFingerprint"),
        "transition.previousCommitFingerprint",
        make_error,
    )
    prior_invocation_ledger_fingerprint = _require_fingerprint(
        mapping.get("priorInvocationLedgerFingerprint"),
        "transition.priorInvocationLedgerFingerprint",
        make_error,
    )
    recovery_of_transition_fingerprint = _require_optional_fingerprint(
        mapping.get("recoveryOfTransitionFingerprint"),
        "transition.recoveryOfTransitionFingerprint",
        make_error,
    )
    invocation_id = _require_optional_id(
        mapping.get("systemdInvocationId"),
        "transition.systemdInvocationId",
        make_error,
    )
    if to_state in RUNNER_ACTIVATION_INVOCATION_FORBIDDEN_STATES and invocation_id:
        raise make_error(
            "runner activation transition has a premature systemd invocation"
        )
    if to_state in RUNNER_ACTIVATION_INVOCATION_REQUIRED_STATES and not invocation_id:
        raise make_error("runner activation transition requires a systemd invocation")
    if invocation_id in {activation_id, generation_id}:
        raise make_error("runner activation systemdInvocationId must be distinct")
    transition_evidence = require_runner_activation_evidence_for_transition(
        mapping.get("evidence"),
        from_state=from_state,
        to_state=to_state,
        make_error=make_error,
    )
    return {
        "activationId": activation_id,
        "evidence": transition_evidence,
        "fromState": from_state,
        "generationId": generation_id,
        "previousCommitFingerprint": previous_commit_fingerprint,
        "priorInvocationLedgerFingerprint": (prior_invocation_ledger_fingerprint),
        "previousTargetFingerprint": previous_target_fingerprint,
        "previousTransitionFingerprint": previous_transition_fingerprint,
        "recoveryOfTransitionFingerprint": (recovery_of_transition_fingerprint),
        "revision": revision,
        "schemaVersion": RUNNER_ACTIVATION_TRANSITION_SCHEMA,
        "systemdInvocationId": invocation_id,
        "targetFingerprint": _require_fingerprint(
            mapping.get("targetFingerprint"),
            "transition.targetFingerprint",
            make_error,
        ),
        "toState": to_state,
    }


def runner_activation_transition_canonical_json(payload: object) -> str:
    return _canonical_json(require_runner_activation_transition(payload))


def runner_activation_transition_fingerprint(payload: object) -> str:
    return _fingerprint(
        _TRANSITION_FINGERPRINT_DOMAIN,
        runner_activation_transition_canonical_json(payload),
    )


def require_runner_activation_transition_chain(
    transitions: object,
    *,
    target: object,
    prior_invocation_ledger: object,
    current_invocation_reservation: object | None = None,
    previous_target: object | None = None,
    previous_commit_chain: object | None = None,
    recovery_of_target: object | None = None,
    recovery_of_chain: object | None = None,
    make_error: Callable[[str], Exception] = ValueError,
) -> list[dict[str, object]]:
    """Verify a non-empty, contiguous, target-bound append-only history."""

    normalized_target = require_runner_activation_target(
        target,
        make_error=make_error,
    )
    ledger = require_runner_activation_prior_invocation_ledger(
        prior_invocation_ledger,
        activation_id=normalized_target["activationId"],
        make_error=make_error,
    )
    lineage = _require_activation_lineage(
        normalized_target,
        previous_target=previous_target,
        previous_commit_chain=previous_commit_chain,
        recovery_of_target=recovery_of_target,
        recovery_of_chain=recovery_of_chain,
        prior_invocation_ledger=prior_invocation_ledger,
        make_error=make_error,
    )
    normalized = _require_target_bound_transition_chain(
        transitions,
        target=normalized_target,
        expected_lineage=lineage[:3],
        expected_invocation_ledger_fingerprint=ledger[0],
        reserved_invocation_ids=ledger[1],
        make_error=make_error,
    )
    require_runner_activation_invocation_reservation_evidence(
        normalized,
        target=normalized_target,
        prior_invocation_ledger=prior_invocation_ledger,
        current_invocation_reservation=current_invocation_reservation,
        transition_fingerprint=runner_activation_transition_fingerprint,
        target_fingerprint=runner_activation_target_fingerprint,
        make_error=make_error,
    )
    return normalized


def _require_target_bound_transition_chain(
    transitions: object,
    *,
    target: dict[str, object],
    expected_lineage: tuple[str, str, str] | None,
    expected_invocation_ledger_fingerprint: str | None,
    reserved_invocation_ids: frozenset[str],
    make_error: Callable[[str], Exception],
) -> list[dict[str, object]]:
    if (
        not isinstance(transitions, Sequence)
        or isinstance(transitions, (str, bytes, bytearray))
        or not transitions
    ):
        raise make_error("runner activation transition chain is invalid")
    expected_target_fingerprint = runner_activation_target_fingerprint(target)
    normalized: list[dict[str, object]] = []
    invocation_id = ""
    lineage = expected_lineage
    invocation_ledger_fingerprint = expected_invocation_ledger_fingerprint
    verification_binding: tuple[str, ...] | None = None
    for index, value in enumerate(transitions):
        transition = require_runner_activation_transition(
            value,
            make_error=make_error,
        )
        if index == 0 and lineage is None:
            lineage = (
                str(transition["previousTargetFingerprint"]),
                str(transition["previousCommitFingerprint"]),
                str(transition["recoveryOfTransitionFingerprint"]),
            )
        if index == 0 and invocation_ledger_fingerprint is None:
            invocation_ledger_fingerprint = str(
                transition["priorInvocationLedgerFingerprint"]
            )
            require_runner_activation_embedded_lineage_shape(
                str(target["operation"]),
                lineage=lineage,
                make_error=make_error,
            )
        if lineage is None:  # pragma: no cover - non-empty chain invariant.
            raise make_error("runner activation transition lineage is invalid")
        if (
            transition["activationId"] != target["activationId"]
            or transition["generationId"] != target["generation"]["generationId"]
            or transition["targetFingerprint"] != expected_target_fingerprint
            or transition["previousTargetFingerprint"] != lineage[0]
            or transition["previousCommitFingerprint"] != lineage[1]
            or transition["priorInvocationLedgerFingerprint"]
            != invocation_ledger_fingerprint
            or transition["recoveryOfTransitionFingerprint"] != lineage[2]
        ):
            raise make_error(
                "runner activation transition chain target binding mismatch"
            )
        if index == 0:
            if transition["revision"] != 1:
                raise make_error(
                    "runner activation transition chain must begin at revision 1"
                )
        else:
            previous = normalized[-1]
            if (
                transition["revision"] != int(previous["revision"]) + 1
                or transition["fromState"] != previous["toState"]
                or transition["previousTransitionFingerprint"]
                != runner_activation_transition_fingerprint(previous)
            ):
                raise make_error("runner activation transition chain is not contiguous")
        current_invocation_id = str(transition["systemdInvocationId"])
        if invocation_id and not current_invocation_id:
            raise make_error("runner activation candidate invocation was lost")
        if current_invocation_id:
            if current_invocation_id in reserved_invocation_ids:
                raise make_error("runner activation reused reserved invocation")
            if invocation_id and current_invocation_id != invocation_id:
                raise make_error("runner activation candidate invocation changed")
            invocation_id = current_invocation_id
        to_state = str(transition["toState"])
        if to_state in {"candidate_verified", "committing", "committed"}:
            current_binding = runner_activation_verification_binding(
                transition["evidence"],
                make_error=make_error,
            )
            if verification_binding and current_binding != verification_binding:
                raise make_error("runner activation verification evidence changed")
            verification_binding = current_binding
        normalized.append(transition)
    return normalized


def _require_trusted_journal_chain(
    transitions: object,
    *,
    target: dict[str, object],
    terminal_state: str,
    make_error: Callable[[str], Exception],
) -> list[dict[str, object]]:
    """Validate a complete chain loaded from the trusted no-replace journal."""

    normalized = _require_target_bound_transition_chain(
        transitions,
        target=target,
        expected_lineage=None,
        expected_invocation_ledger_fingerprint=None,
        reserved_invocation_ids=frozenset(),
        make_error=make_error,
    )
    if normalized[-1]["toState"] != terminal_state:
        raise make_error("runner activation journal chain has the wrong terminal head")
    return normalized


def _require_activation_lineage(
    target: dict[str, object],
    *,
    previous_target: object | None,
    previous_commit_chain: object | None,
    recovery_of_target: object | None,
    recovery_of_chain: object | None,
    prior_invocation_ledger: object,
    make_error: Callable[[str], Exception],
) -> tuple[str, str, str, str, str]:
    operation = str(target["operation"])
    if previous_target is None:
        if operation in {"upgrade", "token_rotation", "rollback"}:
            raise make_error(
                f"runner activation {operation} requires a previous target"
            )
        if previous_commit_chain is not None:
            raise make_error("runner activation previous commit has no target")
        previous = None
        previous_target_fingerprint = ""
        previous_commit_fingerprint = ""
        previous_invocation_id = ""
    else:
        if operation == "install":
            raise make_error(
                "runner activation install must not have a previous target"
            )
        previous = require_runner_activation_target(
            previous_target,
            make_error=make_error,
        )
        _require_previous_target_compatibility(
            target,
            previous,
            make_error=make_error,
        )
        if previous_commit_chain is None:
            raise make_error(
                "runner activation previous target requires a committed chain"
            )
        previous_chain = _require_trusted_journal_chain(
            previous_commit_chain,
            target=previous,
            terminal_state="committed",
            make_error=make_error,
        )
        previous_commit = previous_chain[-1]
        previous_target_fingerprint = runner_activation_target_fingerprint(previous)
        if (
            previous_commit["toState"] != "committed"
            or previous_commit["activationId"] != previous["activationId"]
            or previous_commit["generationId"] != previous["generation"]["generationId"]
            or previous_commit["targetFingerprint"] != previous_target_fingerprint
        ):
            raise make_error(
                "runner activation previous commit does not bind its target"
            )
        previous_commit_fingerprint = runner_activation_transition_fingerprint(
            previous_commit
        )
        previous_invocation_id = str(previous_commit["systemdInvocationId"])
        require_runner_activation_lineage_invocation_reservation(
            prior_invocation_ledger,
            target=previous,
            transitions=previous_chain,
            transition_fingerprint=runner_activation_transition_fingerprint,
            target_fingerprint=runner_activation_target_fingerprint,
            make_error=make_error,
        )
    recovery = _require_recovery_lineage(
        target,
        previous=previous,
        previous_target_fingerprint=previous_target_fingerprint,
        previous_commit_fingerprint=previous_commit_fingerprint,
        previous_invocation_id=previous_invocation_id,
        recovery_of_target=recovery_of_target,
        recovery_of_chain=recovery_of_chain,
        prior_invocation_ledger=prior_invocation_ledger,
        make_error=make_error,
    )
    return (
        previous_target_fingerprint,
        previous_commit_fingerprint,
        recovery[0],
        previous_invocation_id,
        recovery[1],
    )


def _require_previous_target_compatibility(
    target: dict[str, object],
    previous: dict[str, object],
    *,
    make_error: Callable[[str], Exception],
) -> None:
    operation = str(target["operation"])
    if previous["activationId"] == target["activationId"]:
        raise make_error(
            "runner activation previous target must use another activationId"
        )
    if previous["currentLinkPath"] != target["currentLinkPath"]:
        raise make_error(
            "runner activation previous target belongs to another runner root"
        )
    if previous["systemdUnitTemplatePath"] != target["systemdUnitTemplatePath"]:
        raise make_error("runner activation previous target uses another unit template")
    if operation == "upgrade" and (
        previous["generation"]["generationId"] == target["generation"]["generationId"]
    ):
        raise make_error("runner activation upgrade requires a new generation")
    if operation == "token_rotation":
        _require_token_rotation_preserves_runtime(
            target,
            previous,
            make_error=make_error,
        )


def _require_recovery_lineage(
    target: dict[str, object],
    *,
    previous: dict[str, object] | None,
    previous_target_fingerprint: str,
    previous_commit_fingerprint: str,
    previous_invocation_id: str,
    recovery_of_target: object | None,
    recovery_of_chain: object | None,
    prior_invocation_ledger: object,
    make_error: Callable[[str], Exception],
) -> tuple[str, str]:
    if target["operation"] != "rollback":
        if recovery_of_target is not None or recovery_of_chain is not None:
            raise make_error("runner activation non-rollback has recovery lineage")
        return "", ""
    if previous is None:  # pragma: no cover - operation invariant.
        raise make_error("runner activation rollback has no previous target")
    if target["generation"] != previous["generation"]:
        raise make_error(
            "runner activation rollback must restore the previous generation"
        )
    if recovery_of_target is None or recovery_of_chain is None:
        raise make_error(
            "runner activation rollback requires failed activation evidence"
        )
    failed_target = require_runner_activation_target(
        recovery_of_target,
        make_error=make_error,
    )
    failed_chain = _require_trusted_journal_chain(
        recovery_of_chain,
        target=failed_target,
        terminal_state="recovery_required",
        make_error=make_error,
    )
    failed_transition = failed_chain[-1]
    failed_invocation_id = str(failed_transition["systemdInvocationId"])
    require_runner_activation_lineage_invocation_reservation(
        prior_invocation_ledger,
        target=failed_target,
        transitions=failed_chain,
        transition_fingerprint=runner_activation_transition_fingerprint,
        target_fingerprint=runner_activation_target_fingerprint,
        make_error=make_error,
    )
    if (
        failed_target["activationId"]
        in {target["activationId"], previous["activationId"]}
        or failed_target["currentLinkPath"] != target["currentLinkPath"]
        or failed_transition["toState"] != "recovery_required"
        or failed_transition["activationId"] != failed_target["activationId"]
        or failed_transition["targetFingerprint"]
        != runner_activation_target_fingerprint(failed_target)
        or failed_transition["previousTargetFingerprint"] != previous_target_fingerprint
        or failed_transition["previousCommitFingerprint"] != previous_commit_fingerprint
        or (failed_invocation_id and failed_invocation_id == previous_invocation_id)
    ):
        raise make_error("runner activation rollback failed evidence is invalid")
    return (
        runner_activation_transition_fingerprint(failed_transition),
        failed_invocation_id,
    )


__all__ = [
    "RUNNER_ACTIVATION_EVIDENCE_SCHEMA",
    "RUNNER_ACTIVATION_GENERATION_SCHEMA",
    "RUNNER_ACTIVATION_GUARD_OWNER_TEMPLATE",
    "RUNNER_ACTIVATION_INITIAL_STATE",
    "RUNNER_ACTIVATION_OPERATIONS",
    "RUNNER_ACTIVATION_SERVICE",
    "RUNNER_ACTIVATION_STATES",
    "RUNNER_ACTIVATION_TARGET_SCHEMA",
    "RUNNER_ACTIVATION_TERMINAL_STATES",
    "RUNNER_ACTIVATION_TRANSITION_SCHEMA",
    "RUNNER_ACTIVATION_UNIT_TEMPLATE",
    "RUNNER_ACTIVATION_UNIT_TEMPLATE_FILENAME",
    "build_empty_runner_activation_evidence",
    "build_runner_activation_generation",
    "build_runner_activation_target",
    "build_runner_activation_transition",
    "require_runner_activation_generation",
    "require_runner_activation_target",
    "require_runner_activation_transition",
    "require_runner_activation_transition_chain",
    "runner_activation_generation_canonical_json",
    "runner_activation_generation_fingerprint",
    "runner_activation_target_canonical_json",
    "runner_activation_target_fingerprint",
    "runner_activation_transition_canonical_json",
    "runner_activation_transition_fingerprint",
]
