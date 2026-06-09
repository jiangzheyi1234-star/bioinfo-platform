from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from pathlib import Path

import pytest

from core.remote_runner.artifact import (
    RemoteRunnerArtifactError,
    RemoteRunnerArtifactProvider,
    WorkflowRuntimeArtifactProvider,
)
from core.remote_runner.artifact_diagnostics import supply_chain_metadata
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.release_manifest import (
    REMOTE_RUNNER_ARTIFACT,
    ReleaseArtifactSpec,
    WORKFLOW_RUNTIME_ARTIFACT,
    WORKFLOW_RUNTIME_VERSION,
)
from tests.helpers.remote_runner_artifact_checks import staged_artifact_matches_manifest


def _write_artifact(
    path: Path,
    *,
    version: str = "0.1.0-control-plane",
    platform: str = "linux-64",
    content: bytes = b"artifact",
    include_wrapper_assets: bool = True,
    runtime_python_mode: int = 0o755,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "service": "h2ometa-remote",
        "version": version,
        "platform": platform,
        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
    }
    with tarfile.open(path, "w:gz") as archive:
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        manifest_info = tarfile.TarInfo("bootstrap_manifest.json")
        manifest_info.size = len(manifest_bytes)
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
        content_info = tarfile.TarInfo("payload.txt")
        content_info.size = len(content)
        archive.addfile(content_info, io.BytesIO(content))
        python_link = tarfile.TarInfo("runtime/bin/python")
        python_link.type = tarfile.SYMTYPE
        python_link.mode = 0o777
        python_link.linkname = "python3.12"
        archive.addfile(python_link)
        python_payload = b"#!/usr/bin/env python\n"
        python_info = tarfile.TarInfo("runtime/bin/python3.12")
        python_info.mode = runtime_python_mode
        python_info.size = len(python_payload)
        archive.addfile(python_info, io.BytesIO(python_payload))
        conda_unpack_payload = b"#!/usr/bin/env python\n"
        conda_unpack_info = tarfile.TarInfo("runtime/bin/conda-unpack")
        conda_unpack_info.mode = 0o755
        conda_unpack_info.size = len(conda_unpack_payload)
        archive.addfile(conda_unpack_info, io.BytesIO(conda_unpack_payload))
        if include_wrapper_assets:
            for name in RemoteRunnerArtifactProvider.REQUIRED_WRAPPER_ASSET_MEMBERS:
                payload = b"placeholder\n"
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
    payload = path.read_bytes()
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )


def _write_workflow_artifact(
    path: Path,
    *,
    version: str = "0.1.0",
    platform: str = "linux-64",
    service: str = "h2ometa-workflow-runtime",
    snakemake_package: str = "9.19.0",
    include_snakemake_package: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "service": service,
        "version": version,
        "platform": platform,
        "provider": "conda-pack",
        "entrypoints": {
            "python": "workflow-env/bin/python",
            "conda": "workflow-env/bin/conda",
            "condaUnpack": "workflow-env/bin/conda-unpack",
            "snakemake": "workflow-env/bin/snakemake",
        },
        "packages": {"snakemake": snakemake_package},
    }
    with tarfile.open(path, "w:gz") as archive:
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        manifest_info = tarfile.TarInfo("bootstrap_manifest.json")
        manifest_info.size = len(manifest_bytes)
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
        for name in (
            "workflow-env/bin/python",
            "workflow-env/bin/conda",
            "workflow-env/bin/conda-unpack",
            "workflow-env/bin/snakemake",
        ):
            payload = b"#!/usr/bin/env bash\n"
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if include_snakemake_package:
            payload = b""
            info = tarfile.TarInfo("workflow-env/lib/python3.12/site-packages/snakemake/__init__.py")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    payload = path.read_bytes()
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )


def _normalized_tar_names(archive: tarfile.TarFile) -> set[str]:
    return {member.name.lstrip("./") for member in archive.getmembers()}


def _extract_normalized(archive: tarfile.TarFile, name: str) -> tarfile.ExFileObject | None:
    normalized = name.lstrip("./")
    for member in archive.getmembers():
        if member.name.lstrip("./") == normalized:
            return archive.extractfile(member)
    raise KeyError(name)


