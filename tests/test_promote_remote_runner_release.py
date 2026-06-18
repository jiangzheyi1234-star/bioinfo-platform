from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _load_module() -> Any:
    script = Path("scripts/promote_remote_runner_release.py")
    spec = importlib.util.spec_from_file_location("promote_remote_runner_release", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_file(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Path]:
    source_commit = "a" * 40
    release_tag = "h2ometa-runtime-v0.1.2"
    runner = tmp_path / "h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz"
    workflow = tmp_path / "h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz"
    runner_sha = _write_file(runner, b"runner")
    workflow_sha = _write_file(workflow, b"workflow")
    runner.with_suffix(runner.suffix + ".sha256").write_text(f"{runner_sha}  {runner.name}\n", encoding="utf-8")
    workflow.with_suffix(workflow.suffix + ".sha256").write_text(
        f"{workflow_sha}  {workflow.name}\n",
        encoding="utf-8",
    )
    runner_sbom = tmp_path / f"{runner.name}.spdx.json"
    workflow_sbom = tmp_path / f"{workflow.name}.spdx.json"
    runner_sbom_sha = _write_file(runner_sbom, b"runner-sbom")
    workflow_sbom_sha = _write_file(workflow_sbom, b"workflow-sbom")
    paths = {
        "manifest": tmp_path / "manifest.json",
        "metadata": tmp_path / "release-artifacts-metadata.json",
        "manifest_metadata": tmp_path / "release-manifest-metadata.json",
        "attestations": tmp_path / "release-attestations.json",
        "github_attestations": tmp_path / "release-github-attestations.json",
        "published_assets": tmp_path / "release-published-assets.json",
        "gate": tmp_path / "release-gate-evidence.json",
        "summary": tmp_path / "release-promotion-summary.json",
        "candidate": tmp_path / "promoted-manifest.json",
    }
    _write_json(paths["manifest"], _manifest())
    _write_json(
        paths["metadata"],
        {
            "schemaVersion": "h2ometa-release-artifacts-ci.v1",
            "builder": {
                "type": "github-actions",
                "id": "owner/repo/.github/workflows/release-remote-runner-artifacts.yml@refs/tags/v0.1.2",
            },
            "sourceRef": source_commit,
            "sourceCommit": source_commit,
            "artifacts": [
                _artifact("remote_runner", runner, runner_sha, runner_sbom, runner_sbom_sha, source_commit),
                _artifact("workflow_runtime", workflow, workflow_sha, workflow_sbom, workflow_sbom_sha, source_commit),
            ],
        },
    )
    _write_json(
        paths["manifest_metadata"],
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
        paths["attestations"],
        {
            "schemaVersion": "h2ometa-release-attestations.v1",
            "provenance": {
                "attestationId": "b" * 64,
                "attestationUrl": "pending-release-asset:release-provenance.intoto.json",
                "bundleSha256": "b" * 64,
            },
            "sbom": {
                "remote_runner": {
                    "attestationId": "c" * 64,
                    "attestationUrl": "pending-release-asset:h2ometa-remote-runner-sbom.intoto.json",
                    "bundleSha256": "c" * 64,
                },
                "workflow_runtime": {
                    "attestationId": "d" * 64,
                    "attestationUrl": "pending-release-asset:h2ometa-workflow-runtime-sbom.intoto.json",
                    "bundleSha256": "d" * 64,
                },
            },
        },
    )
    _write_json(
        paths["github_attestations"],
        {
            "schemaVersion": "h2ometa-release-github-attestations.v1",
            "mode": "github-hosted-sigstore",
            "sourceCommit": source_commit,
            "provenance": {
                "attestationId": "101",
                "attestationUrl": "https://github.com/owner/repo/attestations/101",
                "bundlePath": "/tmp/provenance.json",
                "subjects": [
                    {"name": runner.name, "digest": {"sha256": runner_sha}},
                    {"name": workflow.name, "digest": {"sha256": workflow_sha}},
                ],
            },
            "sbom": {
                "remote_runner": {
                    "attestationId": "102",
                    "attestationUrl": "https://github.com/owner/repo/attestations/102",
                    "bundlePath": "/tmp/runner-sbom.json",
                    "subject": {"name": runner.name, "digest": {"sha256": runner_sha}},
                    "sbomFilename": runner_sbom.name,
                    "sbomSha256": runner_sbom_sha,
                },
                "workflow_runtime": {
                    "attestationId": "103",
                    "attestationUrl": "https://github.com/owner/repo/attestations/103",
                    "bundlePath": "/tmp/workflow-sbom.json",
                    "subject": {"name": workflow.name, "digest": {"sha256": workflow_sha}},
                    "sbomFilename": workflow_sbom.name,
                    "sbomSha256": workflow_sbom_sha,
                },
            },
        },
    )
    _write_json(
        paths["published_assets"],
        {
            "schemaVersion": "h2ometa-release-published-assets.v1",
            "repository": "owner/repo",
            "releaseTag": release_tag,
            "assets": {
                runner.name: _asset(1, runner_sha, runner.stat().st_size),
                workflow.name: _asset(2, workflow_sha, workflow.stat().st_size),
                runner_sbom.name: _asset(3, runner_sbom_sha, runner_sbom.stat().st_size),
                workflow_sbom.name: _asset(4, workflow_sbom_sha, workflow_sbom.stat().st_size),
                "release-provenance.intoto.json": _asset(5, "b" * 64, 100),
                "h2ometa-remote-runner-sbom.intoto.json": _asset(6, "c" * 64, 100),
                "h2ometa-workflow-runtime-sbom.intoto.json": _asset(7, "d" * 64, 100),
            },
        },
    )
    _write_json(paths["gate"], _release_gate(source_commit, runner_sha))
    return paths


def _manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifacts": {
            "remote_runner": {
                "name": "h2ometa-remote-runner",
                "service": "h2ometa-remote",
                "version": "0.1.1-control-plane",
                "default_platform": "linux-64",
            },
            "workflow_runtime": {
                "name": "h2ometa-workflow-runtime",
                "service": "h2ometa-workflow-runtime",
                "version": "0.1.0",
                "default_platform": "linux-64",
            },
        },
    }


