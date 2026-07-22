from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

import apps.remote_runner.runner_protocol_startup as startup_module
from apps.remote_runner.config import (
    RemoteRunnerConfig,
    bind_remote_runner_config_snapshot,
    ensure_runtime_layout,
    load_remote_runner_config,
    require_explicit_loaded_runner_protocol,
)
from apps.remote_runner.config_snapshot import (
    bind_remote_runner_startup_binding,
    get_process_bound_remote_runner_startup_binding,
)
from apps.remote_runner.errors import RemoteRunnerAuthError
from apps.remote_runner.route_utils import authorized_config
from apps.remote_runner.runner_protocol_startup import (
    initialize_runtime_layout_from_explicit_config,
    load_remote_runner_config_from_startup_preflight,
    load_remote_runner_startup_snapshot,
    require_runner_protocol_startup_preflight,
)
from apps.remote_runner.sqlite_migrations import CURRENT_SCHEMA_VERSION
from core.contracts.runner_protocol import RUNNER_PROTOCOL_VERSION
from core.contracts.runner_protocol_runtime import CURRENT_RUNNER_PROTOCOL_FINGERPRINT
from core.remote_runner.protocol_manifest import build_runner_protocol_manifest_fields


@pytest.fixture(autouse=True)
def _supported_sqlite_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        startup_module,
        "require_remote_runner_sqlite_runtime",
        lambda **_kwargs: {
            "minimumVersion": "3.51.3",
            "loadedVersion": "3.53.0",
            "sqlVersion": "3.53.0",
            "ok": True,
        },
    )


def _startup_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    release = tmp_path / "release"
    package_dir = release / "remote_runner"
    package_dir.mkdir(parents=True)
    runner_python = release / "runtime" / "bin" / "python"
    runner_python.parent.mkdir(parents=True)
    runner_python.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    runner_python.chmod(0o755)
    config_path = tmp_path / "shared" / "config" / "runner.json"
    config_path.parent.mkdir(parents=True)
    data_root = config_path.parent.parent
    config: dict[str, object] = {
        "service_name": "h2ometa-remote",
        "version": "runtime-protocol-test",
        "mode": "background_process",
        "release_dir": str(package_dir),
        "runner_python": str(runner_python),
        "runner_protocol_version": RUNNER_PROTOCOL_VERSION,
        "runner_protocol_fingerprint": CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
        "data_root": str(data_root),
        "db_path": str(data_root / "data" / "runner.db"),
        "runtime_state_path": str(data_root / "runtime" / "runner-state.json"),
        "uploads_dir": str(data_root / "uploads"),
        "results_dir": str(data_root / "results"),
        "work_dir": str(data_root / "work"),
        "logs_dir": str(data_root / "logs"),
        "workflow_profile_dir": str(data_root / "config" / "snakemake" / "default"),
        "workflow_profile_name": "profile.v9+.yaml",
    }
    manifest: dict[str, object] = {
        "service": "h2ometa-remote",
        "version": "runtime-protocol-test",
        "platform": "linux-64",
        "runtime": {
            "provider": "bundled",
            "python": "runtime/bin/python",
            "sqlite": {"minimumVersion": "3.51.3"},
        },
        **build_runner_protocol_manifest_fields(),
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (release / "bootstrap_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (release / "artifact.sha256").write_bytes(("a" * 64 + "\n").encode("ascii"))
    return config_path, package_dir, config, manifest


def _expected_fingerprint(domain: bytes, payload: object) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(domain + b'\x00' + canonical).hexdigest()}"


def test_startup_snapshot_binds_exact_golden_evidence_and_domains(
    tmp_path: Path,
) -> None:
    config_path, package_dir, config, manifest = _startup_fixture(tmp_path)

    cfg, result = load_remote_runner_startup_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )

    assert result == {
        "configPath": str(config_path.resolve()),
        "persistedConfigFingerprint": _expected_fingerprint(
            b"h2ometa.remote-runner.startup.persisted-config.v1",
            config,
        ),
        "effectiveConfigFingerprint": _expected_fingerprint(
            b"h2ometa.remote-runner.startup.effective-config.v1",
            asdict(cfg),
        ),
        "packagePath": str(package_dir.resolve()),
        "runnerPythonPath": str(
            (package_dir.parent / "runtime" / "bin" / "python").resolve()
        ),
        "manifestPath": str((package_dir.parent / "bootstrap_manifest.json").resolve()),
        "bootstrapManifestFingerprint": _expected_fingerprint(
            b"h2ometa.remote-runner.startup.bootstrap-manifest.v2",
            manifest,
        ),
        "artifactArchiveSha256Path": str(
            (package_dir.parent / "artifact.sha256").resolve()
        ),
        "declaredArtifactArchiveSha256": "sha256:" + "a" * 64,
        "protocolVersion": RUNNER_PROTOCOL_VERSION,
        "protocolFingerprint": CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
    }
    assert (
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )
        == result
    )