def _local_staged_release_artifact_or_skip(repo_root: Path, filename: str) -> Path:
    bundle = repo_root / "resources" / "remote-runner" / filename
    if not bundle.exists():
        pytest.skip(
            "release artifact tarballs are external; run scripts/check_remote_runner_release_artifacts.py "
            "with release download credentials to verify artifact contents"
        )
    if filename == REMOTE_RUNNER_ARTIFACT.archive_filename("linux-64") and not staged_artifact_matches_manifest(
        bundle, REMOTE_RUNNER_ARTIFACT, platform="linux-64"
    ):
        pytest.skip("local staged release artifact is stale relative to the release manifest")
    return bundle


def _spec_with_download_url(
    *,
    key: str,
    name: str,
    service: str,
    version: str,
    bundle_env_var: str,
    search_root_env_var: str,
    url: str,
    sha256: str,
    size_bytes: int,
) -> ReleaseArtifactSpec:
    return ReleaseArtifactSpec(
        key=key,
        name=name,
        service=service,
        version=version,
        default_platform="linux-64",
        bundle_env_var=bundle_env_var,
        search_root_env_vars=(search_root_env_var,),
        conda_explicit_specs={},
        sha256={"linux-64": sha256},
        size_bytes={"linux-64": size_bytes},
        lock_sha256={},
        download_urls={"linux-64": url},
    )


def _spec_with_supply_chain_metadata() -> ReleaseArtifactSpec:
    return ReleaseArtifactSpec(
        key="remote_runner",
        name="h2ometa-remote-runner",
        service="h2ometa-remote",
        version="0.1.1-control-plane",
        default_platform="linux-64",
        bundle_env_var="H2OMETA_REMOTE_RUNNER_BUNDLE",
        search_root_env_vars=("H2OMETA_REMOTE_RUNNER_DIR",),
        conda_explicit_specs={"linux-64": "config/lock.txt"},
        sha256={"linux-64": "a" * 64},
        size_bytes={"linux-64": 123},
        lock_sha256={"linux-64": "b" * 64},
        download_urls={"linux-64": "https://example.invalid/artifact.tar.gz"},
        sbom_urls={"linux-64": "https://example.invalid/artifact.spdx.json"},
        attestation_urls={"linux-64": "https://example.invalid/artifact.intoto.jsonl"},
        builder_ids={"linux-64": "github-actions://repo/.github/workflows/release.yml"},
        source_refs={"linux-64": "a" * 40},
        source_commits={"linux-64": "a" * 40},
    )


def test_release_artifact_spec_supports_supply_chain_metadata() -> None:
    spec = _spec_with_supply_chain_metadata()

    metadata = supply_chain_metadata(spec, platform="linux-64")

    assert metadata["complete"] is True
    assert metadata["sbomUrl"].endswith(".spdx.json")
    assert metadata["attestationUrl"].endswith(".intoto.jsonl")
    assert metadata["builderId"].startswith("github-actions://")
    assert metadata["sourceRef"] == "a" * 40
    assert metadata["sourceCommit"] == "a" * 40
    assert metadata["missingRequired"] == []
    assert metadata["missingOptional"] == []


def test_supply_chain_metadata_rejects_mutable_source_ref() -> None:
    spec = _spec_with_supply_chain_metadata()
    spec = ReleaseArtifactSpec(
        **{
            **spec.__dict__,
            "source_refs": {"linux-64": "refs/tags/v0.1.1-control-plane"},
        }
    )

    metadata = supply_chain_metadata(spec, platform="linux-64")

    assert metadata["complete"] is False
    assert metadata["invalidFields"] == ["sourceRef"]


