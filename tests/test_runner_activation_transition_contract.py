from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from core.contracts.runner_activation import (
    RUNNER_ACTIVATION_INITIAL_STATE,
    RUNNER_ACTIVATION_STATES,
    RUNNER_ACTIVATION_TERMINAL_STATES,
    RUNNER_ACTIVATION_TRANSITION_SCHEMA,
    build_empty_runner_activation_evidence,
    build_runner_activation_transition as _build_runner_activation_transition,
    require_runner_activation_transition,
    require_runner_activation_transition_chain as _require_transition_chain,
    runner_activation_target_fingerprint,
    runner_activation_transition_canonical_json,
    runner_activation_transition_fingerprint,
)
from tests.helpers.runner_activation_contract import (
    INVOCATION_ID,
    PREVIOUS_INVOCATION_ID,
    append_chain,
    chain_invocation_reservation,
    committed_install,
    empty_invocation_ledger,
    generation,
    invocation_ledger_for_chains,
    target,
    verification_evidence,
)


FULL_COMMIT_STATES = [
    "prepared",
    "guarded",
    "stopping",
    "stopped",
    "promoting",
    "promoted",
    "starting",
    "verifying",
    "candidate_verified",
    "committing",
    "committed",
]


def build_runner_activation_transition(**kwargs: object) -> dict[str, object]:
    kwargs.setdefault("prior_invocation_ledger", empty_invocation_ledger())
    return _build_runner_activation_transition(**kwargs)


def require_runner_activation_transition_chain(
    transitions: object,
    **kwargs: object,
) -> list[dict[str, object]]:
    kwargs.setdefault("prior_invocation_ledger", empty_invocation_ledger())
    return _require_transition_chain(transitions, **kwargs)


def _lineage(
    previous_target: object,
    previous_chain: object,
) -> dict[str, object]:
    return {
        "prior_invocation_ledger": invocation_ledger_for_chains(
            (previous_target, previous_chain),
        ),
        "previous_target": previous_target,
        "previous_commit_chain": previous_chain,
    }


def _failed_upgrade() -> tuple[
    dict[str, object],
    list[dict[str, object]],
    dict[str, object],
    list[dict[str, object]],
]:
    previous_target, previous_chain = committed_install()
    failed_target = target(operation="upgrade")
    failed_chain = append_chain(
        failed_target,
        FULL_COMMIT_STATES[:8] + ["recovery_required"],
        **_lineage(previous_target, previous_chain),
    )
    return previous_target, previous_chain, failed_target, failed_chain


def _rollback_lineage(
    previous_target: dict[str, object],
    previous_chain: list[dict[str, object]],
    failed_target: dict[str, object],
    failed_chain: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "previous_target": previous_target,
        "previous_commit_chain": previous_chain,
        "prior_invocation_ledger": invocation_ledger_for_chains(
            (previous_target, previous_chain),
            (failed_target, failed_chain),
        ),
        "recovery_of_target": failed_target,
        "recovery_of_chain": failed_chain,
    }


def test_public_transition_states_exclude_in_place_rollback() -> None:
    assert RUNNER_ACTIVATION_TRANSITION_SCHEMA == (
        "h2ometa.runner-activation-transition.v1"
    )
    assert RUNNER_ACTIVATION_INITIAL_STATE == "none"
    assert set(RUNNER_ACTIVATION_TERMINAL_STATES) == {
        "committed",
        "aborted",
        "recovery_required",
    }
    assert not {
        "rolling_back",
        "rollback_verifying",
        "rolled_back",
    }.intersection(RUNNER_ACTIVATION_STATES)


