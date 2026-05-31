from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import (
    RemoteRunnerConfig,
    ensure_runtime_layout,
    get_workflow_profile_path,
)
from core.remote_runner.manager import RemoteRunnerManager


def test_runtime_layout_writes_managed_conda_prefix(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        token="token",
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
    assert f"conda-prefix: {tmp_path / 'shared' / 'conda-envs'}" in profile
    assert (tmp_path / "shared" / "conda-envs").is_dir()


def test_remote_bootstrap_profile_uses_shared_conda_prefix() -> None:
    profile = RemoteRunnerManager._build_remote_workflow_profile_content(
        conda_prefix="/home/tester/.h2ometa/runner/shared/conda-envs"
    )

    assert "software-deployment-method: conda" in profile
    assert "conda-frontend: mamba" in profile
    assert "conda-prefix: /home/tester/.h2ometa/runner/shared/conda-envs" in profile