def test_supply_chain_metadata_requires_sbom_source_builder_and_provenance_or_attestation() -> None:
    spec = ReleaseArtifactSpec(
        key="workflow_runtime",
        name="h2ometa-workflow-runtime",
        service="h2ometa-workflow-runtime",
        version="0.1.0",
        default_platform="linux-64",
        bundle_env_var="H2OMETA_WORKFLOW_RUNTIME_BUNDLE",
        search_root_env_vars=("H2OMETA_WORKFLOW_RUNTIME_DIR",),
        conda_explicit_specs={},
        sha256={},
        size_bytes={},
        lock_sha256={},
        download_urls={},
    )

    metadata = supply_chain_metadata(spec, platform="linux-64")

    assert metadata["complete"] is False
    assert metadata["missingRequired"] == [
        "sbomUrl",
        "builderId",
        "sourceRef",
        "sourceCommit",
        "provenanceUrl|attestationUrl",
        "signatureUrl|attestationUrl",
    ]


def test_artifact_provider_resolves_explicit_bundle_and_verifies_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "custom-runner.tar.gz"
    _write_artifact(bundle, version="dev", content=b"runner-bundle")
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))

    resolved = RemoteRunnerArtifactProvider(search_roots=[]).resolve("dev", platform="linux-64")

    assert resolved.archive_path == bundle
    assert resolved.platform == "linux-64"
    assert resolved.sha256 == hashlib.sha256(bundle.read_bytes()).hexdigest()


def test_artifact_provider_fails_when_checksum_does_not_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "custom-runner.tar.gz"
    bundle.write_bytes(b"runner-bundle")
    bundle.with_suffix(bundle.suffix + ".sha256").write_text("0" * 64, encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))

    with pytest.raises(RemoteRunnerArtifactError, match="sha256 mismatch"):
        RemoteRunnerArtifactProvider(search_roots=[]).resolve("dev")


def test_artifact_provider_finds_versioned_resources_artifact(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    version = "0.1.0-control-plane"
    bundle = root / "resources" / "remote-runner" / f"h2ometa-remote-runner-{version}-linux-64.tar.gz"
    _write_artifact(bundle, version=version, platform="linux-64", content=b"versioned")

    resolved = RemoteRunnerArtifactProvider(repo_root=root).resolve(version, platform="linux-64")

    assert resolved.archive_path == bundle


def test_artifact_provider_finds_versioned_dist_artifact(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    version = "dist-control-plane"
    bundle = root / "dist" / "remote-runner" / f"h2ometa-remote-runner-{version}-linux-64.tar.gz"
    _write_artifact(bundle, version=version, platform="linux-64", content=b"dist")

    resolved = RemoteRunnerArtifactProvider(repo_root=root).resolve(version, platform="linux-64")

    assert resolved.archive_path == bundle


def test_artifact_provider_finds_remote_runner_env_root_before_repo_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    version = "env-control-plane"
    env_root = tmp_path / "env-root"
    bundle = env_root / f"h2ometa-remote-runner-{version}-linux-64.tar.gz"
    _write_artifact(bundle, version=version, platform="linux-64", content=b"env")
    stale_repo_bundle = root / "resources" / "remote-runner" / bundle.name
    _write_artifact(stale_repo_bundle, version=version, platform="linux-64", content=b"repo")
    monkeypatch.delenv("H2OMETA_REMOTE_RUNNER_BUNDLE", raising=False)
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_DIR", str(env_root))

    resolved = RemoteRunnerArtifactProvider(repo_root=root).resolve(version, platform="linux-64")

    assert resolved.archive_path == bundle


def test_workflow_runtime_provider_finds_env_root_before_repo_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    version = "env-workflow"
    env_root = tmp_path / "workflow-env-root"
    bundle = env_root / f"h2ometa-workflow-runtime-{version}-linux-64.tar.gz"
    _write_workflow_artifact(bundle, version=version, platform="linux-64")
    stale_repo_bundle = root / "resources" / "remote-runner" / bundle.name
    _write_workflow_artifact(stale_repo_bundle, version=version, platform="linux-64", snakemake_package="9.0.0")
    monkeypatch.delenv("H2OMETA_WORKFLOW_RUNTIME_BUNDLE", raising=False)
    monkeypatch.setenv("H2OMETA_WORKFLOW_RUNTIME_DIR", str(env_root))

    resolved = WorkflowRuntimeArtifactProvider(repo_root=root).resolve(version, platform="linux-64")

    assert resolved.archive_path == bundle
    assert resolved.snakemake_entrypoint == "workflow-env/bin/snakemake"


def test_artifact_provider_rejects_platform_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = tmp_path / "custom-runner.tar.gz"
    _write_artifact(bundle, version="dev", platform="linux-aarch64")
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))

    with pytest.raises(RemoteRunnerArtifactError, match="platform mismatch"):
        RemoteRunnerArtifactProvider(search_roots=[]).resolve("dev", platform="linux-64")


