from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from core.remote_runner.artifact import (
    RemoteRunnerArtifactError,
    RemoteRunnerArtifactProvider,
    WorkflowRuntimeArtifactProvider,
)
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.release_manifest import ReleaseArtifactSpec, WORKFLOW_RUNTIME_VERSION


def _write_artifact(
    path: Path,
    *,
    version: str = "0.1.0-control-plane",
    platform: str = "linux-64",
    content: bytes = b"artifact",
    include_wrapper_assets: bool = True,
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


def _local_release_artifact_or_skip(repo_root: Path, filename: str) -> Path:
    bundle = repo_root / "resources" / "remote-runner" / filename
    if not bundle.exists():
        pytest.skip(
            "release artifact tarballs are external; run scripts/check_remote_runner_release_artifacts.py "
            "with release download credentials to verify artifact contents"
        )
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


def test_workflow_runtime_provider_resolves_conda_pack_artifact(tmp_path: Path) -> None:
    bundle = tmp_path / "h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz"
    _write_workflow_artifact(bundle)

    resolved = WorkflowRuntimeArtifactProvider(search_roots=[tmp_path]).resolve("0.1.0", platform="linux-64")

    assert resolved.archive_path == bundle
    assert resolved.snakemake_entrypoint == "workflow-env/bin/snakemake"
    assert resolved.conda_unpack_entrypoint == "workflow-env/bin/conda-unpack"


def test_workflow_runtime_provider_rejects_wrong_service(tmp_path: Path) -> None:
    bundle = tmp_path / "h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz"
    _write_workflow_artifact(bundle, service="h2ometa-remote")

    with pytest.raises(RemoteRunnerArtifactError, match="unexpected service"):
        WorkflowRuntimeArtifactProvider(search_roots=[tmp_path]).resolve("0.1.0", platform="linux-64")


def test_workflow_runtime_provider_rejects_artifact_missing_snakemake_package(tmp_path: Path) -> None:
    bundle = tmp_path / "h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz"
    _write_workflow_artifact(bundle, include_snakemake_package=False)

    with pytest.raises(RemoteRunnerArtifactError, match="missing snakemake Python package"):
        WorkflowRuntimeArtifactProvider(search_roots=[tmp_path]).resolve("0.1.0", platform="linux-64")


def test_workflow_runtime_provider_rejects_missing_snakemake_package_version(tmp_path: Path) -> None:
    bundle = tmp_path / "h2ometa-workflow-runtime-0.1.0-linux-64.tar.gz"
    _write_workflow_artifact(bundle, snakemake_package="")

    with pytest.raises(RemoteRunnerArtifactError, match="must declare snakemake package version"):
        WorkflowRuntimeArtifactProvider(search_roots=[tmp_path]).resolve("0.1.0", platform="linux-64")


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


def test_checked_in_remote_runner_artifact_contains_current_runtime_contract() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )

    resolved = RemoteRunnerArtifactProvider(repo_root=repo_root).resolve(REMOTE_RUNNER_VERSION, platform="linux-64")

    assert resolved.archive_path == bundle
    with tarfile.open(bundle, "r:gz") as archive:
        config = _extract_normalized(archive, "remote_runner/config.py")
        main = _extract_normalized(archive, "remote_runner/main.py")
        executor = _extract_normalized(archive, "remote_runner/executor.py")
        assert config is not None
        assert main is not None
        assert executor is not None
        config_text = config.read().decode("utf-8")
        main_text = main.read().decode("utf-8")
        executor_text = executor.read().decode("utf-8")

    assert "workflow_runtime_version" in config_text
    assert "def inspect_workflow_runtime" in config_text
    assert 'checks["workflow_runtime"]' in main_text
    assert "build_workflow_runtime_environment" in executor_text


def test_checked_in_remote_runner_artifact_contains_workflow_design_contract() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )

    resolved = RemoteRunnerArtifactProvider(repo_root=repo_root).resolve(REMOTE_RUNNER_VERSION, platform="linux-64")

    assert resolved.archive_path == bundle
    required_members = {
        "remote_runner/workflow_design_compiler.py",
        "remote_runner/workflow_design_contract.py",
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
    assert "workflow_design_router" in main_text
    assert "app.include_router(workflow_design_router)" in main_text


def test_checked_in_remote_runner_artifact_contains_tool_prepare_endpoint() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )

    resolved = RemoteRunnerArtifactProvider(repo_root=repo_root).resolve(REMOTE_RUNNER_VERSION, platform="linux-64")

    assert resolved.archive_path == bundle
    with tarfile.open(bundle, "r:gz") as archive:
        names = _normalized_tar_names(archive)
        routes = _extract_normalized(archive, "remote_runner/tool_routes.py")
        assert routes is not None
        routes_text = routes.read().decode("utf-8")

    assert {
        "remote_runner/tool_preparation.py",
        "remote_runner/tool_prepare_job_storage.py",
        "remote_runner/tool_prepare_jobs.py",
        "remote_runner/tool_revisions.py",
    }.issubset(names)
    assert '@router.post("/api/v1/tools/prepare-jobs", status_code=202)' in routes_text
    assert "run_tool_prepare_job" in routes_text


def test_checked_in_workflow_runtime_artifact_wraps_activate_for_per_rule_conda_envs() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_release_artifact_or_skip(
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
