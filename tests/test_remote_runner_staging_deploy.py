from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core.contracts.runner_protocol import RUNNER_PROTOCOL_VERSION
from core.remote_runner.bundle import RemoteRunnerBundleBuilder
from scripts.deploy_remote_runner_staging_artifact import validate_staging_artifact
from tests.helpers.remote_runner_control_plane import _fake_runtime_dir
from tests.test_remote_runner_artifact import _write_artifact


def test_staging_artifact_validation_reports_exact_runner_protocol(tmp_path: Path) -> None:
    bundle = RemoteRunnerBundleBuilder().build(
        version="staging-protocol",
        platform="linux-64",
        runtime_dir=_fake_runtime_dir(tmp_path),
    )
    digest = hashlib.sha256(bundle.archive_path.read_bytes()).hexdigest()
    Path(str(bundle.archive_path) + ".sha256").write_text(
        f"{digest}  {bundle.archive_path.name}\n",
        encoding="utf-8",
    )

    metadata = validate_staging_artifact(bundle.archive_path)

    assert metadata["runnerProtocolVersion"] == RUNNER_PROTOCOL_VERSION
    assert metadata["runnerProtocolFingerprint"].startswith("sha256:")


def test_staging_artifact_validation_rejects_missing_runner_protocol(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "runner.tar.gz"
    _write_artifact(
        artifact,
        version="staging-protocol",
        include_runner_protocol=False,
    )

    with pytest.raises(RuntimeError, match="descriptor must be an object"):
        validate_staging_artifact(artifact)


def test_staging_artifact_validation_rejects_wrong_protocol_fingerprint(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "runner.tar.gz"
    _write_artifact(
        artifact,
        version="staging-protocol",
        runner_protocol_fingerprint="sha256:" + "0" * 64,
    )

    with pytest.raises(RuntimeError, match="fingerprint is invalid"):
        validate_staging_artifact(artifact)
