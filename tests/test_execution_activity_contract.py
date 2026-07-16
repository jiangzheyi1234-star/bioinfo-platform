from __future__ import annotations

from pathlib import Path

from core.contracts.execution_activity import (
    EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
    EXECUTION_LIFECYCLE_MAINTENANCE_KEY,
    EXECUTION_LIFECYCLE_MAINTENANCE_SCHEMA_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONSUMER_PATHS = (
    "apps/remote_runner/execution_lifecycle_guard.py",
    "core/app_runtime/managers/runner.py",
    "core/remote_runner/bootstrap_guard.py",
    "core/remote_runner/release_prune.py",
    "core/remote_runner/uninstall.py",
)
FIXTURE_PATHS = (
    "tests/test_remote_runner_bootstrap_guard.py",
    "tests/test_remote_runner_release_prune.py",
    "tests/test_remote_runner_reuse_lock_manager.py",
    "tests/test_remote_runner_stop_service.py",
    "tests/test_remote_runner_token_rotation_health.py",
    "tests/test_remote_runner_uninstall.py",
)


def test_execution_lifecycle_guard_contract_values_are_declared_once() -> None:
    assert EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION == "h2ometa.execution-lifecycle-guard.v1"
    assert EXECUTION_LIFECYCLE_MAINTENANCE_SCHEMA_VERSION == "h2ometa.execution-lifecycle-maintenance.v2"
    assert EXECUTION_LIFECYCLE_MAINTENANCE_KEY == "execution_lifecycle_maintenance"

    for relative_path in CONSUMER_PATHS:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert 'EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION = "' not in source
        assert 'EXECUTION_LIFECYCLE_MAINTENANCE_KEY = "' not in source

    for relative_path in FIXTURE_PATHS:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert "h2ometa.execution-lifecycle-guard.v1" not in source


def test_uninstall_remote_cleanup_uses_contract_schema_value() -> None:
    source = (REPO_ROOT / "core/remote_runner/uninstall.py").read_text(encoding="utf-8")

    assert "h2ometa.execution-lifecycle-guard.v1" not in source
    assert "{EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION!r}" in source
    assert "{EXECUTION_LIFECYCLE_MAINTENANCE_SCHEMA_VERSION!r}" in source
