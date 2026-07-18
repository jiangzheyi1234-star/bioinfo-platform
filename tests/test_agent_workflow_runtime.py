from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.remote_runner import agent_workflow_runtime as runtime_builder
from apps.remote_runner.config import ensure_runtime_layout
from core.contracts.agent_workflow_runtime import (
    AgentWorkflowRuntimeProof,
    WorkflowRuntimeLockV2,
    agent_workflow_runtime_proof_hash,
    workflow_runtime_lock_v2_hash,
)
from tests.helpers.workflow_design_drafts import (
    install_agent_runtime_proof_test_seam,
    workflow_design_config,
)


_REAL_REQUIRE_STARTUP_RELEASE_BINDING = runtime_builder._require_startup_release_binding


@pytest.fixture(autouse=True)
def _cross_platform_runtime_test_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    install_agent_runtime_proof_test_seam(monkeypatch)


def test_runtime_proof_and_lock_use_distinct_strict_domains(tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)

    first = runtime_builder.build_agent_workflow_runtime_lock(cfg)
    second = runtime_builder.build_agent_workflow_runtime_lock(cfg)

    assert first.runtime_payload() == second.runtime_payload()
    assert first.schemaVersion == "workflow-runtime-lock.v2"
    assert first.proof.schemaVersion == "agent-workflow-runtime-proof.v1"
    assert first.proof.platform == "linux-64"
    assert first.runtimeProofHash == agent_workflow_runtime_proof_hash(first.proof)
    assert first.runtimeProofHash != workflow_runtime_lock_v2_hash(first)
    assert first.proof.snakemake.reportedVersion == cfg.snakemake_version
    assert first.proof.workflowRuntime.pythonResolvedPath == (
        first.proof.workflowRuntime.pythonPath
    )
    assert first.proof.workflowProfile.wrapperPrefix.startswith("file:")
    assert first.proof.release.treeHash != first.proof.release.wrapperMirrorTreeHash
    assert runtime_builder.require_current_agent_workflow_runtime_lock(
        cfg,
        first.runtime_payload(),
    ) == {
        "runtimeLock": first.runtime_payload(),
        "runtimeLockHash": workflow_runtime_lock_v2_hash(first),
        "runtimeProofHash": first.runtimeProofHash,
    }


def test_passive_current_runtime_lock_reobserves_without_process_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    stored = runtime_builder.build_agent_workflow_runtime_lock(cfg)
    _forbid_process_probe(monkeypatch)

    assert runtime_builder.require_passive_current_agent_workflow_runtime_lock(
        cfg,
        stored.runtime_payload(),
    ) == {
        "runtimeLock": stored.runtime_payload(),
        "runtimeLockHash": workflow_runtime_lock_v2_hash(stored),
        "runtimeProofHash": stored.runtimeProofHash,
    }


def test_passive_current_runtime_lock_detects_snakemake_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    stored = runtime_builder.build_agent_workflow_runtime_lock(cfg).runtime_payload()
    Path(cfg.snakemake_command).write_bytes(b"passive-snakemake-byte-drift")
    _forbid_process_probe(monkeypatch)

    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_PROOF_MISMATCH"):
        runtime_builder.require_passive_current_agent_workflow_runtime_lock(
            cfg,
            stored,
        )


def test_passive_current_runtime_lock_rejects_configured_version_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    stored = runtime_builder.build_agent_workflow_runtime_lock(cfg).runtime_payload()
    cfg.snakemake_version = "Python 0.0.0-config-drift"
    _forbid_process_probe(monkeypatch)

    with pytest.raises(
        ValueError, match="AGENT_WORKFLOW_RUNTIME_SNAKEMAKE_VERSION_MISMATCH"
    ):
        runtime_builder.require_passive_current_agent_workflow_runtime_lock(
            cfg,
            stored,
        )