def _artifact(
    key: str,
    path: Path,
    sha256: str,
    sbom_path: Path,
    sbom_sha256: str,
    source_commit: str,
) -> dict[str, Any]:
    return {
        "artifactKey": key,
        "version": "0.1.1-control-plane" if key == "remote_runner" else "0.1.0",
        "platform": "linux-64",
        "path": str(path),
        "sha256Path": str(path) + ".sha256",
        "sha256": sha256,
        "sizeBytes": path.stat().st_size,
        "lock": {"sha256": "e" * 64},
        "sbom": {"path": str(sbom_path), "sha256": sbom_sha256},
        "sourceRef": source_commit,
        "sourceCommit": source_commit,
    }


def _asset(asset_id: int, sha256: str, size: int) -> dict[str, Any]:
    return {
        "apiUrl": f"https://api.github.com/repos/owner/repo/releases/assets/{asset_id}",
        "digest": "sha256:" + sha256,
        "size": size,
    }


def _release_gate(source_commit: str, runner_sha: str) -> dict[str, Any]:
    return {
        "schemaVersion": "remote-runner-release-gate.v1",
        "ok": True,
        "sourceCommit": source_commit,
        "remoteRunnerBundle": {
            "path": "E:/code/bio_ui/resources/remote-runner/h2ometa-remote-runner.tar.gz",
            "sha256": runner_sha,
            "markers": ["remote_runner/execution_observability.py"],
        },
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
    }


def _argv(paths: dict[str, Path]) -> list[str]:
    return [
        "--manifest",
        str(paths["manifest"]),
        "--metadata",
        str(paths["metadata"]),
        "--manifest-metadata",
        str(paths["manifest_metadata"]),
        "--attestations",
        str(paths["attestations"]),
        "--published-assets",
        str(paths["published_assets"]),
        "--release-gate-evidence",
        str(paths["gate"]),
        "--release-tag",
        "h2ometa-runtime-v0.1.2",
        "--output-manifest",
        str(paths["candidate"]),
        "--summary-json",
        str(paths["summary"]),
    ]


def test_promote_release_generates_candidate_manifest_and_summary(tmp_path: Path, monkeypatch) -> None:
    promote = _load_module()
    paths = _fixture(tmp_path)
    monkeypatch.setattr(promote, "git_commit", lambda ref: "a" * 40)

    assert promote.main(_argv(paths)) == 0

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["schemaVersion"] == "h2ometa-remote-runner-release-promotion.v1"
    assert summary["sourceCommit"] == "a" * 40
    assert candidate["artifacts"]["remote_runner"]["download_urls"]["linux-64"].endswith("/1")
    assert candidate["artifacts"]["workflow_runtime"]["attestation_urls"]["linux-64"].endswith("/7")
    assert "pending-release-asset:" not in json.dumps(candidate)


def test_promote_release_prefers_github_hosted_attestation_urls(tmp_path: Path, monkeypatch) -> None:
    promote = _load_module()
    paths = _fixture(tmp_path)
    monkeypatch.setattr(promote, "git_commit", lambda ref: "a" * 40)

    assert promote.main([*_argv(paths), "--github-attestations", str(paths["github_attestations"])]) == 0

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert any(check["name"] == "github-hosted-attestations" for check in summary["checks"])
    assert candidate["artifacts"]["remote_runner"]["provenance_urls"]["linux-64"].endswith("/attestations/101")
    assert candidate["artifacts"]["workflow_runtime"]["attestation_urls"]["linux-64"].endswith("/attestations/103")


