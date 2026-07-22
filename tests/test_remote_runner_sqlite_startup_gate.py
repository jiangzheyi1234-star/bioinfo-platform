from __future__ import annotations

from pathlib import Path

import pytest

import apps.remote_runner.runner_protocol_startup as startup_module
from apps.remote_runner.runner_protocol_startup import (
    load_remote_runner_startup_snapshot,
    require_runner_protocol_startup_preflight,
)
from tests.test_remote_runner_protocol_startup import _startup_fixture


def test_startup_snapshot_rejects_unsafe_loaded_sqlite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    monkeypatch.setattr(
        startup_module,
        "require_remote_runner_sqlite_runtime",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("REMOTE_RUNNER_SQLITE_RUNTIME_UNSAFE")
        ),
    )

    with pytest.raises(RuntimeError, match="REMOTE_RUNNER_SQLITE_RUNTIME_UNSAFE"):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_startup_preflight_rejects_missing_config_without_writes(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "shared" / "config" / "runner.json"

    with pytest.raises(RuntimeError, match="REMOTE_RUNNER_CONFIG_MISSING"):
        require_runner_protocol_startup_preflight(
            config_path=missing,
            package_dir=tmp_path / "release" / "remote_runner",
        )

    assert not (tmp_path / "shared").exists()
    assert not (tmp_path / "release").exists()
