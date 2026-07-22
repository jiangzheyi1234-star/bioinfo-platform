"""Exact readiness assertions for the V18/V19 Agent control-plane schema."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence

from .agent_run_authorization_schema import AGENT_RUN_AUTHORIZATION_SCHEMA_STATEMENTS
from .agent_schema_trigger_namespace import assert_exact_trigger_sets
from .agent_session_schema import AGENT_SESSION_SCHEMA_STATEMENTS


AGENT_SESSION_SCHEMA_SIGNATURE_MISMATCH = "AGENT_SESSION_SCHEMA_SIGNATURE_MISMATCH"
AGENT_RUN_AUTHORIZATION_SCHEMA_SIGNATURE_MISMATCH = (
    "AGENT_RUN_AUTHORIZATION_SCHEMA_SIGNATURE_MISMATCH"
)

_SESSION_OBJECTS = (
    ("table", "agent_sessions"),
    ("index", "idx_agent_sessions_status_updated"),
    ("index", "idx_agent_sessions_project_updated"),
    ("table", "agent_plan_revisions"),
    ("index", "idx_agent_plan_revisions_session_generation"),
    ("index", "idx_agent_plan_revisions_hash"),
    ("table", "agent_approvals"),
    ("index", "idx_agent_approvals_session_plan"),
    ("index", "idx_agent_approvals_effective_decision"),
    ("table", "agent_events"),
    ("index", "idx_agent_events_session_idempotency"),
    ("index", "idx_agent_events_hash_chain"),
    ("trigger", "agent_events_no_update"),
    ("trigger", "agent_events_no_delete"),
    ("trigger", "agent_plan_revisions_no_update"),
    ("trigger", "agent_plan_revisions_no_delete"),
    ("trigger", "agent_approvals_no_update"),
    ("trigger", "agent_approvals_no_delete"),
)
_AUTHORIZATION_OBJECTS = (
    ("table", "agent_session_effect_budgets"),
    ("index", "idx_agent_session_effect_budgets_session_idempotency"),
    ("table", "agent_run_authorizations"),
    ("index", "idx_agent_run_authorizations_session"),
    ("index", "idx_agent_run_authorizations_run"),
    ("index", "idx_agent_run_authorizations_session_idempotency"),
    ("trigger", "agent_session_effect_budgets_no_update"),
    ("trigger", "agent_session_effect_budgets_no_delete"),
    ("trigger", "agent_run_authorizations_no_update"),
    ("trigger", "agent_run_authorizations_no_delete"),
    ("trigger", "agent_bound_runs_no_delete"),
)

_SESSION_COLUMNS = {
    "agent_sessions": (
        (0, "session_id", "TEXT", 0, None, 1),
        (1, "contract_version", "TEXT", 1, None, 0),
        (2, "project_id", "TEXT", 1, None, 0),
        (3, "goal_json", "TEXT", 1, None, 0),
        (4, "constraints_json", "TEXT", 1, None, 0),
        (5, "budget_json", "TEXT", 1, None, 0),
        (6, "status", "TEXT", 1, None, 0),
        (7, "state_version", "INTEGER", 1, None, 0),
        (8, "plan_generation", "INTEGER", 1, "0", 0),
        (9, "active_draft_id", "TEXT", 0, None, 0),
        (10, "active_draft_revision", "INTEGER", 0, None, 0),
        (11, "active_plan_hash", "TEXT", 0, None, 0),
        (12, "workflow_revision_id", "TEXT", 0, None, 0),
        (13, "planner_json", "TEXT", 1, "'{}'", 0),
        (14, "last_error_code", "TEXT", 1, "''", 0),
        (15, "creation_request_id", "TEXT", 1, None, 0),
        (16, "creation_request_hash", "TEXT", 1, None, 0),
        (17, "created_by", "TEXT", 1, None, 0),
        (18, "created_at", "TEXT", 1, None, 0),
        (19, "updated_at", "TEXT", 1, None, 0),
        (20, "cancelled_at", "TEXT", 0, None, 0),
    ),
    "agent_plan_revisions": (
        (0, "plan_revision_id", "TEXT", 0, None, 1),
        (1, "contract_version", "TEXT", 1, None, 0),
        (2, "session_id", "TEXT", 1, None, 0),
        (3, "plan_generation", "INTEGER", 1, None, 0),
        (4, "parent_plan_revision_id", "TEXT", 0, None, 0),
        (5, "draft_id", "TEXT", 1, None, 0),
        (6, "draft_revision", "INTEGER", 1, None, 0),
        (7, "plan_hash", "TEXT", 1, None, 0),
        (8, "proposal_json", "TEXT", 1, None, 0),
        (9, "validation_json", "TEXT", 1, None, 0),
        (10, "budget_json", "TEXT", 1, None, 0),
        (11, "created_by", "TEXT", 1, None, 0),
        (12, "created_at", "TEXT", 1, None, 0),
    ),
    "agent_approvals": (
        (0, "approval_id", "TEXT", 0, None, 1),
        (1, "contract_version", "TEXT", 1, None, 0),
        (2, "session_id", "TEXT", 1, None, 0),
        (3, "plan_revision_id", "TEXT", 1, None, 0),
        (4, "plan_generation", "INTEGER", 1, None, 0),
        (5, "plan_hash", "TEXT", 1, None, 0),
        (6, "expected_state_version", "INTEGER", 1, None, 0),
        (7, "decision", "TEXT", 1, None, 0),
        (8, "scope", "TEXT", 1, None, 0),
        (9, "actor", "TEXT", 1, None, 0),
        (10, "reason", "TEXT", 0, None, 0),
        (11, "request_id", "TEXT", 1, None, 0),
        (12, "idempotency_key", "TEXT", 1, None, 0),
        (13, "approval_hash", "TEXT", 1, None, 0),
        (14, "created_at", "TEXT", 1, None, 0),
    ),
    "agent_events": (
        (0, "event_id", "TEXT", 0, None, 1),
        (1, "session_id", "TEXT", 1, None, 0),
        (2, "seq", "INTEGER", 1, None, 0),
        (3, "schema_version", "TEXT", 1, None, 0),
        (4, "event_type", "TEXT", 1, None, 0),
        (5, "from_status", "TEXT", 0, None, 0),
        (6, "to_status", "TEXT", 1, None, 0),
        (7, "state_version", "INTEGER", 1, None, 0),
        (8, "plan_generation", "INTEGER", 1, None, 0),
        (9, "actor", "TEXT", 1, None, 0),
        (10, "request_id", "TEXT", 1, None, 0),
        (11, "correlation_id", "TEXT", 0, None, 0),
        (12, "idempotency_key", "TEXT", 1, None, 0),
        (13, "command_hash", "TEXT", 1, None, 0),
        (14, "payload_json", "TEXT", 1, None, 0),
        (15, "payload_hash", "TEXT", 1, None, 0),
        (16, "event_hash", "TEXT", 1, None, 0),
        (17, "prev_event_hash", "TEXT", 0, None, 0),
        (18, "created_at", "TEXT", 1, None, 0),
    ),
}

_AUTHORIZATION_COLUMNS = {
    "agent_session_effect_budgets": (
        (0, "session_id", "TEXT", 0, None, 1),
        (1, "contract_version", "TEXT", 1, None, 0),
        (2, "max_run_submissions", "INTEGER", 1, None, 0),
        (3, "actor", "TEXT", 1, None, 0),
        (4, "request_id", "TEXT", 1, None, 0),
        (5, "idempotency_key", "TEXT", 1, None, 0),
        (6, "command_hash", "TEXT", 1, None, 0),
        (7, "receipt_hash", "TEXT", 1, None, 0),
        (8, "created_at", "TEXT", 1, None, 0),
    ),
    "agent_run_authorizations": (
        (0, "authorization_id", "TEXT", 0, None, 1),
        (1, "contract_version", "TEXT", 1, None, 0),
        (2, "session_id", "TEXT", 1, None, 0),
        (3, "preview_hash", "TEXT", 1, None, 0),
        (4, "plan_revision_id", "TEXT", 1, None, 0),
        (5, "plan_generation", "INTEGER", 1, None, 0),
        (6, "plan_hash", "TEXT", 1, None, 0),
        (7, "workflow_revision_id", "TEXT", 1, None, 0),
        (8, "expected_state_version", "INTEGER", 1, None, 0),
        (9, "input_manifest_digest", "TEXT", 1, None, 0),
        (10, "run_spec_hash", "TEXT", 1, None, 0),
        (11, "execution_policy_id", "TEXT", 1, None, 0),
        (12, "execution_policy_hash", "TEXT", 1, None, 0),
        (13, "runtime_lock_hash", "TEXT", 1, None, 0),
        (14, "runtime_proof_hash", "TEXT", 1, None, 0),
        (15, "effect_budget_hash", "TEXT", 1, None, 0),
        (16, "run_id", "TEXT", 1, None, 0),
        (17, "scope", "TEXT", 1, None, 0),
        (18, "confirmation", "TEXT", 1, None, 0),
        (19, "actor", "TEXT", 1, None, 0),
        (20, "request_id", "TEXT", 1, None, 0),
        (21, "idempotency_key", "TEXT", 1, None, 0),
        (22, "command_hash", "TEXT", 1, None, 0),
        (23, "receipt_hash", "TEXT", 1, None, 0),
        (24, "created_at", "TEXT", 1, None, 0),
    ),
}

_SESSION_INDEXES = {
    "agent_sessions": {
        "idx_agent_sessions_status_updated": (False, False, ("status", "updated_at")),
        "idx_agent_sessions_project_updated": (False, False, ("project_id", "updated_at")),
    },
    "agent_plan_revisions": {
        "idx_agent_plan_revisions_session_generation": (
            False,
            False,
            ("session_id", "plan_generation"),
        ),
        "idx_agent_plan_revisions_hash": (False, False, ("plan_hash",)),
    },
    "agent_approvals": {
        "idx_agent_approvals_session_plan": (
            False,
            False,
            ("session_id", "plan_generation", "created_at"),
        ),
        "idx_agent_approvals_effective_decision": (
            True,
            False,
            ("session_id", "plan_generation", "expected_state_version"),
        ),
    },
    "agent_events": {
        "idx_agent_events_session_idempotency": (
            True,
            True,
            ("session_id", "idempotency_key"),
        ),
        "idx_agent_events_hash_chain": (
            False,
            False,
            ("session_id", "seq", "event_hash"),
        ),
    },
}
_AUTHORIZATION_INDEXES = {
    "agent_session_effect_budgets": {
        "idx_agent_session_effect_budgets_session_idempotency": (
            True,
            False,
            ("session_id", "idempotency_key"),
        ),
    },
    "agent_run_authorizations": {
        "idx_agent_run_authorizations_session": (True, False, ("session_id",)),
        "idx_agent_run_authorizations_run": (True, False, ("run_id",)),
        "idx_agent_run_authorizations_session_idempotency": (
            True,
            False,
            ("session_id", "idempotency_key"),
        ),
    },
}

_AUTHORIZATION_FOREIGN_KEYS = {
    "agent_session_effect_budgets": {
        ("session_id", "agent_sessions", "session_id", "NO ACTION", "RESTRICT", "NONE")
    },
    "agent_run_authorizations": {
        ("session_id", "agent_sessions", "session_id", "NO ACTION", "RESTRICT", "NONE"),
        (
            "plan_revision_id",
            "agent_plan_revisions",
            "plan_revision_id",
            "NO ACTION",
            "RESTRICT",
            "NONE",
        ),
        (
            "workflow_revision_id",
            "workflow_revisions",
            "workflow_revision_id",
            "NO ACTION",
            "RESTRICT",
            "NONE",
        ),
        ("run_id", "runs", "run_id", "NO ACTION", "RESTRICT", "NONE"),
    },
}

_SESSION_TRIGGERS = {
    "agent_sessions": (),
    "agent_plan_revisions": (
        "agent_plan_revisions_no_delete",
        "agent_plan_revisions_no_update",
    ),
    "agent_approvals": (
        "agent_approvals_no_delete",
        "agent_approvals_no_update",
    ),
    "agent_events": ("agent_events_no_delete", "agent_events_no_update"),
}
_AUTHORIZATION_TRIGGERS = {
    "agent_session_effect_budgets": (
        "agent_session_effect_budgets_no_delete",
        "agent_session_effect_budgets_no_update",
    ),
    "agent_run_authorizations": (
        "agent_run_authorizations_no_delete",
        "agent_run_authorizations_no_update",
    ),
    "runs": ("agent_bound_runs_no_delete",),
}


def assert_agent_session_schema(connection: sqlite3.Connection) -> None:
    _assert_exact_schema(
        connection,
        objects=_SESSION_OBJECTS,
        statements=AGENT_SESSION_SCHEMA_STATEMENTS,
        columns=_SESSION_COLUMNS,
        indexes=_SESSION_INDEXES,
        foreign_keys={table: set() for table in _SESSION_COLUMNS},
        triggers=_SESSION_TRIGGERS,
        error_code=AGENT_SESSION_SCHEMA_SIGNATURE_MISMATCH,
    )


def assert_agent_run_authorization_schema(connection: sqlite3.Connection) -> None:
    _assert_exact_schema(
        connection,
        objects=_AUTHORIZATION_OBJECTS,
        statements=AGENT_RUN_AUTHORIZATION_SCHEMA_STATEMENTS,
        columns=_AUTHORIZATION_COLUMNS,
        indexes=_AUTHORIZATION_INDEXES,
        foreign_keys=_AUTHORIZATION_FOREIGN_KEYS,
        triggers=_AUTHORIZATION_TRIGGERS,
        error_code=AGENT_RUN_AUTHORIZATION_SCHEMA_SIGNATURE_MISMATCH,
    )


def assert_agent_control_plane_schema(connection: sqlite3.Connection) -> None:
    assert_agent_session_schema(connection)
    assert_agent_run_authorization_schema(connection)


def _assert_exact_schema(
    connection: sqlite3.Connection,
    *,
    objects: Sequence[tuple[str, str]],
    statements: Sequence[str],
    columns: Mapping[str, Sequence[tuple[object, ...]]],
    indexes: Mapping[str, Mapping[str, tuple[bool, bool, tuple[str, ...]]]],
    foreign_keys: Mapping[str, set[tuple[str, ...]]],
    triggers: Mapping[str, Sequence[str]],
    error_code: str,
) -> None:
    expected_sql = {
        identity: _normalize_sql(statement)
        for identity, statement in zip(objects, statements, strict=True)
    }
    for object_type, object_name in objects:
        row = connection.execute(
            "SELECT type, sql FROM sqlite_master WHERE name = ?",
            (object_name,),
        ).fetchone()
        if row is None or str(row[0]) != object_type or row[1] is None:
            _fail(error_code, f"missing-or-wrong-type:{object_name}")
        if _normalize_sql(str(row[1])) != expected_sql[(object_type, object_name)]:
            _fail(error_code, f"object-sql:{object_name}")

    for table_name, expected_columns in columns.items():
        observed_columns = tuple(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]),
                int(row[3]),
                None if row[4] is None else str(row[4]),
                int(row[5]),
            )
            for row in connection.execute(
                f"PRAGMA table_info({_quote_pragma_identifier(table_name)})"
            ).fetchall()
        )
        if observed_columns != tuple(expected_columns):
            _fail(error_code, f"columns:{table_name}")
        _assert_indexes(
            connection,
            table_name=table_name,
            expected=indexes.get(table_name, {}),
            error_code=error_code,
        )
        observed_foreign_keys = {
            (
                str(row[3]),
                str(row[2]),
                str(row[4]),
                str(row[5]).upper(),
                str(row[6]).upper(),
                str(row[7]).upper(),
            )
            for row in connection.execute(
                f"PRAGMA foreign_key_list({_quote_pragma_identifier(table_name)})"
            ).fetchall()
        }
        if observed_foreign_keys != foreign_keys[table_name]:
            _fail(error_code, f"foreign-keys:{table_name}")
    assert_exact_trigger_sets(
        connection,
        expected_by_table=triggers,
        error_code=error_code,
    )


def _assert_indexes(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    expected: Mapping[str, tuple[bool, bool, tuple[str, ...]]],
    error_code: str,
) -> None:
    observed: dict[str, tuple[bool, bool, tuple[str, ...]]] = {}
    for row in connection.execute(
        f"PRAGMA index_list({_quote_pragma_identifier(table_name)})"
    ).fetchall():
        if str(row[3]) != "c":
            continue
        index_name = str(row[1])
        observed[index_name] = (
            bool(row[2]),
            bool(row[4]),
            tuple(
                str(column[2])
                for column in connection.execute(
                    f"PRAGMA index_info({_quote_pragma_identifier(index_name)})"
                ).fetchall()
            ),
        )
    if observed != dict(expected):
        _fail(error_code, f"indexes:{table_name}")


def _normalize_sql(value: str) -> str:
    return " ".join(value.replace("IF NOT EXISTS", "").split()).casefold()


def _quote_pragma_identifier(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _fail(error_code: str, component: str) -> None:
    raise RuntimeError(f"{error_code}: {component}")


__all__ = [
    "AGENT_RUN_AUTHORIZATION_SCHEMA_SIGNATURE_MISMATCH",
    "AGENT_SESSION_SCHEMA_SIGNATURE_MISMATCH",
    "assert_agent_control_plane_schema",
    "assert_agent_run_authorization_schema",
    "assert_agent_session_schema",
]
