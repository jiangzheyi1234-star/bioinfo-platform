from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.config import (
    RemoteRunnerConfig,
    ensure_runtime_layout,
    get_workflow_profile_path,
)
from core.remote_runner.manager import RemoteRunnerManager


def test_runtime_layout_writes_managed_conda_prefix(tmp_path: Path) -> None:
    release_dir = tmp_path / "release" / "remote_runner"
    wrapper_dir = release_dir / "snakemake_wrappers"
    wrapper_dir.mkdir(parents=True)
    cfg = RemoteRunnerConfig(
        token="token",
        release_dir=str(release_dir),
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
    )

    ensure_runtime_layout(cfg)

    profile_path = get_workflow_profile_path(cfg)
    assert profile_path is not None
    profile = profile_path.read_text(encoding="utf-8")
    assert "conda-frontend: mamba" in profile
    assert f"wrapper-prefix: {wrapper_dir.resolve().as_uri()}/" in profile
    assert f"conda-prefix: {tmp_path / 'shared' / 'conda-envs'}" in profile
    assert (tmp_path / "shared" / "conda-envs").is_dir()


def test_runtime_layout_refreshes_profile_missing_wrapper_prefix(tmp_path: Path) -> None:
    release_dir = tmp_path / "release" / "remote_runner"
    wrapper_dir = release_dir / "snakemake_wrappers"
    wrapper_dir.mkdir(parents=True)
    cfg = RemoteRunnerConfig(
        token="token",
        release_dir=str(release_dir),
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
    )
    profile_dir = tmp_path / "shared" / "config" / "snakemake" / "default"
    profile_dir.mkdir(parents=True)
    profile_path = profile_dir / "profile.v9+.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "executor: local",
                "software-deployment-method: conda",
                "conda-frontend: mamba",
                f"conda-prefix: {tmp_path / 'shared' / 'conda-envs'}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    ensure_runtime_layout(cfg)

    profile = profile_path.read_text(encoding="utf-8")
    assert f"wrapper-prefix: {wrapper_dir.resolve().as_uri()}/" in profile
    assert f"conda-prefix: {tmp_path / 'shared' / 'conda-envs'}" in profile


def test_remote_bootstrap_profile_uses_shared_conda_prefix() -> None:
    profile = RemoteRunnerManager._build_remote_workflow_profile_content(
        conda_prefix="/home/tester/.h2ometa/runner/shared/conda-envs",
        wrapper_prefix="file:///home/tester/.h2ometa/runner/releases/0.1.1-control-plane/remote_runner/snakemake_wrappers/",
    )

    assert "software-deployment-method: conda" in profile
    assert "conda-frontend: mamba" in profile
    assert "wrapper-prefix: file:///home/tester/.h2ometa/runner/releases/0.1.1-control-plane/remote_runner/snakemake_wrappers/" in profile
    assert "conda-prefix: /home/tester/.h2ometa/runner/shared/conda-envs" in profile


def test_runtime_layout_fails_loudly_when_release_wrapper_mirror_is_missing(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        token="token",
        release_dir=str(tmp_path / "release" / "remote_runner"),
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
    )

    with pytest.raises(RuntimeError, match="SNAKEMAKE_WRAPPER_MIRROR_MISSING"):
        ensure_runtime_layout(cfg)
