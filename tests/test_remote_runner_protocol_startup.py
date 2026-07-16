from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest

from apps.remote_runner.config import (
    RemoteRunnerConfig,
    bind_remote_runner_config_snapshot,
    ensure_runtime_layout,
    load_remote_runner_config,
    require_explicit_loaded_runner_protocol,
)
from apps.remote_runner.errors import RemoteRunnerAuthError
from apps.remote_runner.route_utils import authorized_config
from apps.remote_runner.runner_protocol_startup import (
    initialize_runtime_layout_from_explicit_config,
    load_remote_runner_config_from_startup_preflight,
    require_runner_protocol_startup_preflight,
)
from apps.remote_runner.sqlite_migrations import CURRENT_SCHEMA_VERSION
from core.contracts.runner_protocol import RUNNER_PROTOCOL_VERSION
from core.contracts.runner_protocol_runtime import CURRENT_RUNNER_PROTOCOL_FINGERPRINT
from core.remote_runner.protocol_manifest import build_runner_protocol_manifest_fields


def _startup_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    release = tmp_path / "release"
    package_dir = release / "remote_runner"
    package_dir.mkdir(parents=True)
    config_path = tmp_path / "shared" / "config" / "runner.json"
    config_path.parent.mkdir(parents=True)
    config: dict[str, object] = {
        "version": "runtime-protocol-test",
        "release_dir": str(package_dir),
        "runner_python": str(release / "runtime" / "bin" / "python"),
        "runner_protocol_version": RUNNER_PROTOCOL_VERSION,
        "runner_protocol_fingerprint": CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
    }
    manifest: dict[str, object] = {
        "service": "h2ometa-remote",
        "version": "runtime-protocol-test",
        "platform": "linux-64",
        "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
        **build_runner_protocol_manifest_fields(),
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (release / "bootstrap_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return config_path, package_dir, config, manifest


def test_startup_preflight_binds_config_package_and_manifest(tmp_path: Path) -> None:
    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)

    result = require_runner_protocol_startup_preflight(
        config_path=config_path,
        package_dir=package_dir,
    )

    assert result["configPath"] == str(config_path.resolve())
    assert result["packagePath"] == str(package_dir.resolve())
    assert result["manifestPath"] == str((package_dir.parent / "bootstrap_manifest.json").resolve())
    assert result["protocolFingerprint"] == CURRENT_RUNNER_PROTOCOL_FINGERPRINT


def test_startup_preflight_rejects_missing_config_without_writes(tmp_path: Path) -> None:
    missing = tmp_path / "shared" / "config" / "runner.json"

    with pytest.raises(RuntimeError, match="REMOTE_RUNNER_CONFIG_MISSING"):
        require_runner_protocol_startup_preflight(
            config_path=missing,
            package_dir=tmp_path / "release" / "remote_runner",
        )

    assert not (tmp_path / "shared").exists()
    assert not (tmp_path / "release").exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("runner_protocol_version", None, "EXPECTATION_MISSING"),
        ("runner_protocol_version", "runner-protocol.v0", "EXPECTATION_MISMATCH"),
        ("runner_protocol_fingerprint", None, "EXPECTATION_MISSING"),
        ("runner_protocol_fingerprint", "sha256:" + "0" * 64, "EXPECTATION_MISMATCH"),
    ],
)
def test_startup_preflight_rejects_missing_or_wrong_config_expectation(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    config_path, package_dir, config, _manifest = _startup_fixture(tmp_path)
    if value is None:
        config.pop(field)
    else:
        config[field] = value
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_startup_preflight_rejects_release_path_mismatch(tmp_path: Path) -> None:
    config_path, package_dir, config, _manifest = _startup_fixture(tmp_path)
    config["release_dir"] = str(tmp_path / "another-release" / "remote_runner")
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(RuntimeError, match="REMOTE_RUNNER_RELEASE_DIR_MISMATCH"):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "REMOTE_RUNNER_PYTHON_MISSING"),
        ("/another/runtime/bin/python", "REMOTE_RUNNER_PYTHON_MISMATCH"),
    ],
)
def test_startup_preflight_rejects_missing_or_drifted_runner_python(
    tmp_path: Path,
    value: str | None,
    message: str,
) -> None:
    config_path, package_dir, config, _manifest = _startup_fixture(tmp_path)
    if value is None:
        config.pop("runner_python")
    else:
        config["runner_python"] = value
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_startup_loader_builds_config_from_the_validated_single_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    original_read_text = Path.read_text
    config_reads = 0

    def tracked_read_text(path: Path, *args, **kwargs) -> str:
        nonlocal config_reads
        if path == config_path:
            config_reads += 1
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read_text)

    cfg = load_remote_runner_config_from_startup_preflight(
        config_path=config_path,
        package_dir=package_dir,
    )

    assert config_reads == 1
    assert cfg.release_dir == str(package_dir)
    assert cfg.runner_protocol_version == RUNNER_PROTOCOL_VERSION


