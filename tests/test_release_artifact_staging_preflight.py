from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.test_remote_runner_artifact import _write_artifact


def _load_module() -> Any:
    script = Path("scripts/check_remote_runner_release_artifacts.py")
    spec = importlib.util.spec_from_file_location("check_remote_runner_release_artifacts", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_staging_runner_preflight_accepts_unpromoted_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _load_module()
    bundle = tmp_path / "h2ometa-remote-runner-0.1.2-control-plane-linux-64.tar.gz"
    _write_artifact(bundle, version="0.1.2-control-plane", platform="linux-64")
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))

    resolved = checker._resolve_staging_runner_bundle()

    assert resolved.archive_path == bundle
    assert resolved.version == "0.1.2-control-plane"
    assert resolved.platform == "linux-64"


def test_staging_runner_preflight_rejects_missing_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _load_module()
    bundle = tmp_path / "h2ometa-remote-runner-missing-version-linux-64.tar.gz"
    _write_artifact(bundle, version="", platform="linux-64")
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_BUNDLE", str(bundle))

    with pytest.raises(checker.RemoteRunnerArtifactError, match="manifest missing version"):
        checker._resolve_staging_runner_bundle()
