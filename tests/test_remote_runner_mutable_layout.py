from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

import apps.remote_runner.runner_protocol_startup as startup_module
from apps.remote_runner.process_lifetime_lock import (
    get_runner_process_lifetime_lock_path,
)
from apps.remote_runner.process_owner import (
    get_runner_process_owner_directory,
    get_runner_process_owner_pointer_path,
)
from apps.remote_runner.runner_protocol_startup import (
    initialize_runtime_layout_from_explicit_config,
    load_remote_runner_startup_snapshot,
)
from core.contracts.runner_protocol import RUNNER_PROTOCOL_VERSION
from core.contracts.runner_protocol_runtime import (
    CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
)
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


def _startup_fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
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
        "version": "runtime-layout-test",
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
    manifest = {
        "service": "h2ometa-remote",
        "version": "runtime-layout-test",
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
    return config_path, package_dir, config


@pytest.mark.parametrize(
    "invalid_value",
    [None, "", ".", "/", "relative/runtime/runner-state.json"],
)
def test_startup_rejects_noncanonical_runtime_state_paths_before_mutation(
    tmp_path: Path,
    invalid_value: object,
) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    runtime_dir = Path(str(config["data_root"])) / "runtime"
    config["runtime_state_path"] = invalid_value
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: runtime_state_path",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )

    assert not runtime_dir.exists()


def test_startup_rejects_the_real_filesystem_root_as_runtime_state(
    tmp_path: Path,
) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    config["runtime_state_path"] = tmp_path.anchor
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: runtime_state_path",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


@pytest.mark.parametrize(
    "basename",
    [
        "runner.lock",
        "runner-process-owner.json",
        "process-owners",
        "runner.pid",
        "arbitrary.json",
    ],
)
def test_startup_rejects_reserved_runtime_sibling_names(
    tmp_path: Path,
    basename: str,
) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    data_root = Path(str(config["data_root"]))
    config["runtime_state_path"] = str(data_root / "runtime" / basename)
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: runtime_state_path",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_startup_rejects_noncanonical_or_misplaced_runtime_state_path(
    tmp_path: Path,
) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    data_root = Path(str(config["data_root"]))
    invalid_paths = (
        f"{data_root}{os.sep}runtime{os.sep}..{os.sep}runtime{os.sep}runner-state.json",
        str(data_root / "other" / "runner-state.json"),
        str(package_dir / "runner-state.json"),
    )

    for invalid_path in invalid_paths:
        config["runtime_state_path"] = invalid_path
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(
            RuntimeError,
            match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: runtime_state_path",
        ):
            load_remote_runner_startup_snapshot(
                config_path=config_path,
                package_dir=package_dir,
            )


@pytest.mark.parametrize(
    "field",
    [
        "db_path",
        "logs_dir",
        "results_dir",
        "uploads_dir",
        "work_dir",
        "workflow_profile_dir",
    ],
)
def test_startup_rejects_mutable_path_aliases(tmp_path: Path, field: str) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    config[field] = config["runtime_state_path"]
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match=rf"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


@pytest.mark.parametrize(
    "field",
    ["runtime_state_path", "workflow_profile_name"],
)
def test_startup_requires_explicit_mutable_layout_fields(
    tmp_path: Path,
    field: str,
) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    config.pop(field)
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match=rf"REMOTE_RUNNER_MUTABLE_LAYOUT_MISSING: {field}",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


@pytest.mark.parametrize(
    "invalid_name",
    ["", ".", "..", "other.yaml", "../escaped.yaml", "nested/profile.yaml"],
)
def test_startup_rejects_non_managed_workflow_profile_names(
    tmp_path: Path,
    invalid_name: str,
) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    config["workflow_profile_name"] = invalid_name
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: workflow_profile_name",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_profile_path_escape_is_rejected_before_runtime_mutation(
    tmp_path: Path,
) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    escaped_profile = package_dir.parent / "escaped-profile.yaml"
    config["workflow_profile_name"] = str(escaped_profile)
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: workflow_profile_name",
    ):
        initialize_runtime_layout_from_explicit_config(
            config_path=config_path,
            package_dir=package_dir,
        )

    assert not escaped_profile.exists()
    assert not (config_path.parent.parent / "data").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service_name", "other-service"),
        ("mode", "foreground"),
        ("version", "../unsafe"),
    ],
)
def test_startup_rejects_invalid_explicit_identity_fields(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    config[field] = value
    if field == "version":
        manifest_path = package_dir.parent / "bootstrap_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = value
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match=rf"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_startup_rejects_relative_config_path_before_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _config_path, package_dir, _config = _startup_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(
        RuntimeError,
        match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: config_path",
    ):
        load_remote_runner_startup_snapshot(
            config_path=Path("shared/config/runner.json"),
            package_dir=package_dir,
        )


