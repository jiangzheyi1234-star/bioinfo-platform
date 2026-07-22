"""Fail-closed trigger namespace checks for durable Agent evidence."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence


def assert_exact_trigger_sets(
    connection: sqlite3.Connection,
    *,
    expected_by_table: Mapping[str, Sequence[str]],
    error_code: str,
) -> None:
    """Require the complete trigger set for every listed evidence table."""

    for table_name, expected_names in expected_by_table.items():
        observed = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = ? ORDER BY name",
                (table_name,),
            ).fetchall()
        )
        expected = tuple(sorted(expected_names))
        if observed != expected:
            raise RuntimeError(f"{error_code}: triggers:{table_name}")


def assert_exact_runtime_trigger_namespace(
    connection: sqlite3.Connection,
    *,
    expected_names: Sequence[str],
    error_code: str,
) -> None:
    """Reject every unexpected trigger anywhere in a current runtime DB."""

    observed = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
        ).fetchall()
    )
    if observed != tuple(sorted(expected_names)):
        raise RuntimeError(f"{error_code}: runtime-triggers")


def assert_exact_process_trigger_sets(
    connection: sqlite3.Connection,
    *,
    trigger_names: Sequence[str],
    error_code: str,
) -> None:
    """Partition the process trigger contract across its two owned tables."""

    run_event_names = {
        "agent_process_instances_run_events_no_delete",
        "agent_process_instances_run_events_no_update",
    }
    names = set(trigger_names)
    assert_exact_trigger_sets(
        connection,
        expected_by_table={
            "agent_process_instances": tuple(names - run_event_names),
            "run_events": tuple(run_event_names),
        },
        error_code=error_code,
    )


__all__ = [
    "assert_exact_process_trigger_sets",
    "assert_exact_runtime_trigger_namespace",
    "assert_exact_trigger_sets",
]
