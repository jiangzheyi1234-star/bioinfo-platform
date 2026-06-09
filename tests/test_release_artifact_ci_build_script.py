from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import build_release_artifacts_in_ci as ci_builder


def test_ci_builder_copies_release_sources_from_immutable_ref_without_test_fixtures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    (repo_root / "apps" / "remote_runner").mkdir(parents=True)
    (repo_root / "core" / "contracts").mkdir(parents=True)
    calls: list[tuple[str, str]] = []
    file_writes: list[tuple[str, str]] = []

    def fake_release_files(local_dir: Path, source_ref: str) -> list[str]:
        calls.append((local_dir.relative_to(repo_root).as_posix(), source_ref))
        if local_dir.name == "remote_runner":
            return [
                "apps/remote_runner/main.py",
                "apps/remote_runner/pipelines/demo/.test/run-config.json",
            ]
        return ["core/contracts/workflow_design.py"]

    def fake_run_git(args, *, binary: bool = False):
        assert binary is True
        file_writes.append((args[1], args[0]))
        return b"# source\n"

    monkeypatch.setattr(ci_builder, "REPO_ROOT", repo_root)
    monkeypatch.setattr(ci_builder, "git_release_files_at_ref", fake_release_files)
    monkeypatch.setattr(ci_builder, "run_git", fake_run_git)

    ci_builder.copy_remote_runner_sources(tmp_path / "build", source_ref="abc123")

    assert calls == [
        ("apps/remote_runner", "abc123"),
        ("core/contracts", "abc123"),
    ]
    assert (tmp_path / "build" / "bundle" / "remote_runner" / "main.py").exists()
    assert (
        tmp_path / "build" / "bundle" / "remote_runner" / "pipelines" / "demo" / ".test" / "run-config.json"
    ).exists()
    assert (tmp_path / "build" / "bundle" / "core" / "contracts" / "workflow_design.py").exists()
    assert ("abc123:apps/remote_runner/main.py", "show") in file_writes
    assert ("abc123:apps/remote_runner/pipelines/demo/.test/run-config.json", "show") in file_writes


def test_ci_builder_requires_immutable_source_ref_and_clean_checkout(monkeypatch) -> None:
    calls: list[list[str]] = []
    source_ref = "a" * 40

    def fake_run_git(args, *, binary: bool = False):
        assert binary is False
        calls.append(args)
        if args == ["cat-file", "-t", source_ref]:
            return "commit\n"
        if args == ["rev-parse", f"{source_ref}^{{commit}}"]:
            return "a" * 40 + "\n"
        if args == ["rev-parse", "HEAD^{commit}"]:
            return "a" * 40 + "\n"
        if args == ["status", "--porcelain=v1"]:
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(ci_builder, "run_git", fake_run_git)

    assert ci_builder.ensure_source_ref_checked_out(source_ref) == "a" * 40
    assert ["status", "--porcelain=v1"] in calls


def test_ci_builder_rejects_mutable_source_ref(monkeypatch) -> None:
    monkeypatch.setattr(ci_builder, "run_git", lambda args, *, binary=False: "commit\n")

    for source_ref in ("main", "refs/tags/v0.1.1", "a" * 12):
        try:
            ci_builder.ensure_source_ref_checked_out(source_ref)
        except SystemExit as exc:
            assert "immutable --source-ref" in str(exc)
            assert "40-character commit SHA" in str(exc)
        else:
            raise AssertionError(f"mutable source ref was accepted: {source_ref}")


def test_ci_builder_materializes_lock_from_source_ref_and_validates_manifest_digest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    relative = "config/remote-runner-conda-specs/example/linux-64.explicit.txt"
    lock_text = "@EXPLICIT\nhttps://conda.example/pkg-1.0-0.conda\n"
    spec = SimpleNamespace(
        key="remote_runner",
        conda_explicit_specs={"linux-64": relative},
        lock_sha256={"linux-64": ci_builder.hashlib.sha256(lock_text.encode()).hexdigest()},
    )

    monkeypatch.setattr(ci_builder, "git_file_text", lambda source_ref, repo_relative_path: lock_text)

    path = ci_builder.materialize_lock_file(spec, platform="linux-64", source_ref="a" * 40, build_root=tmp_path)

    assert path.read_text(encoding="utf-8") == lock_text
    assert path.name == Path(relative).name


