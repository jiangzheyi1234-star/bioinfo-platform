from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load_module() -> Any:
    script = Path("scripts/check_remote_runner_release_readiness.py")
    spec = importlib.util.spec_from_file_location("check_remote_runner_release_readiness", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_release_readiness_validates_ci_build_metadata(tmp_path: Path) -> None:
    readiness = _load_module()
    source_commit = "a" * 40
    runner = tmp_path / "h2ometa-remote-runner.tar.gz"
    workflow = tmp_path / "h2ometa-workflow-runtime.tar.gz"
    runner_sha = _write(runner, b"runner")
    workflow_sha = _write(workflow, b"workflow")
    runner.with_suffix(runner.suffix + ".sha256").write_text(f"{runner_sha}  {runner.name}\n", encoding="utf-8")
    workflow.with_suffix(workflow.suffix + ".sha256").write_text(
        f"{workflow_sha}  {workflow.name}\n",
        encoding="utf-8",
    )
    runner_sbom = tmp_path / "runner.spdx.json"
    workflow_sbom = tmp_path / "workflow.spdx.json"
    runner_sbom_sha = _write(runner_sbom, b'{"spdxVersion":"SPDX-2.3"}')
    workflow_sbom_sha = _write(workflow_sbom, b'{"spdxVersion":"SPDX-2.3"}')
    metadata_path = tmp_path / "release-artifacts-metadata.json"
    manifest_metadata_path = tmp_path / "release-manifest-metadata.json"
    attestations_path = tmp_path / "release-attestations.json"
    _write_json(
        metadata_path,
        {
            "schemaVersion": "h2ometa-release-artifacts-ci.v1",
            "sourceCommit": source_commit,
            "artifacts": [
                {
                    "artifactKey": "remote_runner",
                    "platform": "linux-64",
                    "path": str(runner),
                    "sha256Path": str(runner) + ".sha256",
                    "sha256": runner_sha,
                    "sizeBytes": runner.stat().st_size,
                    "sbom": {"path": str(runner_sbom), "sha256": runner_sbom_sha},
                },
                {
                    "artifactKey": "workflow_runtime",
                    "platform": "linux-64",
                    "path": str(workflow),
                    "sha256Path": str(workflow) + ".sha256",
                    "sha256": workflow_sha,
                    "sizeBytes": workflow.stat().st_size,
                    "sbom": {"path": str(workflow_sbom), "sha256": workflow_sbom_sha},
                },
            ],
        },
    )
    _write_json(
        manifest_metadata_path,
        {
            "schemaVersion": "h2ometa-release-manifest-metadata.v1",
            "sourceCommit": source_commit,
            "artifacts": {
                "remote_runner": {"linux-64": {"sha256": runner_sha, "sourceCommit": source_commit}},
                "workflow_runtime": {"linux-64": {"sha256": workflow_sha, "sourceCommit": source_commit}},
            },
        },
    )
    _write_json(
        attestations_path,
        {
            "schemaVersion": "h2ometa-release-attestations.v1",
            "provenance": {"attestationId": "p"},
            "sbom": {
                "remote_runner": {"attestationId": "r"},
                "workflow_runtime": {"attestationId": "w"},
            },
        },
    )

    result = readiness.validate_ci_build_outputs(
        metadata_path=metadata_path,
        manifest_metadata_path=manifest_metadata_path,
        attestations_path=attestations_path,
    )

    assert result.ok is True
    assert result.name == "ci-build-metadata"
    assert result.detail["sourceCommit"] == source_commit
    assert set(result.detail["artifacts"]) == {"remote_runner", "workflow_runtime"}


def test_release_readiness_validates_required_release_gate_labels(tmp_path: Path) -> None:
    readiness = _load_module()
    evidence_path = tmp_path / "release-gate-evidence.json"
    _write_json(
        evidence_path,
        {
            "schemaVersion": "remote-runner-release-gate.v1",
            "ok": True,
            "sourceCommit": "b" * 40,
            "steps": [
                {
                    "name": "real-snakemake-two-slot",
                    "exitCode": 0,
                    "evidenceLabels": [
                        "ACCEPTANCE_SUMMARY",
                        "CONCURRENCY_EVIDENCE",
                        "OBSERVABILITY_EVIDENCE",
                        "POST_ACCEPTANCE_INVARIANTS",
                        "RESOURCE_WAIT_EVIDENCE",
                        "RESULT",
                        "RUNNER_READY",
                    ],
                },
                {
                    "name": "worker-crash-restart-recovery",
                    "exitCode": 0,
                    "evidenceLabels": ["RECOVERY_EVIDENCE", "RESULT", "SERVER_READY_PREFLIGHT"],
                },
                {
                    "name": "execution-policy-acceptance",
                    "exitCode": 0,
                    "evidenceLabels": [
                        "POLICY_ACCEPTANCE_SUMMARY",
                        "POLICY_ATTEMPT_TIMEOUT_EVIDENCE",
                        "POLICY_BACKOFF_EVIDENCE",
                        "OBSERVABILITY_EVIDENCE",
                        "POLICY_PREFLIGHT",
                        "POLICY_QUEUE_TTL_EVIDENCE",
                        "POST_POLICY_INVARIANTS",
                        "RESULT",
                    ],
                },
            ],
        },
    )

    result = readiness.validate_release_gate_evidence(evidence_path)

    assert result.ok is True
    assert set(result.detail["steps"]) == {
        "execution-policy-acceptance",
        "real-snakemake-two-slot",
        "worker-crash-restart-recovery",
    }


def test_release_readiness_accepts_optional_soak_gate_step(tmp_path: Path) -> None:
    readiness = _load_module()
    evidence_path = tmp_path / "release-gate-evidence.json"
    _write_json(
        evidence_path,
        {
            "schemaVersion": "remote-runner-release-gate.v1",
            "ok": True,
            "sourceCommit": "b" * 40,
            "steps": [
                {
                    "name": "real-snakemake-two-slot",
                    "exitCode": 0,
                    "evidenceLabels": [
                        "ACCEPTANCE_SUMMARY",
                        "CONCURRENCY_EVIDENCE",
                        "OBSERVABILITY_EVIDENCE",
                        "POST_ACCEPTANCE_INVARIANTS",
                        "RESOURCE_WAIT_EVIDENCE",
                        "RESULT",
                        "RUNNER_READY",
                    ],
                },
                {
                    "name": "worker-crash-restart-recovery",
                    "exitCode": 0,
                    "evidenceLabels": ["RECOVERY_EVIDENCE", "RESULT", "SERVER_READY_PREFLIGHT"],
                },
                {
                    "name": "execution-policy-acceptance",
                    "exitCode": 0,
                    "evidenceLabels": [
                        "POLICY_ACCEPTANCE_SUMMARY",
                        "POLICY_ATTEMPT_TIMEOUT_EVIDENCE",
                        "POLICY_BACKOFF_EVIDENCE",
                        "OBSERVABILITY_EVIDENCE",
                        "POLICY_PREFLIGHT",
                        "POLICY_QUEUE_TTL_EVIDENCE",
                        "POST_POLICY_INVARIANTS",
                        "RESULT",
                    ],
                },
                {
                    "name": "soak-stress-fault-injection",
                    "exitCode": 0,
                    "evidenceLabels": [
                        "RESULT",
                        "SOAK_ACCEPTANCE_SUMMARY",
                        "SOAK_OBSERVABILITY_EVIDENCE",
                    ],
                },
            ],
        },
    )

    result = readiness.validate_release_gate_evidence(evidence_path)

    assert result.ok is True
    assert "soak-stress-fault-injection" in result.detail["steps"]


def test_release_readiness_rejects_partial_release_gate_evidence(tmp_path: Path) -> None:
    readiness = _load_module()
    evidence_path = tmp_path / "release-gate-evidence.json"
    _write_json(
        evidence_path,
        {
            "schemaVersion": "remote-runner-release-gate.v1",
            "ok": True,
            "sourceCommit": "c" * 40,
            "steps": [
                {
                    "name": "execution-policy-acceptance",
                    "exitCode": 0,
                    "evidenceLabels": ["RESULT"],
                }
            ],
        },
    )

    try:
        readiness.validate_release_gate_evidence(evidence_path)
    except ValueError as exc:
        assert "evidence missing labels" in str(exc)
    else:
        raise AssertionError("partial release gate evidence was accepted")


def test_release_readiness_can_run_as_non_destructive_ci_metadata_check(tmp_path: Path, capsys) -> None:
    readiness = _load_module()
    metadata = tmp_path / "metadata.json"
    manifest = tmp_path / "manifest.json"
    attestations = tmp_path / "attestations.json"

    assert (
        readiness.main(
            [
                "--ci-build-metadata",
                str(metadata),
                "--manifest-metadata",
                str(manifest),
                "--attestations",
                str(attestations),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "RELEASE_READINESS_SUMMARY" in captured.out
    assert "FileNotFoundError" in captured.out