def test_artifact_provider_rejects_missing_profile_wrapper_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "custom-runner.tar.gz"
    _write_artifact(bundle, version="dev", include_wrapper_assets=False)
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))

    with pytest.raises(RemoteRunnerArtifactError, match="missing bundled Snakemake wrapper assets"):
        RemoteRunnerArtifactProvider(search_roots=[]).resolve("dev", platform="linux-64")


def test_artifact_provider_rejects_non_executable_bundled_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "custom-runner.tar.gz"
    _write_artifact(bundle, version="dev", runtime_python_mode=0o664)
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))

    with pytest.raises(RemoteRunnerArtifactError, match="runtime executable is not executable"):
        RemoteRunnerArtifactProvider(search_roots=[]).resolve("dev", platform="linux-64")


def test_artifact_validation_uses_specific_archive_parse_errors() -> None:
    root = Path(__file__).resolve().parents[1] / "core" / "remote_runner"
    io_source = (root / "artifact_io.py").read_text(encoding="utf-8")
    runner_validation_source = (root / "remote_runner_artifact_validation.py").read_text(encoding="utf-8")
    workflow_validation_source = (root / "workflow_runtime_artifact_validation.py").read_text(encoding="utf-8")

    wrapper_source = runner_validation_source.split("def verify_required_wrapper_assets(", 1)[1]
    manifest_source = io_source.split("def read_manifest(", 1)[1]
    manifest_source = manifest_source.split("def validated_member_names(", 1)[0]
    workflow_source = workflow_validation_source.split("def verify_workflow_runtime_contents(", 1)[1]

    for block in (wrapper_source, manifest_source, workflow_source):
        assert "except Exception" not in block


def test_artifact_provider_delegates_io_and_runtime_validation_details() -> None:
    root = Path(__file__).resolve().parents[1]
    artifact_path = root / "core" / "remote_runner" / "artifact.py"
    io_path = root / "core" / "remote_runner" / "artifact_io.py"
    runner_validation_path = root / "core" / "remote_runner" / "remote_runner_artifact_validation.py"
    workflow_validation_path = root / "core" / "remote_runner" / "workflow_runtime_artifact_validation.py"

    assert io_path.exists()
    assert runner_validation_path.exists()
    assert workflow_validation_path.exists()

    artifact_source = artifact_path.read_text(encoding="utf-8")
    io_source = io_path.read_text(encoding="utf-8")
    runner_validation_source = runner_validation_path.read_text(encoding="utf-8")
    workflow_validation_source = workflow_validation_path.read_text(encoding="utf-8")

    assert len(artifact_source.splitlines()) <= 260
    assert "from core.remote_runner.artifact_io import" in artifact_source
    assert "from core.remote_runner.remote_runner_artifact_validation import verify_required_wrapper_assets" in artifact_source
    assert "from core.remote_runner.workflow_runtime_artifact_validation import" in artifact_source

    for helper_name in (
        "_download_declared_archive",
        "_artifact_cache_root",
        "_download_headers",
        "_read_expected_sha256",
        "_sha256_file",
        "_read_manifest",
        "_validated_member_names",
        "_verify_bundled_runtime_entrypoints",
        "_verify_required_wrapper_assets",
        "_verify_workflow_runtime_contents",
    ):
        assert f"def {helper_name}(" not in artifact_source
    assert "urlopen" not in artifact_source
    assert "shutil.copyfileobj" not in artifact_source
    assert "PurePosixPath" not in artifact_source

    assert "def resolve_archive_path(" in io_source
    assert "def download_declared_archive(" in io_source
    assert "def read_manifest(" in io_source
    assert "def validated_member_names(" in io_source
    assert "def verify_bundled_runtime_entrypoints(" in runner_validation_source
    assert "def verify_required_wrapper_assets(" in runner_validation_source
    assert "def verify_workflow_runtime_contents(" in workflow_validation_source


