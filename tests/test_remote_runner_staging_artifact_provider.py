from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from core.remote_runner.artifact import RemoteRunnerArtifactError, RemoteRunnerArtifactProvider
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.release_manifest import REMOTE_RUNNER_ARTIFACT


def _write_minimal_runner_artifact(path: Path, *, version: str = REMOTE_RUNNER_VERSION) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "service": "h2ometa-remote",
        "version": version,
        "platform": "linux-64",
        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
    }
    with tarfile.open(path, "w:gz") as archive:
        manifest_payload = json.dumps(manifest).encode("utf-8")
        manifest_info = tarfile.TarInfo("bootstrap_manifest.json")
        manifest_info.size = len(manifest_payload)
        archive.addfile(manifest_info, io.BytesIO(manifest_payload))
        for name in ("runtime/bin/python", "runtime/bin/conda-unpack"):
            payload = b"#!/usr/bin/env python\n"
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        for name in RemoteRunnerArtifactProvider.REQUIRED_WRAPPER_ASSET_MEMBERS:
            payload = b"placeholder\n"
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")


def test_staged_declared_runner_bundle_requires_explicit_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    bundle = root / "resources" / "remote-runner" / REMOTE_RUNNER_ARTIFACT.archive_filename("linux-64")
    _write_minimal_runner_artifact(bundle)
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))
    monkeypatch.delenv("H2OMETA_ALLOW_STAGING_REMOTE_RUNNER_BUNDLE", raising=False)

    with pytest.raises(RemoteRunnerArtifactError, match="manifest sha256 mismatch"):
        RemoteRunnerArtifactProvider(repo_root=root).resolve(REMOTE_RUNNER_VERSION, platform="linux-64")

    monkeypatch.setenv("H2OMETA_ALLOW_STAGING_REMOTE_RUNNER_BUNDLE", "1")
    resolved = RemoteRunnerArtifactProvider(repo_root=root).resolve(REMOTE_RUNNER_VERSION, platform="linux-64")

    assert resolved.archive_path == bundle


def test_explicit_staged_runner_bundle_allows_unpromoted_manifest_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    bundle = root / "dist" / "remote-runner" / "h2ometa-remote-runner-0.1.4-control-plane-linux-64.tar.gz"
    _write_minimal_runner_artifact(bundle, version="0.1.4-control-plane")
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))
    monkeypatch.setenv("H2OMETA_ALLOW_STAGING_REMOTE_RUNNER_BUNDLE", "1")

    resolved = RemoteRunnerArtifactProvider(repo_root=root).resolve(REMOTE_RUNNER_VERSION, platform="linux-64")

    assert resolved.archive_path == bundle
    assert resolved.version == "0.1.4-control-plane"
