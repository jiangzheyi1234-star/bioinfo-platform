from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.remote_runner.config import (
    RemoteRunnerConfig,
    dump_public_config,
    ensure_runtime_layout,
    inspect_runtime_layout,
    load_remote_runner_config,
)
from apps.remote_runner.storage_core import get_connection
from core.remote_runner.metadata import build_remote_config_payload


def _configured_runner(tmp_path: Path, **overrides: object) -> RemoteRunnerConfig:
    shared_root = tmp_path / "shared"
    values = {
        "data_root": str(shared_root),
        "db_path": str(shared_root / "data" / "runner.db"),
        "runtime_state_path": str(shared_root / "runtime" / "runner-state.json"),
        "uploads_dir": str(shared_root / "uploads"),
        "results_dir": str(shared_root / "results"),
        "work_dir": str(shared_root / "work"),
        "logs_dir": str(shared_root / "logs"),
    }
    values.update(overrides)
    return RemoteRunnerConfig(**values)


def test_remote_runner_database_backend_defaults_to_sqlite_and_redacts_database_url() -> None:
    cfg = RemoteRunnerConfig(database_url="postgresql://user:secret@example.invalid/h2ometa")

    public = dump_public_config(cfg)

    assert public["database_backend"] == "sqlite"
    assert "database_url" not in public


def test_load_remote_runner_config_rejects_postgres_backend_without_creating_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "runner.json"
    db_path = tmp_path / "shared" / "data" / "runner.db"
    config_path.write_text(
        json.dumps({"database_backend": "postgres", "db_path": str(db_path)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED: postgres"):
        load_remote_runner_config()

    assert not db_path.exists()


def test_load_remote_runner_config_rejects_database_url_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setenv("H2OMETA_DATABASE_URL", "postgresql://user:secret@example.invalid/h2ometa")

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_URL_UNSUPPORTED"):
        load_remote_runner_config()


def test_load_remote_runner_config_rejects_remote_database_url_env_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_DATABASE_URL", "postgresql://user:secret@example.invalid/h2ometa")

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_URL_UNSUPPORTED"):
        load_remote_runner_config()


def test_load_remote_runner_config_rejects_database_url_in_runner_config_without_secret_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "runner.json"
    db_path = tmp_path / "shared" / "data" / "runner.db"
    config_path.write_text(
        json.dumps(
            {
                "database_url": "postgresql://user:very-secret-password@example.invalid/h2ometa",
                "db_path": str(db_path),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    with pytest.raises(ValueError) as exc_info:
        load_remote_runner_config()

    assert str(exc_info.value) == "REMOTE_RUNNER_DATABASE_URL_UNSUPPORTED"
    assert "very-secret-password" not in str(exc_info.value)
    assert not db_path.exists()


def test_load_remote_runner_config_rejects_secret_bearing_backend_without_secret_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "runner.json"
    db_path = tmp_path / "shared" / "data" / "runner.db"
    config_path.write_text(
        json.dumps(
            {
                "database_backend": "postgresql://user:very-secret-password@example.invalid/h2ometa",
                "db_path": str(db_path),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    with pytest.raises(ValueError) as exc_info:
        load_remote_runner_config()

    assert str(exc_info.value) == "REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED: redacted"
    assert "very-secret-password" not in str(exc_info.value)
    assert not db_path.exists()


def test_load_remote_runner_config_rejects_database_backend_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "runner.json"
    db_path = tmp_path / "shared" / "data" / "runner.db"
    config_path.write_text(json.dumps({"db_path": str(db_path)}), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setenv("H2OMETA_DATABASE_BACKEND", "postgres")

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED: postgres"):
        load_remote_runner_config()

    assert not db_path.exists()


def test_load_remote_runner_config_rejects_postgresql_backend_spelling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_DATABASE_BACKEND", "postgresql")

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED: postgresql"):
        load_remote_runner_config()


def test_load_remote_runner_config_rejects_unsupported_database_signal_even_when_env_prefers_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(json.dumps({"database_backend": "postgres"}), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_DATABASE_BACKEND", "sqlite")

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED: postgres"):
        load_remote_runner_config()


def test_load_remote_runner_config_rejects_lower_priority_unsupported_env_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "runner.json"
    config_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    monkeypatch.setenv("H2OMETA_REMOTE_RUNNER_DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("H2OMETA_DATABASE_BACKEND", "postgres")

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED: postgres"):
        load_remote_runner_config()


def test_ensure_runtime_layout_rejects_unsupported_database_backend_before_sqlite_init(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path, database_backend="postgres")

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED: postgres"):
        ensure_runtime_layout(cfg)

    assert not Path(cfg.db_path).exists()


def test_ensure_runtime_layout_rejects_database_url_before_sqlite_init(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path, database_url="postgresql://user:secret@example.invalid/h2ometa")

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_URL_UNSUPPORTED"):
        ensure_runtime_layout(cfg)

    assert not Path(cfg.db_path).exists()


def test_inspect_runtime_layout_rejects_database_url_before_sqlite_inspection(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path, database_url="postgresql://user:secret@example.invalid/h2ometa")

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_URL_UNSUPPORTED"):
        inspect_runtime_layout(cfg)

    assert not Path(cfg.db_path).exists()


def test_get_connection_rejects_unsupported_database_backend_even_when_sqlite_exists(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    ensure_runtime_layout(cfg)
    cfg.database_backend = "postgres"

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED: postgres"):
        get_connection(cfg)


def test_get_connection_rejects_database_url_even_when_sqlite_exists(tmp_path: Path) -> None:
    cfg = _configured_runner(tmp_path)
    ensure_runtime_layout(cfg)
    cfg.database_url = "postgresql://user:secret@example.invalid/h2ometa"

    with pytest.raises(ValueError, match="REMOTE_RUNNER_DATABASE_URL_UNSUPPORTED"):
        get_connection(cfg)


def test_remote_bootstrap_config_payload_declares_sqlite_backend_without_database_url() -> None:
    payload = build_remote_config_payload(
        version="test-version",
        mode="background_process",
        remote_port=43127,
        token="token",
        remote_shared="/home/tester/.h2ometa/runner/shared",
        remote_release="/home/tester/.h2ometa/runner/releases/test-version",
        remote_runtime_state="/home/tester/.h2ometa/runner/shared/runtime/runner-state.json",
        runner_python="/home/tester/.h2ometa/runner/current/runtime/bin/python",
        managed_conda_command="",
        managed_conda_root_prefix="",
        workflow_runtime_provider="",
        workflow_runtime_source="",
        workflow_runtime_version="",
        snakemake_command="",
        snakemake_version="",
        workflow_profile_dir="/home/tester/.h2ometa/runner/shared/workflow-profiles",
        workflow_profile_name="h2ometa",
    )

    assert payload["database_backend"] == "sqlite"
    assert "database_url" not in payload
