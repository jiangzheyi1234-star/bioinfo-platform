from __future__ import annotations

from pathlib import Path


def test_release_gate_evidence_registration_workflow_contract() -> None:
    workflow = Path(".github/workflows/register-remote-runner-release-gate-evidence.yml").read_text(
        encoding="utf-8",
    )

    assert "Register Remote Runner Release Gate Evidence" in workflow
    assert "workflow_dispatch:" in workflow
    assert "release_artifact_run_id:" in workflow
    assert "release_gate_evidence_asset:" in workflow
    assert "release_gate_evidence_artifact:" in workflow
    assert "h2ometa-remote-runner-release-gate-evidence" in workflow
    assert "permissions:\n  contents: read\n  actions: read" in workflow
    assert "contents: write" not in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in workflow
    assert "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b" in workflow
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert 'gh run download "$RELEASE_ARTIFACT_RUN_ID"' in workflow
    assert 'gh run view "$RELEASE_ARTIFACT_RUN_ID"' in workflow
    assert "Release Remote Runner Artifacts" in workflow
    assert "release artifact run headSha must match metadata.sourceCommit" in workflow
    assert "metadata.builder.runUrl does not reference release_artifact_run_id" in workflow
    assert '--name "h2ometa-remote-runner-release-${PLATFORM}"' in workflow
    assert '--name "h2ometa-remote-runner-release-published-assets-${PLATFORM}"' in workflow
    assert 'gh release download "$RELEASE_TAG"' in workflow
    assert "--ci-build-metadata dist/remote-runner/release-artifacts-metadata.json" in workflow
    assert "--manifest-metadata dist/remote-runner/release-manifest-metadata.json" in workflow
    assert "--attestations dist/remote-runner/release-attestations.json" in workflow
    assert "--release-gate-evidence dist/remote-runner/release-gate-evidence.json" in workflow
    assert "scripts/check_remote_runner_release_readiness.py" in workflow
    assert "release gate sourceCommit mismatch" in workflow
    assert "release gate remoteRunnerBundle sha256 mismatch" in workflow
    assert "published assets releaseTag mismatch" in workflow
    assert "updater.merge_published_asset_urls" in workflow
    assert "h2ometa-release-gate-evidence-registration.v1" in workflow
    assert "releaseGateEvidenceArtifact" in workflow
    assert "run.bat --web" not in workflow


def test_promotion_workflow_requires_registered_gate_evidence() -> None:
    workflow = Path(".github/workflows/promote-remote-runner-release.yml").read_text(encoding="utf-8")

    assert "release-gate-evidence-registration.json" in workflow
    assert 'gh run view "$RELEASE_GATE_EVIDENCE_RUN_ID"' in workflow
    assert "Register Remote Runner Release Gate Evidence" in workflow
    assert "release gate evidence run headSha must match metadata.sourceCommit" in workflow
    assert "release gate registration releaseArtifactRunId mismatch" in workflow
    assert "--release-gate-registration dist/remote-runner/release-gate-evidence-registration.json" in workflow
    assert '--release-artifact-run-id "$RELEASE_ARTIFACT_RUN_ID"' in workflow
    assert '--repository "$GH_REPO"' in workflow