@pytest.mark.parametrize("target", ["config", "manifest"])
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_startup_snapshot_rejects_duplicate_keys_and_non_finite_json(
    tmp_path: Path,
    target: str,
    constant: str,
) -> None:
    config_path, package_dir, config, manifest = _startup_fixture(tmp_path)
    path = (
        config_path
        if target == "config"
        else package_dir.parent / "bootstrap_manifest.json"
    )
    payload = config if target == "config" else manifest
    raw = json.dumps(payload)[:-1] + f',"unsafe":{constant}}}'
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(
        RuntimeError, match=f"REMOTE_RUNNER_.*{target.upper()}.*INVALID"
    ):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )

    duplicate = json.dumps(payload)[:-1] + ',"version":"duplicate"}'
    path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(
        RuntimeError, match=f"REMOTE_RUNNER_.*{target.upper()}.*INVALID"
    ):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


@pytest.mark.parametrize("target", ["config", "manifest"])
@pytest.mark.parametrize("surrogate", [r"\ud800", r"\udfff"])
def test_startup_snapshot_rejects_escaped_unicode_surrogates(
    tmp_path: Path,
    target: str,
    surrogate: str,
) -> None:
    config_path, package_dir, config, manifest = _startup_fixture(tmp_path)
    path = (
        config_path
        if target == "config"
        else package_dir.parent / "bootstrap_manifest.json"
    )
    payload = config if target == "config" else manifest
    raw = json.dumps(payload)[:-1] + f',"unsafe":"{surrogate}"}}'
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(
        RuntimeError, match=f"REMOTE_RUNNER_.*{target.upper()}.*INVALID"
    ):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


@pytest.mark.parametrize("target", ["config", "manifest"])
@pytest.mark.parametrize("invalid_kind", ["non_utf8", "oversized"])
def test_startup_snapshot_rejects_invalid_json_file_bytes(
    tmp_path: Path,
    target: str,
    invalid_kind: str,
) -> None:
    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    path = (
        config_path
        if target == "config"
        else package_dir.parent / "bootstrap_manifest.json"
    )
    if invalid_kind == "non_utf8":
        path.write_bytes(b'{"invalid":"\xff"}')
    else:
        path.write_bytes(b'{"padding":"' + b"x" * (1024 * 1024) + b'"}')

    with pytest.raises(
        RuntimeError, match=f"REMOTE_RUNNER_.*{target.upper()}.*INVALID"
    ):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


@pytest.mark.parametrize("target", ["config", "manifest", "artifact"])
@pytest.mark.parametrize("replacement", ["missing", "directory", "symlink"])
def test_startup_snapshot_rejects_missing_or_unsafe_evidence_files(
    tmp_path: Path,
    target: str,
    replacement: str,
) -> None:
    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    paths = {
        "config": config_path,
        "manifest": package_dir.parent / "bootstrap_manifest.json",
        "artifact": package_dir.parent / "artifact.sha256",
    }
    path = paths[target]
    if replacement == "missing":
        path.unlink()
    elif replacement == "directory":
        path.unlink()
        path.mkdir()
    else:
        target_path = path.with_name(path.name + ".target")
        path.replace(target_path)
        try:
            path.symlink_to(target_path)
        except OSError as exc:
            pytest.skip(f"file symlinks unavailable: {exc}")

    expected = {
        "config": "REMOTE_RUNNER_CONFIG_(?:MISSING|INVALID)",
        "manifest": "REMOTE_RUNNER_ARTIFACT_MANIFEST_(?:MISSING|INVALID)",
        "artifact": "REMOTE_RUNNER_ARTIFACT_ARCHIVE_SHA256_(?:MISSING|INVALID)",
    }[target]
    with pytest.raises(RuntimeError, match=expected):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


@pytest.mark.parametrize(
    "value",
    [
        "a" * 63,
        "A" * 64,
        "sha256:" + "a" * 64,
        "a" * 64 + "\r\n",
        "a" * 64 + "\n\n",
        "a" * 64 + " ",
    ],
)
def test_startup_snapshot_rejects_noncanonical_artifact_archive_sha256(
    tmp_path: Path,
    value: str,
) -> None:
    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    (package_dir.parent / "artifact.sha256").write_bytes(value.encode("ascii"))

    with pytest.raises(RuntimeError, match="ARTIFACT_ARCHIVE_SHA256_INVALID"):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_startup_snapshot_accepts_artifact_archive_sha256_without_lf(
    tmp_path: Path,
) -> None:
    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    (package_dir.parent / "artifact.sha256").write_bytes(b"b" * 64)

    result = require_runner_protocol_startup_preflight(
        config_path=config_path,
        package_dir=package_dir,
    )

    assert result["declaredArtifactArchiveSha256"] == "sha256:" + "b" * 64


