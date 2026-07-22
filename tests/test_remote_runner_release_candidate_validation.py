from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_remote_runner_artifact_on_server import (
    validate_built_remote_runner_candidate,
)
from tests.helpers.remote_runner_artifact_checks import (
    write_remote_runner_artifact,
)


def test_release_candidate_validation_binds_manifest_and_sqlite_evidence(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "runner.tar.gz"
    write_remote_runner_artifact(
        artifact,
        version="0.1.6-sqlite-gate",
        platform="linux-64",
    )

    evidence = validate_built_remote_runner_candidate(
        artifact_path=artifact,
        version="0.1.6-sqlite-gate",
        platform="linux-64",
    )

    assert evidence["manifestSchemaVersion"].endswith("bootstrap-manifest.v2")
    assert evidence["sqlite"]["packagedVersion"] == "3.53.0"


def test_release_candidate_validation_rejects_build_request_identity_drift(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "runner.tar.gz"
    write_remote_runner_artifact(artifact, version="0.1.6-sqlite-gate")

    with pytest.raises(RuntimeError, match="identity does not match"):
        validate_built_remote_runner_candidate(
            artifact_path=artifact,
            version="0.1.7-other",
            platform="linux-64",
        )
