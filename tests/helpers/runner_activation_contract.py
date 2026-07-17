"""Fixtures for strict remote-runner activation contract tests."""

from __future__ import annotations

from core.contracts.runner_activation import (
    RUNNER_ACTIVATION_EVIDENCE_SCHEMA,
    build_runner_activation_generation,
    build_runner_activation_target,
    build_runner_activation_transition,
    runner_activation_target_fingerprint,
    runner_activation_transition_fingerprint,
)
from core.contracts.runner_activation_invocation_ledger import (
    build_empty_runner_activation_invocation_ledger,
    build_runner_activation_invocation_ledger,
    build_runner_activation_invocation_reservation,
    runner_activation_invocation_reservation_fingerprint,
)


ACTIVATION_ID = "a" * 32
GENERATION_ID = "b" * 32
TOKEN_GENERATION_ID = "c" * 32
INVOCATION_ID = "d" * 32
PREVIOUS_INVOCATION_ID = "5" * 32
ROOT = "/home/runner/.h2ometa/runner"


def generation_root(generation_id: str = GENERATION_ID) -> str:
    return f"{ROOT}/shared/activation/generations/{generation_id}"


def generation(
    *,
    generation_id: str = GENERATION_ID,
    token_generation_id: str = TOKEN_GENERATION_ID,
    release_name: str = "0.2.0-control-plane",
    config_fingerprint: str = "sha256:" + "2" * 64,
    runtime_config_fingerprint: str = "sha256:" + "6" * 64,
    unit_fingerprint: str = "sha256:" + "5" * 64,
) -> dict[str, object]:
    return build_runner_activation_generation(
        generation_id=generation_id,
        release_path=f"{ROOT}/releases/{release_name}",
        release_artifact_sha256="sha256:" + "1" * 64,
        config_path=f"{generation_root(generation_id)}/runner.json",
        config_fingerprint=config_fingerprint,
        runtime_config_fingerprint=runtime_config_fingerprint,
        profile_path=f"{generation_root(generation_id)}/profile.v9+.yaml",
        profile_fingerprint="sha256:" + "3" * 64,
        protocol_version="runner-protocol.v6",
        protocol_fingerprint="sha256:" + "4" * 64,
        systemd_unit_template_fingerprint=unit_fingerprint,
        token_generation_id=token_generation_id,
    )


def target(
    *,
    activation_id: str = ACTIVATION_ID,
    selected_generation: object | None = None,
    operation: str = "install",
) -> dict[str, object]:
    chosen_generation = selected_generation or generation()
    unit = f"h2ometa-remote@{activation_id}.service"
    return build_runner_activation_target(
        activation_id=activation_id,
        operation=operation,
        generation=chosen_generation,
        current_link_path=f"{ROOT}/current",
        current_link_target=str(chosen_generation["releasePath"]),
        systemd_unit=unit,
        systemd_unit_template_path=(
            "/home/runner/.config/systemd/user/h2ometa-remote@.service"
        ),
    )


def verification_evidence(
    *,
    committed: bool = False,
    invocation_reservation_fingerprint: str = "sha256:" + "f" * 64,
) -> dict[str, str]:
    return {
        "activationVerificationFingerprint": "sha256:" + "a" * 64,
        "authenticatedReadinessFingerprint": "sha256:" + "b" * 64,
        "invocationReservationFingerprint": (invocation_reservation_fingerprint),
        "lifecycleGuardReleaseFingerprint": ("sha256:" + "e" * 64 if committed else ""),
        "processOwnerFingerprint": "sha256:" + "c" * 64,
        "schemaVersion": RUNNER_ACTIVATION_EVIDENCE_SCHEMA,
        "systemdObservationFingerprint": "sha256:" + "d" * 64,
    }