def test_artifact_provider_downloads_declared_artifact_to_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = "downloaded-control-plane"
    filename = f"h2ometa-remote-runner-{version}-linux-64.tar.gz"
    source = tmp_path / "release" / filename
    _write_artifact(source, version=version, platform="linux-64", content=b"downloaded")
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    cache_root = tmp_path / "artifact-cache"
    monkeypatch.setenv("H2OMETA_ARTIFACT_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(
        "core.remote_runner.artifact.REMOTE_RUNNER_ARTIFACT",
        _spec_with_download_url(
            key="remote_runner",
            name="h2ometa-remote-runner",
            service="h2ometa-remote",
            version=version,
            bundle_env_var="H2OMETA_REMOTE_RUNNER_BUNDLE",
            search_root_env_var="H2OMETA_REMOTE_RUNNER_DIR",
            url=source.as_uri(),
            sha256=sha256,
            size_bytes=source.stat().st_size,
        ),
    )

    resolved = RemoteRunnerArtifactProvider(search_roots=[]).resolve(version, platform="linux-64")

    expected_path = cache_root / "remote_runner" / version / "linux-64" / filename
    assert resolved.archive_path == expected_path
    assert resolved.sha256 == sha256
    assert expected_path.read_bytes() == source.read_bytes()
    assert expected_path.with_suffix(expected_path.suffix + ".sha256").read_text(encoding="utf-8") == (
        f"{sha256}  {filename}\n"
    )


def test_artifact_provider_reuses_concurrent_valid_cache_when_replace_is_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = "downloaded-control-plane"
    filename = f"h2ometa-remote-runner-{version}-linux-64.tar.gz"
    source = tmp_path / "release" / filename
    _write_artifact(source, version=version, platform="linux-64", content=b"downloaded")
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    cache_root = tmp_path / "artifact-cache"
    expected_path = cache_root / "remote_runner" / version / "linux-64" / filename
    monkeypatch.setenv("H2OMETA_ARTIFACT_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(
        "core.remote_runner.artifact.REMOTE_RUNNER_ARTIFACT",
        _spec_with_download_url(
            key="remote_runner",
            name="h2ometa-remote-runner",
            service="h2ometa-remote",
            version=version,
            bundle_env_var="H2OMETA_REMOTE_RUNNER_BUNDLE",
            search_root_env_var="H2OMETA_REMOTE_RUNNER_DIR",
            url=source.as_uri(),
            sha256=sha256,
            size_bytes=source.stat().st_size,
        ),
    )

    def locked_replace(src: str | bytes | os.PathLike[str], dst: str | bytes | os.PathLike[str]) -> None:
        Path(dst).write_bytes(Path(src).read_bytes())
        raise PermissionError("target is locked by concurrent downloader")

    monkeypatch.setattr("core.remote_runner.artifact_io.os.replace", locked_replace)

    resolved = RemoteRunnerArtifactProvider(search_roots=[]).resolve(version, platform="linux-64")

    assert resolved.archive_path == expected_path
    assert expected_path.read_bytes() == source.read_bytes()
    assert not list(expected_path.parent.glob(f"{filename}.*.tmp"))


def test_artifact_provider_ignores_stale_repo_candidate_and_downloads_manifest_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = "downloaded-control-plane"
    filename = f"h2ometa-remote-runner-{version}-linux-64.tar.gz"
    stale_repo_bundle = tmp_path / "repo" / "resources" / "remote-runner" / filename
    _write_artifact(stale_repo_bundle, version=version, platform="linux-64", content=b"stale")
    source = tmp_path / "release" / filename
    _write_artifact(source, version=version, platform="linux-64", content=b"declared")
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    cache_root = tmp_path / "artifact-cache"
    monkeypatch.setenv("H2OMETA_ARTIFACT_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(
        "core.remote_runner.artifact.REMOTE_RUNNER_ARTIFACT",
        _spec_with_download_url(
            key="remote_runner",
            name="h2ometa-remote-runner",
            service="h2ometa-remote",
            version=version,
            bundle_env_var="H2OMETA_REMOTE_RUNNER_BUNDLE",
            search_root_env_var="H2OMETA_REMOTE_RUNNER_DIR",
            url=source.as_uri(),
            sha256=sha256,
            size_bytes=source.stat().st_size,
        ),
    )

    resolved = RemoteRunnerArtifactProvider(repo_root=tmp_path / "repo").resolve(version, platform="linux-64")

    assert resolved.archive_path == cache_root / "remote_runner" / version / "linux-64" / filename
    assert resolved.sha256 == sha256