def test_startup_snapshot_rejects_path_fd_inode_drift(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from apps.remote_runner import runner_protocol_startup as startup

    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    original_stat = startup._snapshot_path_stat
    config_stat_calls = 0

    def drifting_stat(path: Path):
        nonlocal config_stat_calls
        result = original_stat(path)
        if path == config_path:
            config_stat_calls += 1
            if config_stat_calls == 2:
                return SimpleNamespace(
                    st_mode=result.st_mode,
                    st_dev=result.st_dev,
                    st_ino=result.st_ino + 1,
                    st_size=result.st_size,
                    st_mtime_ns=result.st_mtime_ns,
                    st_ctime_ns=result.st_ctime_ns,
                )
        return result

    monkeypatch.setattr(startup, "_snapshot_path_stat", drifting_stat)

    with pytest.raises(RuntimeError, match="REMOTE_RUNNER_CONFIG_INVALID"):
        require_runner_protocol_startup_preflight(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_effective_env_override_changes_only_effective_config_fingerprint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    worker_slots_env = "H2OMETA_REMOTE_RUN_WORKER_SLOTS"
    monkeypatch.delenv(worker_slots_env, raising=False)
    baseline_cfg, baseline = load_remote_runner_startup_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )

    monkeypatch.setenv(worker_slots_env, "2")
    overridden_cfg, overridden = load_remote_runner_startup_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )

    assert baseline_cfg.run_worker_slot_count == 1
    assert overridden_cfg.run_worker_slot_count == 2
    assert (
        baseline["persistedConfigFingerprint"]
        == overridden["persistedConfigFingerprint"]
    )
    assert (
        baseline["effectiveConfigFingerprint"]
        != overridden["effectiveConfigFingerprint"]
    )


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
        ("mismatch", "REMOTE_RUNNER_PYTHON_MISMATCH"),
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
        config["runner_python"] = str(
            tmp_path / "another" / "runtime" / "bin" / "python"
        )
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
    from apps.remote_runner import runner_protocol_startup as startup

    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    original_snapshot_read = startup._read_regular_file_snapshot
    config_reads = 0

    def tracked_snapshot_read(path: Path, **kwargs) -> bytes:
        nonlocal config_reads
        if path == config_path:
            config_reads += 1
        return original_snapshot_read(path, **kwargs)

    monkeypatch.setattr(startup, "_read_regular_file_snapshot", tracked_snapshot_read)

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
        "runner_python": str(
            tmp_path / "drifted-release" / "runtime" / "bin" / "python"
        ),
    }
    config_path.write_text(json.dumps(drifted), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    bound = authorized_config("Bearer startup-token")

    assert bound.release_dir == str(package_dir)
    assert bound.data_root == str(tmp_path / "shared")
    with pytest.raises(RemoteRunnerAuthError, match="authentication failed"):
        authorized_config("Bearer drifted-token")


def test_preflight_release_evidence_remains_process_bound_and_detached(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path, package_dir, _config, _manifest = _startup_fixture(tmp_path)
    _cfg, binding = load_remote_runner_startup_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )
    monkeypatch.setattr(
        "apps.remote_runner.config_snapshot._PROCESS_BOUND_REMOTE_RUNNER_STARTUP_BINDING",
        None,
    )

    bind_remote_runner_startup_binding(binding)
    original = deepcopy(binding)
    binding["packagePath"] = str(tmp_path / "drifted-release")

    assert get_process_bound_remote_runner_startup_binding() == original
    bind_remote_runner_startup_binding(original)
    with pytest.raises(
        RuntimeError, match="REMOTE_RUNNER_STARTUP_BINDING_ALREADY_BOUND"
    ):
        bind_remote_runner_startup_binding(binding)

    invalid = {**original, "unexpected": "value"}
    with pytest.raises(RuntimeError, match="REMOTE_RUNNER_STARTUP_BINDING_INVALID"):
        bind_remote_runner_startup_binding(invalid)


def test_explicit_startup_initialization_uses_one_snapshot_and_migrates_layout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from apps.remote_runner import runner_protocol_startup as startup

    config_path, package_dir, config, _manifest = _startup_fixture(tmp_path)
    (package_dir / "snakemake_wrappers").mkdir()
    data_root = tmp_path / "runtime-data"
    config_path = data_root / "config" / "runner.json"
    config_path.parent.mkdir(parents=True)
    config.update(
        {
            "data_root": str(data_root),
            "db_path": str(data_root / "data" / "runner.db"),
            "runtime_state_path": str(data_root / "runtime" / "runner-state.json"),
            "uploads_dir": str(data_root / "uploads"),
            "results_dir": str(data_root / "results"),
            "work_dir": str(data_root / "work"),
            "logs_dir": str(data_root / "logs"),
            "workflow_profile_dir": str(data_root / "config" / "snakemake" / "default"),
        }
    )
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    original_snapshot_read = startup._read_regular_file_snapshot
    config_reads = 0

    def tracked_snapshot_read(path: Path, **kwargs) -> bytes:
        nonlocal config_reads
        if path == config_path:
            config_reads += 1
        return original_snapshot_read(path, **kwargs)

    monkeypatch.setattr(startup, "_read_regular_file_snapshot", tracked_snapshot_read)
    lock_events: list[str] = []

    class FakeLifetimeLock:
        def release(self) -> None:
            lock_events.append("release")

    monkeypatch.setattr(
        "apps.remote_runner.process_lifetime_lock.acquire_runner_process_lifetime_lock",
        lambda _cfg: lock_events.append("acquire") or FakeLifetimeLock(),
    )

    initialize_runtime_layout_from_explicit_config(
        config_path=config_path,
        package_dir=package_dir,
    )

    assert config_reads == 1
    assert lock_events == ["acquire", "release"]
    assert (data_root / "uploads").is_dir()
    db_path = data_root / "data" / "runner.db"
    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute("PRAGMA user_version").fetchone()[0]
            == CURRENT_SCHEMA_VERSION
        )