def append_chain(
    selected_target: object,
    states: list[str],
    *,
    previous_target: object | None = None,
    previous_commit_chain: object | None = None,
    recovery_of_target: object | None = None,
    recovery_of_chain: object | None = None,
    prior_invocation_ledger: object | None = None,
    invocation_id: str = INVOCATION_ID,
) -> list[dict[str, object]]:
    ledger = (
        empty_invocation_ledger()
        if prior_invocation_ledger is None
        else prior_invocation_ledger
    )
    transitions: list[dict[str, object]] = []
    previous: dict[str, object] | None = None
    reservation_fingerprint = ""
    for state in states:
        evidence = None
        if state in {"candidate_verified", "committing"}:
            if not reservation_fingerprint:
                reservation_fingerprint = (
                    runner_activation_invocation_reservation_fingerprint(
                        chain_invocation_reservation(
                            ledger,
                            selected_target,
                            transitions,
                        )
                    )
                )
            evidence = verification_evidence(
                invocation_reservation_fingerprint=reservation_fingerprint
            )
        elif state == "committed":
            evidence = verification_evidence(
                committed=True,
                invocation_reservation_fingerprint=reservation_fingerprint,
            )
        observed_invocation = (
            invocation_id
            if state
            in {
                "verifying",
                "candidate_verified",
                "committing",
                "committed",
                "recovery_required",
            }
            else ""
        )
        lineage = (
            {
                "previous_target": previous_target,
                "previous_commit_chain": previous_commit_chain,
                "recovery_of_target": recovery_of_target,
                "recovery_of_chain": recovery_of_chain,
            }
            if previous is None
            else {}
        )
        previous = build_runner_activation_transition(
            target=selected_target,
            prior_invocation_ledger=ledger,
            to_state=state,
            evidence=evidence,
            previous_transition=previous,
            systemd_invocation_id=observed_invocation,
            **lineage,
        )
        transitions.append(previous)
    return transitions


def empty_invocation_ledger() -> dict[str, object]:
    return build_empty_runner_activation_invocation_ledger()


def reserve_chain_invocation(
    ledger: object,
    selected_target: dict[str, object],
    transitions: list[dict[str, object]],
) -> dict[str, object]:
    normalized = build_runner_activation_invocation_ledger(
        ledger["reservations"] if isinstance(ledger, dict) else ledger
    )
    reservations = list(normalized["reservations"])
    reservation = chain_invocation_reservation(
        normalized,
        selected_target,
        transitions,
    )
    return build_runner_activation_invocation_ledger([*reservations, reservation])


def chain_invocation_reservation(
    prior_ledger: object,
    selected_target: dict[str, object],
    transitions: list[dict[str, object]],
) -> dict[str, object]:
    normalized = build_runner_activation_invocation_ledger(
        prior_ledger["reservations"] if isinstance(prior_ledger, dict) else prior_ledger
    )
    reservations = list(normalized["reservations"])
    observed = next(
        transition for transition in transitions if transition["systemdInvocationId"]
    )
    return build_runner_activation_invocation_reservation(
        activation_id=selected_target["activationId"],
        generation_id=selected_target["generation"]["generationId"],
        invocation_id=observed["systemdInvocationId"],
        observed_transition_fingerprint=(
            runner_activation_transition_fingerprint(observed)
        ),
        previous_reservation=(reservations[-1] if reservations else None),
        systemd_unit=selected_target["systemdUnit"],
        target_fingerprint=runner_activation_target_fingerprint(selected_target),
    )


def invocation_ledger_for_chains(
    *chains: tuple[dict[str, object], list[dict[str, object]]],
) -> dict[str, object]:
    ledger = empty_invocation_ledger()
    for selected_target, transitions in chains:
        ledger = reserve_chain_invocation(
            ledger,
            selected_target,
            transitions,
        )
    return ledger


def committed_install(
    *,
    activation_id: str = "6" * 32,
    generation_id: str = "7" * 32,
    token_generation_id: str = "8" * 32,
    invocation_id: str = PREVIOUS_INVOCATION_ID,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    installed_target = target(
        activation_id=activation_id,
        selected_generation=generation(
            generation_id=generation_id,
            token_generation_id=token_generation_id,
            release_name="0.1.9-control-plane",
        ),
    )
    states = [
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
    return installed_target, append_chain(
        installed_target,
        states,
        invocation_id=invocation_id,
    )


__all__ = [
    "ACTIVATION_ID",
    "GENERATION_ID",
    "INVOCATION_ID",
    "PREVIOUS_INVOCATION_ID",
    "ROOT",
    "TOKEN_GENERATION_ID",
    "append_chain",
    "chain_invocation_reservation",
    "committed_install",
    "empty_invocation_ledger",
    "generation",
    "generation_root",
    "invocation_ledger_for_chains",
    "reserve_chain_invocation",
    "target",
    "verification_evidence",
]