def test_install_commit_chain_is_contiguous_invocation_and_evidence_bound() -> None:
    selected_target = target()
    transitions = append_chain(selected_target, FULL_COMMIT_STATES)
    reservation = chain_invocation_reservation(
        empty_invocation_ledger(),
        selected_target,
        transitions,
    )

    with pytest.raises(ValueError, match="evidence has no entry"):
        require_runner_activation_transition_chain(
            transitions,
            target=selected_target,
        )
    mismatched_reservation = deepcopy(reservation)
    mismatched_reservation["targetFingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="not the next entry"):
        require_runner_activation_transition_chain(
            transitions,
            current_invocation_reservation=mismatched_reservation,
            target=selected_target,
        )

    normalized = require_runner_activation_transition_chain(
        transitions,
        current_invocation_reservation=reservation,
        target=selected_target,
    )
    assert normalized == transitions
    assert [item["revision"] for item in normalized] == list(
        range(1, len(FULL_COMMIT_STATES) + 1)
    )
    assert normalized[0]["fromState"] == "none"
    assert normalized[-1]["toState"] == "committed"
    assert normalized[-1]["evidence"]["lifecycleGuardReleaseFingerprint"]
    assert {
        item["systemdInvocationId"]
        for item in normalized
        if item["systemdInvocationId"]
    } == {INVOCATION_ID}
    for previous, current in zip(
        normalized[:-1],
        normalized[1:],
        strict=True,
    ):
        assert current["previousTransitionFingerprint"] == (
            runner_activation_transition_fingerprint(previous)
        )


def test_verified_and_committed_states_require_exact_proof_references() -> None:
    selected_target = target()
    before_verifying = append_chain(
        selected_target,
        FULL_COMMIT_STATES[:7],
    )[-1]
    verifying = build_runner_activation_transition(
        target=selected_target,
        to_state="verifying",
        previous_transition=before_verifying,
        systemd_invocation_id=INVOCATION_ID,
    )

    with pytest.raises(ValueError, match="evidence is incomplete"):
        build_runner_activation_transition(
            target=selected_target,
            to_state="candidate_verified",
            previous_transition=verifying,
            systemd_invocation_id=INVOCATION_ID,
        )
    unreserved_evidence = verification_evidence()
    unreserved_evidence["invocationReservationFingerprint"] = ""
    with pytest.raises(ValueError, match="evidence is incomplete"):
        build_runner_activation_transition(
            target=selected_target,
            to_state="candidate_verified",
            evidence=unreserved_evidence,
            previous_transition=verifying,
            systemd_invocation_id=INVOCATION_ID,
        )
    candidate_verified = build_runner_activation_transition(
        target=selected_target,
        to_state="candidate_verified",
        evidence=verification_evidence(),
        previous_transition=verifying,
        systemd_invocation_id=INVOCATION_ID,
    )
    committing = build_runner_activation_transition(
        target=selected_target,
        to_state="committing",
        evidence=verification_evidence(),
        previous_transition=candidate_verified,
        systemd_invocation_id=INVOCATION_ID,
    )
    with pytest.raises(ValueError, match="committed transition evidence"):
        build_runner_activation_transition(
            target=selected_target,
            to_state="committed",
            evidence=verification_evidence(),
            previous_transition=committing,
            systemd_invocation_id=INVOCATION_ID,
        )


def test_aborted_evidence_distinguishes_pre_guard_and_guarded_abort() -> None:
    selected_target = target()
    prepared = build_runner_activation_transition(
        target=selected_target,
        to_state="prepared",
    )
    assert (
        build_runner_activation_transition(
            target=selected_target,
            to_state="aborted",
            previous_transition=prepared,
        )["toState"]
        == "aborted"
    )

    guarded = build_runner_activation_transition(
        target=selected_target,
        to_state="guarded",
        previous_transition=prepared,
    )
    with pytest.raises(ValueError, match="aborted transition evidence"):
        build_runner_activation_transition(
            target=selected_target,
            to_state="aborted",
            previous_transition=guarded,
        )
    guard_release = build_empty_runner_activation_evidence()
    guard_release["lifecycleGuardReleaseFingerprint"] = "sha256:" + "f" * 64
    aborted = build_runner_activation_transition(
        target=selected_target,
        to_state="aborted",
        evidence=guard_release,
        previous_transition=guarded,
    )
    assert aborted["evidence"] == guard_release


def test_transition_requires_invocation_as_soon_as_verification_starts() -> None:
    selected_target = target()
    before_verifying = append_chain(
        selected_target,
        FULL_COMMIT_STATES[:7],
    )[-1]

    with pytest.raises(ValueError, match="requires a systemd invocation"):
        build_runner_activation_transition(
            target=selected_target,
            to_state="verifying",
            previous_transition=before_verifying,
        )
    with pytest.raises(ValueError, match="premature systemd invocation"):
        build_runner_activation_transition(
            target=selected_target,
            to_state="prepared",
            systemd_invocation_id=INVOCATION_ID,
        )


def test_transition_has_exact_fields_and_domain_separated_fingerprint() -> None:
    transition = build_runner_activation_transition(
        target=target(),
        to_state="prepared",
    )
    canonical = runner_activation_transition_canonical_json(transition)
    assert canonical == json.dumps(
        transition,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    expected = hashlib.sha256(
        RUNNER_ACTIVATION_TRANSITION_SCHEMA.encode("ascii")
        + b"\x00"
        + canonical.encode("utf-8")
    ).hexdigest()
    assert runner_activation_transition_fingerprint(transition) == (
        f"sha256:{expected}"
    )
    with pytest.raises(ValueError, match="fields must match exactly"):
        require_runner_activation_transition(
            {**transition, "token": "must-never-appear"}
        )


@pytest.mark.parametrize(
    ("from_states", "illegal_state"),
    [
        (["prepared"], "promoting"),
        (["prepared", "aborted"], "guarded"),
        (FULL_COMMIT_STATES, "recovery_required"),
        (["prepared", "recovery_required"], "guarded"),
    ],
)
def test_illegal_or_terminal_state_transitions_are_rejected(
    from_states: list[str],
    illegal_state: str,
) -> None:
    selected_target = target()
    transitions = append_chain(selected_target, from_states)

    with pytest.raises(ValueError, match="is illegal"):
        build_runner_activation_transition(
            target=selected_target,
            to_state=illegal_state,
            previous_transition=transitions[-1],
        )


def test_upgrade_requires_previous_target_committed_head() -> None:
    previous_target, previous_chain = committed_install()
    upgrade_target = target(operation="upgrade")
    lineage = _lineage(previous_target, previous_chain)

    with pytest.raises(ValueError, match="requires a previous target"):
        build_runner_activation_transition(
            target=upgrade_target,
            to_state="prepared",
        )
    with pytest.raises(ValueError, match="requires a committed chain"):
        build_runner_activation_transition(
            target=upgrade_target,
            prior_invocation_ledger=lineage["prior_invocation_ledger"],
            previous_target=previous_target,
            to_state="prepared",
        )
    unrelated_target, unrelated_chain = committed_install(
        activation_id="1" * 32,
        generation_id="2" * 32,
        token_generation_id="3" * 32,
    )
    assert unrelated_target != previous_target
    with pytest.raises(ValueError, match="target binding mismatch"):
        build_runner_activation_transition(
            target=upgrade_target,
            prior_invocation_ledger=lineage["prior_invocation_ledger"],
            previous_target=lineage["previous_target"],
            previous_commit_chain=unrelated_chain,
            to_state="prepared",
        )

    prepared = build_runner_activation_transition(
        target=upgrade_target,
        to_state="prepared",
        **lineage,
    )
    assert prepared["previousCommitFingerprint"] == (
        runner_activation_transition_fingerprint(previous_chain[-1])
    )
    with pytest.raises(ValueError, match="reservation binding is invalid"):
        build_runner_activation_transition(
            target=upgrade_target,
            prior_invocation_ledger=empty_invocation_ledger(),
            previous_target=previous_target,
            previous_commit_chain=previous_chain,
            to_state="prepared",
        )


def test_token_rotation_preserves_credential_free_runtime_identity() -> None:
    previous_target, previous_chain = committed_install()
    previous_generation = previous_target["generation"]
    rotated_generation = generation(
        generation_id="9" * 32,
        token_generation_id="0" * 32,
        release_name="0.1.9-control-plane",
        config_fingerprint="sha256:" + "9" * 64,
    )
    rotated_target = target(
        selected_generation=rotated_generation,
        operation="token_rotation",
    )
    lineage = _lineage(previous_target, previous_chain)
    prepared = build_runner_activation_transition(
        target=rotated_target,
        to_state="prepared",
        **lineage,
    )
    assert prepared["previousTargetFingerprint"] == (
        runner_activation_target_fingerprint(previous_target)
    )

    runtime_drift = deepcopy(rotated_target)
    runtime_drift["generation"]["runtimeConfigFingerprint"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="changed runtime identity"):
        build_runner_activation_transition(
            target=runtime_drift,
            to_state="prepared",
            **lineage,
        )
    unit_drift = deepcopy(rotated_target)
    unit_drift["generation"]["systemdUnitTemplateFingerprint"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="changed runtime identity"):
        build_runner_activation_transition(
            target=unit_drift,
            to_state="prepared",
            **lineage,
        )
    unchanged_credential = deepcopy(rotated_target)
    unchanged_credential["generation"]["configFingerprint"] = previous_generation[
        "configFingerprint"
    ]
    with pytest.raises(ValueError, match="new credential generation"):
        build_runner_activation_transition(
            target=unchanged_credential,
            to_state="prepared",
            **lineage,
        )


def test_lineage_reservation_must_bind_the_previous_activation() -> None:
    previous_target, previous_chain = committed_install()
    upgrade_target = target(operation="upgrade")
    lineage = _lineage(previous_target, previous_chain)
    forged_ledger = deepcopy(lineage["prior_invocation_ledger"])
    reservation = forged_ledger["reservations"][0]
    reservation["activationId"] = "0" * 32
    reservation["systemdUnit"] = f"h2ometa-remote@{'0' * 32}.service"

    with pytest.raises(ValueError, match="reservation binding is invalid"):
        build_runner_activation_transition(
            target=upgrade_target,
            prior_invocation_ledger=forged_ledger,
            previous_target=previous_target,
            previous_commit_chain=previous_chain,
            to_state="prepared",
        )


def test_rollback_is_new_forward_activation_of_committed_generation() -> None:
    (
        previous_target,
        previous_chain,
        failed_target,
        failed_chain,
    ) = _failed_upgrade()
    rollback_target = target(
        activation_id="e" * 32,
        selected_generation=deepcopy(previous_target["generation"]),
        operation="rollback",
    )
    lineage = _rollback_lineage(
        previous_target,
        previous_chain,
        failed_target,
        failed_chain,
    )
    rollback_chain = append_chain(
        rollback_target,
        FULL_COMMIT_STATES,
        invocation_id="f" * 32,
        **lineage,
    )

    normalized = require_runner_activation_transition_chain(
        rollback_chain,
        current_invocation_reservation=chain_invocation_reservation(
            lineage["prior_invocation_ledger"],
            rollback_target,
            rollback_chain,
        ),
        target=rollback_target,
        **lineage,
    )
    assert normalized[-1]["toState"] == "committed"
    assert rollback_target["activationId"] != failed_target["activationId"]
    assert rollback_target["systemdUnit"] != failed_target["systemdUnit"]
    assert rollback_target["generation"] == previous_target["generation"]
    assert normalized[0]["recoveryOfTransitionFingerprint"] == (
        runner_activation_transition_fingerprint(failed_chain[-1])
    )


def test_rollback_rejects_missing_or_mismatched_recovery_evidence() -> None:
    (
        previous_target,
        previous_chain,
        failed_target,
        failed_chain,
    ) = _failed_upgrade()
    rollback_target = target(
        activation_id="e" * 32,
        selected_generation=deepcopy(previous_target["generation"]),
        operation="rollback",
    )
    lineage = _lineage(previous_target, previous_chain)
    with pytest.raises(ValueError, match="failed activation evidence"):
        build_runner_activation_transition(
            target=rollback_target,
            to_state="prepared",
            **lineage,
        )

    drifted_generation = generation(
        generation_id="9" * 32,
        token_generation_id="0" * 32,
        release_name="0.1.9-control-plane",
    )
    drifted_rollback = target(
        activation_id="e" * 32,
        selected_generation=drifted_generation,
        operation="rollback",
    )
    with pytest.raises(ValueError, match="restore the previous generation"):
        build_runner_activation_transition(
            target=drifted_rollback,
            to_state="prepared",
            recovery_of_target=failed_target,
            recovery_of_chain=failed_chain,
            **lineage,
        )


def test_rollback_chain_rejects_failed_invocation_reuse() -> None:
    (
        previous_target,
        previous_chain,
        failed_target,
        failed_chain,
    ) = _failed_upgrade()
    rollback_target = target(
        activation_id="e" * 32,
        selected_generation=deepcopy(previous_target["generation"]),
        operation="rollback",
    )
    lineage = _rollback_lineage(
        previous_target,
        previous_chain,
        failed_target,
        failed_chain,
    )
    with pytest.raises(ValueError, match="reused reserved invocation"):
        append_chain(
            rollback_target,
            FULL_COMMIT_STATES,
            invocation_id=INVOCATION_ID,
            **lineage,
        )


@pytest.mark.parametrize("operation", ["upgrade", "token_rotation", "repair"])
def test_new_activation_rejects_previous_committed_invocation_reuse(
    operation: str,
) -> None:
    previous_target, previous_chain = committed_install()
    if operation == "upgrade":
        selected_target = target(operation=operation)
    elif operation == "token_rotation":
        selected_target = target(
            selected_generation=generation(
                generation_id="9" * 32,
                token_generation_id="0" * 32,
                release_name="0.1.9-control-plane",
                config_fingerprint="sha256:" + "9" * 64,
            ),
            operation=operation,
        )
    else:
        selected_target = target(
            selected_generation=deepcopy(previous_target["generation"]),
            operation=operation,
        )
    with pytest.raises(ValueError, match="reused reserved invocation"):
        append_chain(
            selected_target,
            FULL_COMMIT_STATES,
            invocation_id=PREVIOUS_INVOCATION_ID,
            **_lineage(previous_target, previous_chain),
        )


def test_rollback_rejects_previous_committed_invocation_reuse() -> None:
    previous_target, previous_chain, failed_target, failed_chain = _failed_upgrade()
    rollback_target = target(
        activation_id="e" * 32,
        selected_generation=deepcopy(previous_target["generation"]),
        operation="rollback",
    )
    with pytest.raises(ValueError, match="reused reserved invocation"):
        append_chain(
            rollback_target,
            FULL_COMMIT_STATES,
            invocation_id=PREVIOUS_INVOCATION_ID,
            **_rollback_lineage(
                previous_target,
                previous_chain,
                failed_target,
                failed_chain,
            ),
        )


def test_failed_activation_rejects_previous_invocation_reuse() -> None:
    previous_target, previous_chain = committed_install()
    failed_target = target(operation="upgrade")
    with pytest.raises(ValueError, match="reused reserved invocation"):
        append_chain(
            failed_target,
            FULL_COMMIT_STATES[:8] + ["recovery_required"],
            invocation_id=PREVIOUS_INVOCATION_ID,
            **_lineage(previous_target, previous_chain),
        )


def test_chain_rejects_invocation_reserved_by_older_ancestor() -> None:
    first_target, first_chain = committed_install()
    second_target = target(operation="upgrade")
    second_chain = append_chain(
        second_target,
        FULL_COMMIT_STATES,
        invocation_id=INVOCATION_ID,
        **_lineage(first_target, first_chain),
    )
    prior_ledger = invocation_ledger_for_chains(
        (first_target, first_chain),
        (second_target, second_chain),
    )
    third_target = target(
        activation_id="1" * 32,
        selected_generation=generation(
            generation_id="2" * 32,
            token_generation_id="3" * 32,
            release_name="0.2.1-control-plane",
        ),
        operation="upgrade",
    )
    third_chain = append_chain(
        third_target,
        FULL_COMMIT_STATES,
        prior_invocation_ledger=prior_ledger,
        previous_target=second_target,
        previous_commit_chain=second_chain,
        invocation_id="4" * 32,
    )
    forged = deepcopy(third_chain)
    for transition in forged:
        if transition["systemdInvocationId"]:
            transition["systemdInvocationId"] = PREVIOUS_INVOCATION_ID

    with pytest.raises(ValueError, match="reused reserved invocation"):
        require_runner_activation_transition_chain(
            forged,
            target=third_target,
            prior_invocation_ledger=prior_ledger,
            previous_target=second_target,
            previous_commit_chain=second_chain,
        )


def test_recovery_required_cannot_drop_an_observed_invocation() -> None:
    selected_target = target()
    transitions = append_chain(
        selected_target,
        FULL_COMMIT_STATES[:8],
    )
    transitions.append(
        build_runner_activation_transition(
            target=selected_target,
            to_state="recovery_required",
            previous_transition=transitions[-1],
        )
    )

    with pytest.raises(ValueError, match="invocation was lost"):
        require_runner_activation_transition_chain(
            transitions,
            target=selected_target,
        )


def test_lineage_rejects_detached_terminal_records_without_full_chains() -> None:
    previous_target, previous_chain, failed_target, failed_chain = _failed_upgrade()
    upgrade_target = target(
        activation_id="1" * 32,
        selected_generation=generation(
            generation_id="2" * 32,
            token_generation_id="3" * 32,
            release_name="0.2.1-control-plane",
        ),
        operation="upgrade",
    )
    with pytest.raises(ValueError, match="must begin at revision 1"):
        build_runner_activation_transition(
            target=upgrade_target,
            previous_target=previous_target,
            previous_commit_chain=[previous_chain[-1]],
            to_state="prepared",
        )

    rollback_target = target(
        activation_id="e" * 32,
        selected_generation=deepcopy(previous_target["generation"]),
        operation="rollback",
    )
    with pytest.raises(ValueError, match="must begin at revision 1"):
        build_runner_activation_transition(
            target=rollback_target,
            prior_invocation_ledger=invocation_ledger_for_chains(
                (previous_target, previous_chain),
                (failed_target, failed_chain),
            ),
            previous_target=previous_target,
            previous_commit_chain=previous_chain,
            recovery_of_target=failed_target,
            recovery_of_chain=[failed_chain[-1]],
            to_state="prepared",
        )


def test_chain_rejects_hash_invocation_or_verification_evidence_drift() -> None:
    selected_target = target()
    transitions = append_chain(selected_target, FULL_COMMIT_STATES)

    hash_drift = deepcopy(transitions)
    hash_drift[2]["previousTransitionFingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="not contiguous"):
        require_runner_activation_transition_chain(
            hash_drift,
            target=selected_target,
        )

    invocation_drift = deepcopy(transitions)
    invocation_drift[-1]["systemdInvocationId"] = "f" * 32
    with pytest.raises(ValueError, match="invocation changed"):
        require_runner_activation_transition_chain(
            invocation_drift,
            target=selected_target,
        )

    evidence_drift = deepcopy(transitions)
    evidence_drift[-1]["evidence"]["processOwnerFingerprint"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="evidence changed"):
        require_runner_activation_transition_chain(
            evidence_drift,
            target=selected_target,
        )