def test_explicit_startup_initialization_releases_lock_when_layout_fails(
    monkeypatch,
) -> None:
    from apps.remote_runner import runner_protocol_startup as startup

    cfg = SimpleNamespace(runtime_state_path="/shared/runtime/runner-state.json")
    events: list[str] = []

    class FakeLifetimeLock:
        def release(self) -> None:
            events.append("release")

    monkeypatch.setattr(
        startup,
        "load_remote_runner_config_from_startup_preflight",
        lambda **_kwargs: cfg,
    )
    monkeypatch.setattr(
        "apps.remote_runner.process_lifetime_lock.acquire_runner_process_lifetime_lock",
        lambda _cfg: events.append("acquire") or FakeLifetimeLock(),
    )
    monkeypatch.setattr(
        "apps.remote_runner.config.ensure_runtime_layout",
        lambda _cfg: (
            events.append("ensure")
            or (_ for _ in ()).throw(RuntimeError("layout failed"))
        ),
    )

    with pytest.raises(RuntimeError, match="layout failed"):
        startup.initialize_runtime_layout_from_explicit_config()

    assert events == ["acquire", "ensure", "release"]


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
        (
            lambda manifest: manifest.pop("runnerProtocol"),
            "descriptor must be an object",
        ),
        (
            lambda manifest: manifest.__setitem__(
                "runnerProtocolFingerprint", "sha256:" + "0" * 64
            ),
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


def test_layout_rejects_wrong_expectation_before_creating_directories(
    tmp_path: Path,
) -> None:
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
    run_source = (root / "apps" / "remote_runner" / "run.py").read_text(
        encoding="utf-8"
    )
    activation_source = (
        root / "core" / "remote_runner" / "bootstrap_protocol_activation.py"
    ).read_text(encoding="utf-8")

    helper_call = "cfg, startup_binding = _load_startup_snapshot_for_owner_adoption()"
    assert run_source.index(helper_call) < run_source.index(
        "lifetime_lock = adopt_runner_process_lifetime_lock(cfg)"
    )
    assert run_source.index(
        "lifetime_lock = adopt_runner_process_lifetime_lock(cfg)"
    ) < run_source.index("from .config import (")
    assert run_source.index(helper_call) < run_source.index("from .main import app")
    helper_start = run_source.index("def _load_startup_snapshot_for_owner_adoption()")
    helper_end = run_source.index("def _scrub_inherited_runner_binding_environment(")
    assert (
        "return load_remote_runner_startup_snapshot()"
        in run_source[helper_start:helper_end]
    )
    assert "load_remote_runner_config()" not in run_source
    assert "initialize_runtime_layout_from_explicit_config" in activation_source
    assert "{python} -B -c" in activation_source