def test_startup_requires_the_exact_config_suffix(tmp_path: Path) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    misplaced = config_path.parent.parent / "not-config" / "not-runner.json"
    misplaced.parent.mkdir()
    misplaced.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: config_path",
    ):
        load_remote_runner_startup_snapshot(
            config_path=misplaced,
            package_dir=package_dir,
        )


@pytest.mark.parametrize("field", ["release_dir", "runner_python"])
def test_startup_rejects_noncanonical_immutable_paths(
    tmp_path: Path,
    field: str,
) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    if field == "release_dir":
        config[field] = str(package_dir.parent / "alias" / ".." / package_dir.name)
    else:
        expected_python = package_dir.parent / "runtime" / "bin" / "python"
        config[field] = str(
            expected_python.parent / "alias" / ".." / expected_python.name
        )
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(
        RuntimeError,
        match=rf"REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: {field}",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_startup_accepts_contained_bundled_python_symlink(tmp_path: Path) -> None:
    config_path, package_dir, _config = _startup_fixture(tmp_path)
    entrypoint = package_dir.parent / "runtime" / "bin" / "python"
    target = entrypoint.with_name("python3.12")
    entrypoint.replace(target)
    try:
        entrypoint.symlink_to(target.name)
    except OSError as exc:
        target.replace(entrypoint)
        pytest.skip(f"file symlink unavailable: {exc}")

    _cfg, binding = load_remote_runner_startup_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )

    assert entrypoint.is_symlink()
    assert binding["runnerPythonPath"] == str(entrypoint)


def test_startup_rejects_bundled_python_symlink_outside_runtime(
    tmp_path: Path,
) -> None:
    config_path, package_dir, _config = _startup_fixture(tmp_path)
    entrypoint = package_dir.parent / "runtime" / "bin" / "python"
    outside_target = tmp_path / "outside-python"
    outside_target.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    outside_target.chmod(0o755)
    entrypoint.unlink()
    try:
        entrypoint.symlink_to(outside_target)
    except OSError as exc:
        pytest.skip(f"file symlink unavailable: {exc}")

    with pytest.raises(RuntimeError, match="REMOTE_RUNNER_PYTHON_INVALID"):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX executable mode required")
def test_startup_rejects_non_executable_bundled_python(tmp_path: Path) -> None:
    config_path, package_dir, _config = _startup_fixture(tmp_path)
    entrypoint = package_dir.parent / "runtime" / "bin" / "python"
    entrypoint.chmod(0o644)

    with pytest.raises(RuntimeError, match="REMOTE_RUNNER_PYTHON_INVALID"):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_startup_rejects_mutable_subdirectory_symlink_into_release(
    tmp_path: Path,
) -> None:
    config_path, package_dir, _config = _startup_fixture(tmp_path)
    target = package_dir.parent / "mutable-logs"
    target.mkdir()
    logs_path = config_path.parent.parent / "logs"
    try:
        logs_path.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    with pytest.raises(
        RuntimeError,
        match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: logs_dir_alias",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_startup_rejects_shared_tree_symlink_into_release(tmp_path: Path) -> None:
    config_path, package_dir, config = _startup_fixture(tmp_path)
    shared = config_path.parent.parent
    physical_shared = package_dir.parent / "mutable-shared"
    shutil.rmtree(shared)
    (physical_shared / "config").mkdir(parents=True)
    physical_config = physical_shared / "config" / "runner.json"
    physical_config.write_text(json.dumps(config), encoding="utf-8")
    try:
        shared.symlink_to(physical_shared, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    with pytest.raises(
        RuntimeError,
        match="REMOTE_RUNNER_MUTABLE_LAYOUT_INVALID: release_shared_overlap",
    ):
        load_remote_runner_startup_snapshot(
            config_path=config_path,
            package_dir=package_dir,
        )


def test_exact_layout_keeps_state_lock_and_owner_paths_pairwise_distinct(
    tmp_path: Path,
) -> None:
    config_path, package_dir, _config = _startup_fixture(tmp_path)
    cfg, _binding = load_remote_runner_startup_snapshot(
        config_path=config_path,
        package_dir=package_dir,
    )
    paths = {
        Path(cfg.runtime_state_path),
        get_runner_process_lifetime_lock_path(cfg),
        get_runner_process_owner_pointer_path(cfg),
        get_runner_process_owner_directory(cfg),
    }

    assert len(paths) == 4
    assert {path.parent for path in paths} == {Path(cfg.runtime_state_path).parent}