def test_workflow_runtime_provider_resolves_conda_pack_artifact(tmp_path: Path) -> None:
    bundle = tmp_path / "h2ometa-workflow-runtime-local-workflow-linux-64.tar.gz"
    _write_workflow_artifact(bundle, version="local-workflow")

    resolved = WorkflowRuntimeArtifactProvider(search_roots=[tmp_path]).resolve("local-workflow", platform="linux-64")

    assert resolved.archive_path == bundle
    assert resolved.snakemake_entrypoint == "workflow-env/bin/snakemake"
    assert resolved.conda_unpack_entrypoint == "workflow-env/bin/conda-unpack"


def test_workflow_runtime_provider_rejects_wrong_service(tmp_path: Path) -> None:
    bundle = tmp_path / "h2ometa-workflow-runtime-local-workflow-linux-64.tar.gz"
    _write_workflow_artifact(bundle, version="local-workflow", service="h2ometa-remote")

    with pytest.raises(RemoteRunnerArtifactError, match="unexpected service"):
        WorkflowRuntimeArtifactProvider(search_roots=[tmp_path]).resolve("local-workflow", platform="linux-64")


def test_workflow_runtime_provider_rejects_artifact_missing_snakemake_package(tmp_path: Path) -> None:
    bundle = tmp_path / "h2ometa-workflow-runtime-local-workflow-linux-64.tar.gz"
    _write_workflow_artifact(bundle, version="local-workflow", include_snakemake_package=False)

    with pytest.raises(RemoteRunnerArtifactError, match="missing snakemake Python package"):
        WorkflowRuntimeArtifactProvider(search_roots=[tmp_path]).resolve("local-workflow", platform="linux-64")


def test_workflow_runtime_provider_rejects_missing_snakemake_package_version(tmp_path: Path) -> None:
    bundle = tmp_path / "h2ometa-workflow-runtime-local-workflow-linux-64.tar.gz"
    _write_workflow_artifact(bundle, version="local-workflow", snakemake_package="")

    with pytest.raises(RemoteRunnerArtifactError, match="must declare snakemake package version"):
        WorkflowRuntimeArtifactProvider(search_roots=[tmp_path]).resolve("local-workflow", platform="linux-64")


def test_workflow_runtime_provider_downloads_declared_artifact_to_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = "downloaded-workflow"
    filename = f"h2ometa-workflow-runtime-{version}-linux-64.tar.gz"
    source = tmp_path / "release" / filename
    _write_workflow_artifact(source, version=version, platform="linux-64")
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    cache_root = tmp_path / "artifact-cache"
    monkeypatch.setenv("H2OMETA_ARTIFACT_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(
        "core.remote_runner.artifact.WORKFLOW_RUNTIME_ARTIFACT",
        _spec_with_download_url(
            key="workflow_runtime",
            name="h2ometa-workflow-runtime",
            service="h2ometa-workflow-runtime",
            version=version,
            bundle_env_var="H2OMETA_WORKFLOW_RUNTIME_BUNDLE",
            search_root_env_var="H2OMETA_WORKFLOW_RUNTIME_DIR",
            url=source.as_uri(),
            sha256=sha256,
            size_bytes=source.stat().st_size,
        ),
    )

    resolved = WorkflowRuntimeArtifactProvider(search_roots=[]).resolve(version, platform="linux-64")

    expected_path = cache_root / "workflow_runtime" / version / "linux-64" / filename
    assert resolved.archive_path == expected_path
    assert resolved.sha256 == sha256
    assert resolved.snakemake_entrypoint == "workflow-env/bin/snakemake"