def test_promote_release_accepts_disabled_github_attestation_summary(tmp_path: Path, monkeypatch) -> None:
    promote = _load_module()
    paths = _fixture(tmp_path)
    payload = json.loads(paths["github_attestations"].read_text(encoding="utf-8"))
    payload["mode"] = "disabled-by-input"
    payload["provenance"]["attestationId"] = ""
    payload["provenance"]["attestationUrl"] = ""
    for entry in payload["sbom"].values():
        entry["attestationId"] = ""
        entry["attestationUrl"] = ""
    _write_json(paths["github_attestations"], payload)
    monkeypatch.setattr(promote, "git_commit", lambda ref: "a" * 40)

    assert promote.main([*_argv(paths), "--github-attestations", str(paths["github_attestations"])]) == 0

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    candidate = json.loads(paths["candidate"].read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert any(
        check["name"] == "github-attestations-summary" and check["mode"] == "disabled-by-input"
        for check in summary["checks"]
    )
    assert candidate["artifacts"]["remote_runner"]["provenance_urls"]["linux-64"].endswith("/5")
    assert candidate["artifacts"]["workflow_runtime"]["attestation_urls"]["linux-64"].endswith("/7")


def test_promote_release_can_require_github_hosted_attestations(tmp_path: Path, monkeypatch) -> None:
    promote = _load_module()
    paths = _fixture(tmp_path)
    payload = json.loads(paths["github_attestations"].read_text(encoding="utf-8"))
    payload["mode"] = "disabled-by-input"
    _write_json(paths["github_attestations"], payload)
    monkeypatch.setattr(promote, "git_commit", lambda ref: "a" * 40)

    assert (
        promote.main(
            [
                *_argv(paths),
                "--github-attestations",
                str(paths["github_attestations"]),
                "--require-github-attestations",
            ]
        )
        == 1
    )

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert "does not contain hosted GitHub attestations" in json.dumps(summary)


def test_promote_release_rejects_release_gate_source_mismatch(tmp_path: Path, monkeypatch) -> None:
    promote = _load_module()
    paths = _fixture(tmp_path)
    gate = json.loads(paths["gate"].read_text(encoding="utf-8"))
    gate["sourceCommit"] = "f" * 40
    _write_json(paths["gate"], gate)
    monkeypatch.setattr(promote, "git_commit", lambda ref: "a" * 40)

    assert promote.main(_argv(paths)) == 1

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert "release gate sourceCommit mismatch" in json.dumps(summary)


def test_promote_release_rejects_release_gate_bundle_mismatch(tmp_path: Path, monkeypatch) -> None:
    promote = _load_module()
    paths = _fixture(tmp_path)
    gate = json.loads(paths["gate"].read_text(encoding="utf-8"))
    gate["remoteRunnerBundle"]["sha256"] = "f" * 64
    _write_json(paths["gate"], gate)
    monkeypatch.setattr(promote, "git_commit", lambda ref: "a" * 40)

    assert promote.main(_argv(paths)) == 1

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert "remoteRunnerBundle sha256 mismatch" in json.dumps(summary)


def test_promote_release_rejects_pending_production_manifest_fields(tmp_path: Path, monkeypatch) -> None:
    promote = _load_module()
    paths = _fixture(tmp_path)
    monkeypatch.setattr(promote, "git_commit", lambda ref: "a" * 40)
    original_update_manifest = promote.updater.update_manifest

    def fake_update_manifest(*args, **kwargs):
        candidate = original_update_manifest(*args, **kwargs)
        candidate["artifacts"]["remote_runner"]["attestation_urls"]["linux-64"] = "pending:manual-review"
        return candidate

    monkeypatch.setattr(promote.updater, "update_manifest", fake_update_manifest)

    assert promote.main(_argv(paths)) == 1

    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary["ok"] is False
    assert "pending production field" in json.dumps(summary)


def test_promote_release_apply_writes_manifest_only_after_checks(tmp_path: Path, monkeypatch) -> None:
    promote = _load_module()
    paths = _fixture(tmp_path)
    monkeypatch.setattr(promote, "git_commit", lambda ref: "a" * 40)

    assert promote.main([*_argv(paths), "--apply"]) == 0

    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert manifest["artifacts"]["remote_runner"]["source_commits"]["linux-64"] == "a" * 40
    assert summary["appliedManifest"] == str(paths["manifest"])