def test_preflighted_config_snapshot_remains_process_bound_after_disk_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path, package_dir, config, _manifest = _startup_fixture(tmp_path)
    config.update(
        {
            "token": "startup-token",
            "data_root": str(tmp_path / "startup-data"),
            "db_path": str(tmp_path / "startup-data" / "runner.db"),
        }
    )
    config_path.write_text(json.dumps(config), encoding="utf-8")
    cfg = load_remote_runner_config_from_startup_preflight(
        config_path=config_path,
        package_dir=package_dir,
    )
    monkeypatch.setattr(
        "apps.remote_runner.config_snapshot._PROCESS_BOUND_REMOTE_RUNNER_CONFIG",
        None,
    )
    bind_remote_runner_config_snapshot(cfg)

    drifted = {
        **config,
        "token": "drifted-token",
        "data_root": str(tmp_path / "drifted-data"),
        "release_dir": str(tmp_path / "drifted-release" / "remote_runner"),
        "runner_python": str(tmp_path / "drifted-release" / "runtime" / "bin" / "python"),
    }
    config_path.write_text(json.dumps(drifted), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    bound = authorized_config("Bearer startup-token")

    assert bound.release_dir == str(package_dir)
    assert bound.data_root == str(tmp_path / "startup-data")
    with pytest.raises(RemoteRunnerAuthError, match="authentication failed"):
        authorized_config("Bearer drifted-token")


def test_explicit_startup_initialization_uses_one_snapshot_and_migrates_layout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path, package_dir, config, _manifest = _startup_fixture(tmp_path)
    (package_dir / "snakemake_wrappers").mkdir()
    data_root = tmp_path / "runtime-data"
    config.update(
        {
            "data_root": str(data_root),
            "db_path": str(data_root / "data" / "runner.db"),
            "runtime_state_path": str(data_root / "runtime" / "runner-state.json"),
            "uploads_dir": str(data_root / "uploads"),
            "results_dir": str(data_root / "results"),
            "work_dir": str(data_root / "work"),
            "logs_dir": str(data_root / "logs"),
        }
    )
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    original_read_text = Path.read_text
    config_reads = 0

    def tracked_read_text(path: Path, *args, **kwargs) -> str:
        nonlocal config_reads
        if path == config_path:
            config_reads += 1
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read_text)

    initialize_runtime_layout_from_explicit_config(
        config_path=config_path,
        package_dir=package_dir,
    )

    assert config_reads == 1
    assert (data_root / "uploads").is_dir()
    db_path = data_root / "data" / "runner.db"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_explicit_startup_initialization_rejects_manifest_drift_before_layout_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path, package_dir, config, manifest = _startup_fixture(tmp_path)
    data_root = tmp_path / "runtime-data"
    config.update(
        {
            "data_root": str(data_root),
            "db_path": str(data_root / "data" / "runner.db"),
        }
    )
    config_path.write_text(json.dumps(config), encoding="utf-8")
    manifest["service"] = "unexpected-runner"
    (package_dir.parent / "bootstrap_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    with pytest.raises(RuntimeError, match="SERVICE_MISMATCH"):
        initialize_runtime_layout_from_explicit_config(
            config_path=config_path,
            package_dir=package_dir,
        )

    assert not data_root.exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest.__setitem__("service", "wrong"), "SERVICE_MISMATCH"),
        (lambda manifest: manifest.__setitem__("version", "wrong"), "VERSION_MISMATCH"),
        (lambda manifest: manifest.pop("runnerProtocol"), "descriptor must be an object"),
        (
            lambda manifest: manifest.__setitem__("runnerProtocolFingerprint", "sha256:" + "0" * 64),
            "PROTOCOL_FINGERPRINT_INVALID",
        ),
    ],
)
def test_startup_preflight_rejects_drifted_manifest(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    config_path, package_dir, _config, manifest = _startup_fixture(tmp_path)
    drifted = deepcopy(manifest)
    mutation(drifted)
    (package_dir.parent / "bootstrap_manifest.json").write_text(
        json.dumps(drifted),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match=message):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_explicit_config_missing_protocol_fails_before_layout_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "shared" / "config" / "runner.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"data_root": str(tmp_path / "runtime-data")}),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    cfg = load_remote_runner_config()
    with pytest.raises(RuntimeError, match="EXPECTATION_MISSING"):
        require_explicit_loaded_runner_protocol(cfg)

    assert not (tmp_path / "runtime-data").exists()


def test_layout_rejects_wrong_expectation_before_creating_directories(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    cfg = RemoteRunnerConfig(
        runner_protocol_fingerprint="sha256:" + "0" * 64,
        data_root=str(shared),
        db_path=str(shared / "data" / "runner.db"),
        runtime_state_path=str(shared / "runtime" / "runner-state.json"),
        uploads_dir=str(shared / "uploads"),
        results_dir=str(shared / "results"),
        work_dir=str(shared / "work"),
        logs_dir=str(shared / "logs"),
    )

    with pytest.raises(ValueError, match="EXPECTATION_MISMATCH"):
        ensure_runtime_layout(cfg)

    assert not shared.exists()


def test_entrypoints_run_read_only_preflight_before_runtime_imports() -> None:
    root = Path(__file__).resolve().parents[1]
    run_source = (root / "apps" / "remote_runner" / "run.py").read_text(encoding="utf-8")
    activation_source = (
        root / "core" / "remote_runner" / "bootstrap_protocol_activation.py"
    ).read_text(encoding="utf-8")

    assert run_source.index("load_remote_runner_config_from_startup_preflight()") < run_source.index(
        "from .config import ("
    )
    assert run_source.index("load_remote_runner_config_from_startup_preflight()") < run_source.index(
        "from .main import app"
    )
    assert "load_remote_runner_config()" not in run_source
    assert "initialize_runtime_layout_from_explicit_config" in activation_source
    assert "{python} -B -c" in activation_source