def test_ci_builder_release_manifest_metadata_uses_resolved_source_commit(tmp_path: Path) -> None:
    artifact_path = tmp_path / "h2ometa-remote-runner-0.1.1-control-plane-linux-64.tar.gz"
    sbom_path = tmp_path / f"{artifact_path.name}.spdx.json"
    metadata = ci_builder.build_metadata(
        artifacts=[
            {
                "artifactKey": "remote_runner",
                "version": "0.1.1-control-plane",
                "platform": "linux-64",
                "path": str(artifact_path),
                "sha256": "a" * 64,
                "sizeBytes": 123,
                "lock": {"sha256": "b" * 64},
                "sbom": {"path": str(sbom_path), "sha256": "c" * 64},
                "sourceRef": "d" * 40,
                "sourceCommit": "d" * 40,
            }
        ],
        source_ref="d" * 40,
        source_commit="d" * 40,
    )

    manifest_metadata = ci_builder.release_manifest_metadata(metadata)
    release_item = manifest_metadata["artifacts"]["remote_runner"]["linux-64"]

    assert release_item["sha256"] == "a" * 64
    assert release_item["sizeBytes"] == 123
    assert release_item["lockSha256"] == "b" * 64
    assert release_item["sbomFilename"].endswith(".spdx.json")
    assert release_item["downloadUrl"] == ""
    assert release_item["attestationUrl"] == ""
    assert release_item["sourceRef"] == "d" * 40
    assert release_item["sourceCommit"] == "d" * 40


def test_ci_builder_spdx_sbom_records_conda_explicit_packages(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.tar.gz"
    artifact_path.write_bytes(b"artifact")
    lock_path = tmp_path / "explicit.txt"
    lock_path.write_text(
        "@EXPLICIT\n"
        "https://conda.example/linux-64/python-3.12.0-h123_0.conda\n"
        "https://conda.example/noarch/snakemake-9.19.0-pyhd8ed1ab_0.tar.bz2\n",
        encoding="utf-8",
    )
    artifact = {
        "artifactKey": "workflow_runtime",
        "version": "0.1.0",
        "platform": "linux-64",
        "path": str(artifact_path),
        "sha256": "a" * 64,
        "lock": {"path": str(lock_path)},
    }

    sbom = ci_builder.write_spdx_sbom(artifact=artifact, output_dir=tmp_path, source_ref="a" * 40)
    payload = ci_builder.json.loads(Path(sbom["path"]).read_text(encoding="utf-8"))

    package_names = {item["name"] for item in payload["packages"]}
    assert "artifact.tar.gz" in package_names
    assert "python-3.12.0-h123_0" in package_names
    assert "snakemake-9.19.0-pyhd8ed1ab_0" in package_names
    assert {
        "spdxElementId": "SPDXRef-ReleaseArtifact",
        "relationshipType": "DEPENDS_ON",
        "relatedSpdxElement": "SPDXRef-CondaPackage-1",
    } in payload["relationships"]


def test_ci_builder_records_github_builder_identity(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "owner/repo/.github/workflows/release.yml@refs/tags/v1")

    metadata = ci_builder.build_metadata(
        artifacts=[{"artifactKey": "remote_runner", "sha256": "a" * 64}],
        source_ref="a" * 40,
        source_commit="a" * 40,
    )

    assert metadata["builder"]["type"] == "github-actions"
    assert metadata["builder"]["id"].endswith("@refs/tags/v1")
    assert metadata["builder"]["runUrl"] == "https://github.com/owner/repo/actions/runs/12345"
    assert metadata["sourceRef"] == "a" * 40
    assert metadata["sourceCommit"] == "a" * 40


def test_ci_builder_uses_controlled_linux_builder_not_ssh(monkeypatch) -> None:
    source = Path("scripts/build_release_artifacts_in_ci.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/release-remote-runner-artifacts.yml").read_text(encoding="utf-8")

    assert "ssh_connect" not in source
    assert "connect()" not in source
    assert "def ensure_source_ref_checked_out(" in source
    assert "CORE_RUNTIME_HELPER_FILES = (" in source
    assert "runner_builder.CORE_RUNTIME_HELPER_FILES" not in source
    assert "runs-on: ubuntu-24.04" in workflow
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in workflow
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in workflow
    assert "actions/attest@" not in workflow
    assert "attestations: write" not in workflow
    assert "artifact-metadata: write" not in workflow
    assert "ATTESTATION_BUNDLE_FILENAMES" in source
    assert "pending-release-asset:" in source
    assert "dist/remote-runner/*.spdx.json" in workflow
    assert "dist/remote-runner/release-manifest-metadata.json" in workflow
    assert "dist/remote-runner/release-attestations.json" in workflow
    assert "dist/remote-runner/attestation-bundles/*.intoto.json" in workflow
    assert "release-published-assets.json" in workflow
    assert 'dist.rglob("*")' in workflow
    assert "h2ometa-remote-runner-release-published-assets-${{ env.PLATFORM }}" in workflow
    assert "published release is missing expected assets" in workflow
    assert "gh release view" in workflow
    assert "--repo \"$GH_REPO\"" in workflow
    assert "contents: write" in workflow
    assert "gh release upload" in workflow
    assert "uv run --frozen python scripts/build_release_artifacts_in_ci.py" in workflow
