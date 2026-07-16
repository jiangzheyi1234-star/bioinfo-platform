from __future__ import annotations

from pathlib import Path

import pytest

from core.remote_runner.artifact import RemoteRunnerArtifactError, RemoteRunnerArtifactProvider
from tests.test_remote_runner_artifact import _write_artifact


def test_artifact_provider_rejects_missing_runner_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "runner.tar.gz"
    _write_artifact(bundle, version="dev", include_runner_protocol=False)
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))

    with pytest.raises(RemoteRunnerArtifactError, match="descriptor must be an object"):
        RemoteRunnerArtifactProvider(search_roots=[]).resolve(
            "dev",
            platform="linux-64",
        )


def test_artifact_provider_rejects_wrong_runner_protocol_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "runner.tar.gz"
    _write_artifact(
        bundle,
        version="dev",
        runner_protocol_fingerprint="sha256:" + "0" * 64,
    )
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))

    with pytest.raises(RemoteRunnerArtifactError, match="fingerprint is invalid"):
        RemoteRunnerArtifactProvider(search_roots=[]).resolve(
            "dev",
            platform="linux-64",
        )
