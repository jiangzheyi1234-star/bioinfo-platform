from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner.agent_control_plane_schema_readiness import (
    AGENT_RUN_AUTHORIZATION_SCHEMA_SIGNATURE_MISMATCH,
    AGENT_SESSION_SCHEMA_SIGNATURE_MISMATCH,
    assert_agent_control_plane_schema,
    assert_agent_run_authorization_schema,
    assert_agent_session_schema,
)
from apps.remote_runner.agent_schema_extensions import (
    AGENT_SCHEMA_TRIGGER_NAMESPACE_MISMATCH,
)
from apps.remote_runner.sqlite_migrations import initialize_or_migrate_runtime_db
from tests.agent_process_instance_schema_fixtures import downgrade_process_schema
from tests.helpers.reference_database import make_remote_runner_config


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    return Path(cfg.db_path)


def test_fresh_control_plane_has_exact_v18_v19_schema(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        assert_agent_session_schema(connection)
        assert_agent_run_authorization_schema(connection)
        assert_agent_control_plane_schema(connection)


@pytest.mark.parametrize(
    ("trigger_name", "operation"),
    [
        ("agent_events_no_update", "UPDATE"),
        ("agent_events_no_delete", "DELETE"),
        ("agent_plan_revisions_no_update", "UPDATE"),
    ],
)
def test_session_readiness_rejects_noop_immutable_trigger(
    database_path: Path,
    trigger_name: str,
    operation: str,
) -> None:
    table_name = "agent_events" if trigger_name.startswith("agent_events") else "agent_plan_revisions"
    with sqlite3.connect(database_path) as connection:
        connection.execute(f'DROP TRIGGER "{trigger_name}"')
        connection.execute(
            f'CREATE TRIGGER "{trigger_name}" BEFORE {operation} ON "{table_name}" '
            "BEGIN SELECT 1; END"
        )
        with pytest.raises(
            RuntimeError,
            match=(
                rf"^{AGENT_SESSION_SCHEMA_SIGNATURE_MISMATCH}: "
                rf"object-sql:{trigger_name}$"
            ),
        ):
            assert_agent_session_schema(connection)


@pytest.mark.parametrize(
    ("trigger_name", "table_name", "operation"),
    [
        ("agent_run_authorizations_no_update", "agent_run_authorizations", "UPDATE"),
        (
            "agent_session_effect_budgets_no_update",
            "agent_session_effect_budgets",
            "UPDATE",
        ),
        ("agent_bound_runs_no_delete", "runs", "DELETE"),
    ],
)
def test_authorization_readiness_rejects_noop_guard_trigger(
    database_path: Path,
    trigger_name: str,
    table_name: str,
    operation: str,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(f'DROP TRIGGER "{trigger_name}"')
        connection.execute(
            f'CREATE TRIGGER "{trigger_name}" BEFORE {operation} ON "{table_name}" '
            "BEGIN SELECT 1; END"
        )
        with pytest.raises(
            RuntimeError,
            match=(
                rf"^{AGENT_RUN_AUTHORIZATION_SCHEMA_SIGNATURE_MISMATCH}: "
                rf"object-sql:{trigger_name}$"
            ),
        ):
            assert_agent_run_authorization_schema(connection)


def test_current_startup_rejects_same_name_weak_authorization_trigger(
    database_path: Path,
) -> None:
    trigger_name = "agent_run_authorizations_no_update"
    with sqlite3.connect(database_path) as connection:
        connection.execute(f'DROP TRIGGER "{trigger_name}"')
        connection.execute(
            f'CREATE TRIGGER "{trigger_name}" BEFORE UPDATE '
            'ON "agent_run_authorizations" BEGIN SELECT 1; END'
        )

    with pytest.raises(
        RuntimeError,
        match=(
            rf"^{AGENT_RUN_AUTHORIZATION_SCHEMA_SIGNATURE_MISMATCH}: "
            rf"object-sql:{trigger_name}$"
        ),
    ):
        initialize_or_migrate_runtime_db(database_path)


def test_control_plane_readiness_rejects_extra_trigger_on_managed_table(
    database_path: Path,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TRIGGER forged_authorization_side_effect "
            "AFTER INSERT ON agent_run_authorizations BEGIN SELECT 1; END"
        )
        with pytest.raises(
            RuntimeError,
            match=(
                rf"^{AGENT_RUN_AUTHORIZATION_SCHEMA_SIGNATURE_MISMATCH}: "
                r"triggers:agent_run_authorizations$"
            ),
        ):
            assert_agent_run_authorization_schema(connection)


def test_current_startup_rejects_extra_trigger_outside_agent_tables(
    database_path: Path,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TRIGGER forged_runtime_side_effect "
            "AFTER INSERT ON uploads BEGIN SELECT 1; END"
        )

    with pytest.raises(
        RuntimeError,
        match=rf"^{AGENT_SCHEMA_TRIGGER_NAMESPACE_MISMATCH}: runtime-triggers$",
    ):
        initialize_or_migrate_runtime_db(database_path)


def test_v20_upgrade_rejects_weak_authority_before_process_schema_commit(
    database_path: Path,
) -> None:
    downgrade_process_schema(database_path)
    trigger_name = "agent_run_authorizations_no_update"
    with sqlite3.connect(database_path) as connection:
        connection.execute(f'DROP TRIGGER "{trigger_name}"')
        connection.execute(
            f'CREATE TRIGGER "{trigger_name}" BEFORE UPDATE '
            'ON "agent_run_authorizations" BEGIN SELECT 1; END'
        )

    with pytest.raises(
        RuntimeError,
        match=rf"^{AGENT_RUN_AUTHORIZATION_SCHEMA_SIGNATURE_MISMATCH}:",
    ):
        initialize_or_migrate_runtime_db(database_path)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 20
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version IN (21, 22)"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'agent_process_instances'"
        ).fetchone() is None


def test_session_readiness_rejects_same_name_wrong_index(database_path: Path) -> None:
    index_name = "idx_agent_events_hash_chain"
    with sqlite3.connect(database_path) as connection:
        connection.execute(f'DROP INDEX "{index_name}"')
        connection.execute(
            f'CREATE INDEX "{index_name}" ON agent_events(session_id, event_hash, seq)'
        )
        with pytest.raises(
            RuntimeError,
            match=(
                rf"^{AGENT_SESSION_SCHEMA_SIGNATURE_MISMATCH}: "
                rf"object-sql:{index_name}$"
            ),
        ):
            assert_agent_session_schema(connection)


def test_readiness_errors_never_expose_database_path(database_path: Path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TRIGGER agent_events_no_update")
        with pytest.raises(RuntimeError) as captured:
            assert_agent_session_schema(connection)
    assert str(database_path) not in str(captured.value)
    assert str(captured.value) == (
        f"{AGENT_SESSION_SCHEMA_SIGNATURE_MISMATCH}: "
        "missing-or-wrong-type:agent_events_no_update"
    )
