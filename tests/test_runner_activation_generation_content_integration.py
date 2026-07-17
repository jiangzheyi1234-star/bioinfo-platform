from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

import pytest

from apps.remote_runner.config import RemoteRunnerConfig
from core.contracts.runner_activation import (
    build_runner_activation_generation,
    build_runner_activation_transition,
    require_runner_activation_generation,
    runner_activation_generation_canonical_json,
)
from core.contracts.runner_activation_content import (
    build_runner_activation_config_bytes,
    build_runner_activation_profile_bytes,
    require_runner_activation_config_bytes,
    runner_activation_config_blob_integrity_tag,
    runner_activation_file_bytes_sha256,
    runner_activation_runtime_config_fingerprint,
    verify_runner_activation_config_blob_integrity_tag,
)
from tests.helpers.runner_activation_contract import (
    CONFIG_INTEGRITY_KEY_ID,
    TOKEN_GENERATION_ID as FIXTURE_TOKEN_GENERATION_ID,
    append_chain,
    committed_install,
    empty_invocation_ledger,
    invocation_ledger_for_chains,
    target,
)


ROOT = "/home/runner/.h2ometa/runner"
GENERATION_ID = "1" * 32
TOKEN_GENERATION_ID = "2" * 32
INTEGRITY_KEY_ID = "3" * 32
INTEGRITY_KEY = b"k" * 32


def _config_payload() -> dict[str, object]:
    return asdict(
        RemoteRunnerConfig(
            version="0.2.0-control-plane",
            mode="systemd_user",
            bind_port=43117,
            token="secret-token-sentinel",
            api_token_roles=("auditor", "workflow-operator"),
            runner_protocol_version="runner-protocol.v6",
            runner_protocol_fingerprint="sha256:" + "4" * 64,
            data_root=f"{ROOT}/shared",
            db_path=f"{ROOT}/shared/data/runner.db",
            runtime_state_path=f"{ROOT}/shared/runtime/runner-state.json",
            uploads_dir=f"{ROOT}/shared/uploads",
            results_dir=f"{ROOT}/shared/results",
            work_dir=f"{ROOT}/shared/work",
            logs_dir=f"{ROOT}/shared/logs",
            release_dir=f"{ROOT}/releases/0.2.0-control-plane/remote_runner",
            runner_python=f"{ROOT}/releases/0.2.0-control-plane/runtime/bin/python",
            managed_conda_command=(
                f"{ROOT}/releases/0.2.0-control-plane/runtime/bin/micromamba"
            ),
            managed_conda_root_prefix=f"{ROOT}/shared/conda",
            workflow_runtime_provider="bundled",
            workflow_runtime_source="release",
            workflow_runtime_version="1",
            snakemake_command=(
                f"{ROOT}/releases/0.2.0-control-plane/runtime/bin/snakemake"
            ),
            snakemake_version="9.8.1",
            workflow_profile_dir=(
                f"{ROOT}/shared/activation/generations/{GENERATION_ID}"
            ),
            workflow_profile_name="profile.v9+.yaml",
        )
    )


def test_generated_content_identities_are_accepted_by_generation_contract() -> None:
    config_bytes = build_runner_activation_config_bytes(_config_payload())
    profile_bytes = build_runner_activation_profile_bytes(
        conda_prefix=f"{ROOT}/shared/conda-envs"
    )
    integrity_tag = runner_activation_config_blob_integrity_tag(
        config_bytes,
        integrity_key=INTEGRITY_KEY,
        integrity_key_id=INTEGRITY_KEY_ID,
    )

    generation = build_runner_activation_generation(
        generation_id=GENERATION_ID,
        release_path=f"{ROOT}/releases/0.2.0-control-plane",
        release_artifact_sha256=runner_activation_file_bytes_sha256(b"release-archive"),
        config_path=(
            f"{ROOT}/shared/activation/generations/{GENERATION_ID}/runner.json"
        ),
        config_blob_integrity_key_id=INTEGRITY_KEY_ID,
        config_blob_integrity_tag=integrity_tag,
        runtime_config_fingerprint=runner_activation_runtime_config_fingerprint(
            config_bytes
        ),
        profile_path=(
            f"{ROOT}/shared/activation/generations/{GENERATION_ID}/profile.v9+.yaml"
        ),
        profile_fingerprint=runner_activation_file_bytes_sha256(profile_bytes),
        protocol_version="runner-protocol.v6",
        protocol_fingerprint="sha256:" + "4" * 64,
        systemd_unit_template_fingerprint=runner_activation_file_bytes_sha256(
            b"[Service]\nType=notify\n"
        ),
        token_generation_id=TOKEN_GENERATION_ID,
    )

    assert require_runner_activation_generation(generation) == generation
    assert verify_runner_activation_config_blob_integrity_tag(
        config_bytes,
        integrity_key=INTEGRITY_KEY,
        integrity_key_id=INTEGRITY_KEY_ID,
        integrity_tag=generation["configBlobIntegrityTag"],
    )
    serialized = runner_activation_generation_canonical_json(generation)
    assert "secret-token-sentinel" not in serialized
    assert "configFingerprint" not in serialized


def test_repair_rejects_reused_generation_id_with_content_drift() -> None:
    previous_target, previous_chain = committed_install()
    lineage = {
        "prior_invocation_ledger": invocation_ledger_for_chains(
            (previous_target, previous_chain)
        ),
        "previous_target": previous_target,
        "previous_commit_chain": previous_chain,
    }
    exact_repair = target(
        selected_generation=deepcopy(previous_target["generation"]),
        operation="repair",
    )

    prepared = build_runner_activation_transition(
        target=exact_repair,
        to_state="prepared",
        **lineage,
    )
    assert prepared["generationId"] == previous_target["generation"]["generationId"]

    drifted_repair = deepcopy(exact_repair)
    drifted_repair["generation"]["runtimeConfigFingerprint"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="reused with different content"):
        build_runner_activation_transition(
            target=drifted_repair,
            to_state="prepared",
            **lineage,
        )


class ContractError(RuntimeError):
    pass


def test_config_parser_uses_caller_error_for_out_of_range_integer() -> None:
    raw = build_runner_activation_config_bytes(_config_payload())
    oversized = raw.replace(b'"bind_port":43117', b'"bind_port":' + b"9" * 5_000)

    with pytest.raises(ContractError, match="out of range"):
        require_runner_activation_config_bytes(
            oversized,
            make_error=ContractError,
        )


@pytest.mark.parametrize(
    "invocation_id",
    [CONFIG_INTEGRITY_KEY_ID, FIXTURE_TOKEN_GENERATION_ID],
)
def test_target_bound_invocation_id_is_distinct_from_credential_ids(
    invocation_id: str,
) -> None:
    with pytest.raises(ValueError, match="systemdInvocationId must be distinct"):
        append_chain(
            target(),
            [
                "prepared",
                "guarded",
                "stopping",
                "stopped",
                "promoting",
                "promoted",
                "starting",
                "verifying",
            ],
            invocation_id=invocation_id,
            prior_invocation_ledger=empty_invocation_ledger(),
        )