def test_runtime_layout_materializes_managed_conda_root_before_proof(
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    managed_root = Path(cfg.managed_conda_root_prefix)
    managed_root.rmdir()

    ensure_runtime_layout(cfg)

    assert managed_root.is_dir()


def test_runtime_lock_rejects_tampered_proof_and_hash(tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    payload = runtime_builder.build_agent_workflow_runtime_lock(cfg).runtime_payload()
    payload["proof"]["snakemake"]["reportedVersion"] = "forged"

    with pytest.raises(
        ValidationError, match="AGENT_WORKFLOW_RUNTIME_PROOF_HASH_MISMATCH"
    ):
        WorkflowRuntimeLockV2.model_validate(payload)

    payload = runtime_builder.build_agent_workflow_runtime_lock(cfg).runtime_payload()
    payload["runtimeProofHash"] = "0" * 64
    with pytest.raises(
        ValidationError, match="AGENT_WORKFLOW_RUNTIME_PROOF_HASH_MISMATCH"
    ):
        WorkflowRuntimeLockV2.model_validate(payload)


def test_runtime_contract_revalidates_mutated_model_instances(tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    proof = runtime_builder.build_agent_workflow_runtime_proof(cfg)
    original_hash = agent_workflow_runtime_proof_hash(proof)
    object.__setattr__(proof.snakemake, "sha256", "not-a-hash")

    with pytest.raises(ValidationError):
        agent_workflow_runtime_proof_hash(proof)
    assert len(original_hash) == 64


@pytest.mark.parametrize(
    "field",
    [
        "runnerProtocol",
        "workflowRuntime",
        "snakemake",
        "managedConda",
        "workflowProfile",
        "release",
    ],
)
def test_runtime_proof_rejects_missing_exact_sections(
    tmp_path: Path,
    field: str,
) -> None:
    cfg = workflow_design_config(tmp_path)
    payload = runtime_builder.build_agent_workflow_runtime_proof(cfg).runtime_payload()
    payload.pop(field)

    with pytest.raises(ValidationError):
        AgentWorkflowRuntimeProof.model_validate(payload)


def test_runtime_proof_rejects_extra_or_secret_like_fields(tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    payload = runtime_builder.build_agent_workflow_runtime_proof(cfg).runtime_payload()
    payload["debug"] = True
    with pytest.raises(ValidationError):
        AgentWorkflowRuntimeProof.model_validate(payload)

    payload = runtime_builder.build_agent_workflow_runtime_proof(cfg).runtime_payload()
    payload["workflowRuntime"]["source"] = "Bearer abcdefghijklmnopqrstuvwxyz"
    with pytest.raises(ValidationError):
        AgentWorkflowRuntimeProof.model_validate(payload)


def test_current_runtime_check_detects_release_and_wrapper_drift(
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    stored = runtime_builder.build_agent_workflow_runtime_lock(cfg).runtime_payload()
    release_file = Path(cfg.release_dir) / "runtime-proof-fixture.py"
    release_file.write_text("# changed release bytes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_PROOF_MISMATCH"):
        runtime_builder.require_current_agent_workflow_runtime_lock(cfg, stored)

    stored = runtime_builder.build_agent_workflow_runtime_lock(cfg).runtime_payload()
    wrapper = next((Path(cfg.release_dir) / "snakemake_wrappers").rglob("wrapper.py"))
    wrapper.write_text("# changed wrapper bytes\n", encoding="utf-8")
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_PROOF_MISMATCH"):
        runtime_builder.require_current_agent_workflow_runtime_lock(cfg, stored)


def test_current_runtime_check_detects_profile_drift_before_authorization(
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    stored = runtime_builder.build_agent_workflow_runtime_lock(cfg).runtime_payload()
    profile = Path(cfg.workflow_profile_dir) / cfg.workflow_profile_name
    profile.write_text(
        profile.read_text(encoding="utf-8") + "latency-wait: 61\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_PROOF_MISMATCH"):
        runtime_builder.require_current_agent_workflow_runtime_lock(cfg, stored)


def test_runtime_builder_detects_binary_byte_drift_with_fresh_version_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    command = Path(cfg.snakemake_command)
    monkeypatch.setattr(
        runtime_builder,
        "_probe_snakemake_version",
        lambda _cfg, _path: cfg.snakemake_version,
    )
    stored = runtime_builder.build_agent_workflow_runtime_lock(cfg).runtime_payload()
    command.write_bytes(b"snakemake-v2")

    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_PROOF_MISMATCH"):
        runtime_builder.require_current_agent_workflow_runtime_lock(cfg, stored)


def test_runtime_builder_rejects_old_lock_and_manifest_marker_tamper(
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_LOCK_V2_REQUIRED"):
        runtime_builder.require_current_agent_workflow_runtime_lock(
            cfg,
            {"schemaVersion": "workflow-runtime-lock.v1"},
        )

    artifact_marker = Path(cfg.release_dir).parent / "artifact.sha256"
    artifact_marker.write_text("not-a-sha\n", encoding="ascii")
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_ARTIFACT_SHA_INVALID"):
        runtime_builder.build_agent_workflow_runtime_lock(cfg)


def test_runtime_builder_rejects_workflow_runtime_manifest_and_marker_drift(
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    proof = runtime_builder.build_agent_workflow_runtime_proof(cfg)
    runtime_root = Path(proof.workflowRuntime.root)
    marker = runtime_root / "artifact.sha256"
    marker.write_text("invalid\n", encoding="ascii")
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_ARCHIVE_SHA_INVALID"):
        runtime_builder.build_agent_workflow_runtime_lock(cfg)

    cfg = workflow_design_config(tmp_path / "manifest-case")
    proof = runtime_builder.build_agent_workflow_runtime_proof(cfg)
    manifest = Path(proof.workflowRuntime.bootstrapManifestPath)
    payload = manifest.read_text(encoding="utf-8").replace(
        '"provider": "conda-pack"',
        '"provider": "untrusted"',
    )
    manifest.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_MANIFEST_MISMATCH"):
        runtime_builder.build_agent_workflow_runtime_lock(cfg)


def test_runtime_builder_allows_only_internal_entrypoint_symlink_chains(
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    initial = runtime_builder.build_agent_workflow_runtime_proof(cfg)
    declared = Path(initial.workflowRuntime.pythonPath)
    target = declared.with_name("python3.12")
    declared.rename(target)
    try:
        declared.symlink_to(target.name)
    except OSError:
        target.rename(declared)
        pytest.skip("this Windows host cannot create the Linux artifact symlink shape")

    proof = runtime_builder.build_agent_workflow_runtime_proof(cfg)

    assert proof.workflowRuntime.pythonPath == str(declared)
    assert proof.workflowRuntime.pythonResolvedPath == str(target)

    stored = runtime_builder.build_agent_workflow_runtime_lock(cfg).runtime_payload()
    original_target_bytes = target.read_bytes()
    target.write_bytes(b"python-target-drift")
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_PROOF_MISMATCH"):
        runtime_builder.require_current_agent_workflow_runtime_lock(cfg, stored)
    target.write_bytes(original_target_bytes)

    declared.unlink()
    outside = tmp_path / "outside-python"
    target.replace(outside)
    declared.symlink_to(outside)
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_ENTRYPOINT_INVALID"):
        runtime_builder.build_agent_workflow_runtime_proof(cfg)


def test_runtime_lock_hash_includes_the_proof_hash_field(tmp_path: Path) -> None:
    cfg = workflow_design_config(tmp_path)
    lock = runtime_builder.build_agent_workflow_runtime_lock(cfg)
    payload = deepcopy(lock.runtime_payload())
    payload["runtimeProofHash"] = "f" * 64

    with pytest.raises(ValidationError):
        WorkflowRuntimeLockV2.model_validate(payload)
    assert workflow_runtime_lock_v2_hash(lock) != lock.runtimeProofHash


def test_production_collection_requires_and_matches_startup_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    proof = runtime_builder.build_agent_workflow_runtime_proof(cfg)
    runner = proof.runnerProtocol
    binding = {
        "packagePath": proof.release.directory,
        "manifestPath": runner.bootstrapManifestPath,
        "bootstrapManifestFingerprint": runner.bootstrapManifestFingerprint,
        "artifactArchiveSha256Path": runner.artifactArchiveSha256Path,
        "declaredArtifactArchiveSha256": runner.declaredArtifactArchiveSha256,
        "protocolVersion": runner.version,
        "protocolFingerprint": runner.fingerprint,
    }
    monkeypatch.setattr(
        runtime_builder,
        "_require_startup_release_binding",
        _REAL_REQUIRE_STARTUP_RELEASE_BINDING,
    )
    monkeypatch.setattr(
        runtime_builder,
        "get_process_bound_remote_runner_startup_binding",
        lambda: binding,
    )
    monkeypatch.setattr(runtime_builder, "_require_linux_64_host", lambda: None)

    assert runtime_builder.build_agent_workflow_runtime_proof(cfg) == proof

    binding["declaredArtifactArchiveSha256"] = "sha256:" + "f" * 64
    with pytest.raises(
        ValueError, match="AGENT_WORKFLOW_RUNTIME_STARTUP_BINDING_MISMATCH"
    ):
        runtime_builder.build_agent_workflow_runtime_proof(cfg)


def test_collection_cannot_proceed_without_startup_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    monkeypatch.setattr(
        runtime_builder,
        "_require_startup_release_binding",
        _REAL_REQUIRE_STARTUP_RELEASE_BINDING,
    )
    monkeypatch.setattr(runtime_builder, "_require_linux_64_host", lambda: None)
    monkeypatch.setattr(
        runtime_builder,
        "get_process_bound_remote_runner_startup_binding",
        lambda: None,
    )

    with pytest.raises(
        ValueError, match="AGENT_WORKFLOW_RUNTIME_STARTUP_BINDING_REQUIRED"
    ):
        runtime_builder.build_agent_workflow_runtime_proof(cfg)


def test_collection_checks_production_platform_before_startup_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = workflow_design_config(tmp_path)
    monkeypatch.setattr(
        runtime_builder,
        "_require_startup_release_binding",
        _REAL_REQUIRE_STARTUP_RELEASE_BINDING,
    )
    monkeypatch.setattr(
        runtime_builder,
        "_require_linux_64_host",
        lambda: (_ for _ in ()).throw(
            ValueError("AGENT_WORKFLOW_RUNTIME_PLATFORM_MISMATCH")
        ),
    )
    monkeypatch.setattr(
        runtime_builder,
        "get_process_bound_remote_runner_startup_binding",
        lambda: pytest.fail("startup binding must follow host validation"),
    )

    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUNTIME_PLATFORM_MISMATCH"):
        runtime_builder.build_agent_workflow_runtime_proof(cfg)


def _forbid_process_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        pytest.fail("passive runtime verification must not launch a subprocess")

    monkeypatch.setattr(runtime_builder, "_probe_snakemake_version", fail_if_called)
    monkeypatch.setattr(runtime_builder.subprocess, "run", fail_if_called)
