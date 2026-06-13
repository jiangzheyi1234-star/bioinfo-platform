from __future__ import annotations

import tarfile
from pathlib import Path

from core.remote_runner.artifact import WorkflowRuntimeArtifactProvider
from core.remote_runner.release_manifest import WORKFLOW_RUNTIME_VERSION
from tests.test_remote_runner_artifact import (
    _extract_normalized,
    _local_staged_release_artifact_or_skip,
    _normalized_tar_names,
)


def test_local_staged_workflow_runtime_artifact_wraps_activate_for_per_rule_conda_envs() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-workflow-runtime-{WORKFLOW_RUNTIME_VERSION}-linux-64.tar.gz",
    )

    resolved = WorkflowRuntimeArtifactProvider(repo_root=repo_root).resolve(
        WORKFLOW_RUNTIME_VERSION,
        platform="linux-64",
    )

    assert resolved.archive_path == bundle
    with tarfile.open(bundle, "r:gz") as archive:
        normalized_names = _normalized_tar_names(archive)
        activate = _extract_normalized(archive, "workflow-env/bin/activate")
        assert activate is not None
        activate_text = activate.read().decode("utf-8")

    assert "workflow-env/bin/activate.conda-pack" in normalized_names
    assert 'PATH="$_h2ometa_activate_dir:$PATH" "$_h2ometa_conda" shell.posix activate "$@"' in activate_text
    assert '. "$_h2ometa_conda_pack_activate"' in activate_text