def test_release_artifact_preflight_has_supply_chain_strict_gate() -> None:
    source = (Path.cwd() / "scripts" / "check_remote_runner_release_artifacts.py").read_text(encoding="utf-8")

    assert "--require-supply-chain" in source
    assert "pendingFields" in source
    assert "invalidFields" in source
    assert "release supply-chain metadata incomplete" in source


def test_release_manifest_records_supply_chain_assets_for_ci_handoff() -> None:
    runner, workflow = (
        supply_chain_metadata(REMOTE_RUNNER_ARTIFACT, platform=REMOTE_RUNNER_ARTIFACT.default_platform),
        supply_chain_metadata(WORKFLOW_RUNTIME_ARTIFACT, platform=WORKFLOW_RUNTIME_ARTIFACT.default_platform),
    )

    for metadata in (runner, workflow):
        assert metadata["complete"] is True
        assert metadata["pendingFields"] == []
        assert metadata["missingRequired"] == []
        assert metadata["invalidFields"] == []
        assert metadata["sbomUrl"].startswith("https://api.github.com/")
        assert metadata["attestationUrl"].startswith("https://api.github.com/")
        assert metadata["signatureUrl"].startswith("https://api.github.com/")
        assert ".github/workflows/release-remote-runner-artifacts.yml@" in metadata["builderId"]
        assert metadata["sourceRef"] == metadata["sourceCommit"]


def test_local_staged_remote_runner_artifact_contains_current_runtime_contract() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )

    resolved = RemoteRunnerArtifactProvider(repo_root=repo_root).resolve(REMOTE_RUNNER_VERSION, platform="linux-64")

    assert resolved.archive_path == bundle
    with tarfile.open(bundle, "r:gz") as archive:
        names = _normalized_tar_names(archive)
        config = _extract_normalized(archive, "remote_runner/config.py")
        workflow_runtime_config = _extract_normalized(archive, "remote_runner/workflow_runtime_config.py")
        health_service = _extract_normalized(archive, "remote_runner/health_service.py")
        health_routes = _extract_normalized(archive, "remote_runner/health_routes.py")
        control_service = _extract_normalized(archive, "remote_runner/control_service.py")
        main = _extract_normalized(archive, "remote_runner/main.py")
        executor = _extract_normalized(archive, "remote_runner/executor.py")
        workflow_engine_adapter = _extract_normalized(archive, "remote_runner/workflow_engine_adapter.py")
        assert config is not None
        assert workflow_runtime_config is not None
        assert health_service is not None
        assert health_routes is not None
        assert control_service is not None
        assert main is not None
        assert executor is not None
        assert workflow_engine_adapter is not None
        config_text = config.read().decode("utf-8")
        workflow_runtime_config_text = workflow_runtime_config.read().decode("utf-8")
        health_service_text = health_service.read().decode("utf-8")
        health_routes_text = health_routes.read().decode("utf-8")
        control_service_text = control_service.read().decode("utf-8")
        main_text = main.read().decode("utf-8")
        executor_text = executor.read().decode("utf-8")
        workflow_engine_adapter_text = workflow_engine_adapter.read().decode("utf-8")

    assert "remote_runner/workflow_runtime_config.py" in names
    assert "remote_runner/health_service.py" in names
    assert "remote_runner/health_routes.py" in names
    assert "remote_runner/control_service.py" in names
    assert "remote_runner/workflow_engine_adapter.py" in names
    assert "workflow_runtime_version" in config_text
    assert "inspect_workflow_runtime" in config_text
    assert "def inspect_workflow_runtime" in workflow_runtime_config_text
    assert "def build_workflow_runtime_environment" in workflow_runtime_config_text
    assert 'checks["workflow_runtime"]' in health_service_text
    assert "health_ready_from_request" in health_routes_text
    assert "build_health_ready_payload" in control_service_text
    assert "app.include_router(health_router)" in main_text
    assert "SnakemakeEngineAdapter" in executor_text
    assert "build_workflow_runtime_environment" in workflow_engine_adapter_text


def test_local_staged_remote_runner_artifact_matches_storage_core_source() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )

    with tarfile.open(bundle, "r:gz") as archive:
        storage_core = _extract_normalized(archive, "remote_runner/storage_core.py")
        assert storage_core is not None
        packaged_text = storage_core.read().decode("utf-8")

    source_text = (repo_root / "apps" / "remote_runner" / "storage_core.py").read_text(encoding="utf-8")
    assert packaged_text == source_text


def test_local_staged_remote_runner_artifact_contains_workflow_design_contract_dependency() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )

    resolved = RemoteRunnerArtifactProvider(repo_root=repo_root).resolve(REMOTE_RUNNER_VERSION, platform="linux-64")

    assert resolved.archive_path == bundle
    required_members = {
        "remote_runner/workflow_design_compiler.py",
        "remote_runner/workflow_design_planner.py",
        "remote_runner/workflow_design_routes.py",
        "remote_runner/workflow_design_storage.py",
        "remote_runner/workflow_design_submission.py",
    }
    with tarfile.open(bundle, "r:gz") as archive:
        names = _normalized_tar_names(archive)
        main = _extract_normalized(archive, "remote_runner/main.py")
        assert main is not None
        main_text = main.read().decode("utf-8")

    assert required_members.issubset(names)
    assert (
        {
            "core/__init__.py",
            "core/async_boundary.py",
            "core/api_payloads.py",
            "core/api_responses.py",
            "core/contracts/__init__.py",
            "core/contracts/workflow_design.py",
            "core/problem_responses.py",
            "core/problem_status.py",
        }.issubset(names)
        or "remote_runner/workflow_design_contract.py" in names
    )
    assert "workflow_design_router" in main_text
    assert "app.include_router(workflow_design_router)" in main_text


def test_local_staged_remote_runner_artifact_contains_tool_prepare_endpoint() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )

    resolved = RemoteRunnerArtifactProvider(repo_root=repo_root).resolve(REMOTE_RUNNER_VERSION, platform="linux-64")

    assert resolved.archive_path == bundle
    with tarfile.open(bundle, "r:gz") as archive:
        names = _normalized_tar_names(archive)
        routes = _extract_normalized(archive, "remote_runner/tool_routes.py")
        service = _extract_normalized(archive, "remote_runner/tool_service.py")
        prepare_jobs = _extract_normalized(archive, "remote_runner/tool_prepare_jobs.py")
        assert routes is not None
        assert service is not None
        assert prepare_jobs is not None
        routes_text = routes.read().decode("utf-8")
        service_text = service.read().decode("utf-8")
        prepare_jobs_text = prepare_jobs.read().decode("utf-8")

    assert {
        "remote_runner/tool_preparation.py",
        "remote_runner/tool_prepare_job_storage.py",
        "remote_runner/tool_prepare_jobs.py",
        "remote_runner/tool_revisions.py",
        "remote_runner/tool_service.py",
    }.issubset(names)
    assert '@router.get("/api/v1/tools/index")' in routes_text
    assert '@router.post("/api/v1/tools/prepare-jobs", status_code=202)' in routes_text
    assert "list_tool_index_from_request" in service_text
    assert "create_tool_prepare_job_response_from_request" in service_text
    assert "run_tool_prepare_job" not in service_text
    assert "def run_tool_prepare_job" in prepare_jobs_text


def test_local_staged_workflow_runtime_artifact_wraps_activate_for_per_rule_conda_envs() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-workflow-runtime-{WORKFLOW_RUNTIME_VERSION}-linux-64.tar.gz",
    )

    resolved = WorkflowRuntimeArtifactProvider(repo_root=repo_root).resolve(WORKFLOW_RUNTIME_VERSION, platform="linux-64")

    assert resolved.archive_path == bundle
    with tarfile.open(bundle, "r:gz") as archive:
        normalized_names = _normalized_tar_names(archive)
        activate = _extract_normalized(archive, "workflow-env/bin/activate")
        assert activate is not None
        activate_text = activate.read().decode("utf-8")

    assert "workflow-env/bin/activate.conda-pack" in normalized_names
    assert 'PATH="$_h2ometa_activate_dir:$PATH" "$_h2ometa_conda" shell.posix activate "$@"' in activate_text
    assert '. "$_h2ometa_conda_pack_activate"' in activate_text
