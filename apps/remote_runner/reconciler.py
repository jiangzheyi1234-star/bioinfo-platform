from __future__ import annotations

import sqlite3
from typing import Any

from .config import RemoteRunnerConfig
from .event_contracts import append_run_event_v2
from .reconciler_rules import (
    clock_jump_observation,
    expired_lease_observation,
    queued_job_observation,
)
from .storage_core import get_connection, now_iso


def run_shadow_reconciler_once(
    cfg: RemoteRunnerConfig,
    *,
    now: str | None = None,
    clock_jump_expiry_threshold: int = 10,
) -> list[dict[str, Any]]:
    observed_at = str(now or now_iso())
    with get_connection(cfg) as connection:
        expired_rows = _expired_lease_rows(connection, observed_at)
        queued_rows = _queued_job_rows(connection, observed_at)
        observations: list[dict[str, Any]] = []
        clock_jump = clock_jump_observation(
            expired_lease_count=len(expired_rows),
            threshold=int(clock_jump_expiry_threshold),
        )
        if clock_jump is not None:
            observations.append(clock_jump)
            _append_observation_to_runs(
                connection,
                rows=expired_rows,
                event_type="clock_jump_suspected",
                observation=clock_jump,
                observed_at=observed_at,
            )

        for row in expired_rows:
            observation = expired_lease_observation(dict(row))
            observations.append(observation)
            _append_observation_event(
                connection,
                run_id=str(row["run_id"]),
                event_type="run_lease_expired_observed",
                observation=observation,
                observed_at=observed_at,
            )

        for row in queued_rows:
            observations.append(queued_job_observation(dict(row)))

        connection.commit()
        return observations


def _queued_job_rows(connection: sqlite3.Connection, now: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT jobs.*
        FROM run_jobs AS jobs
        LEFT JOIN run_leases AS leases ON leases.run_id = jobs.run_id
        WHERE jobs.state = 'queued'
          AND jobs.available_at <= ?
          AND leases.run_id IS NULL
        ORDER BY jobs.priority DESC, jobs.available_at ASC, jobs.created_at ASC, jobs.job_id ASC
        """,
        (now,),
    ).fetchall()


def _expired_lease_rows(connection: sqlite3.Connection, now: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            jobs.job_id,
            jobs.run_id,
            leases.attempt_id,
            leases.lease_generation,
            leases.expires_at
        FROM run_jobs AS jobs
        JOIN run_leases AS leases ON leases.run_id = jobs.run_id
        WHERE jobs.state = 'claimed'
          AND leases.state = 'active'
          AND leases.expires_at < ?
        ORDER BY leases.expires_at ASC, jobs.run_id ASC
        """,
        (now,),
    ).fetchall()


def _append_observation_to_runs(
    connection: sqlite3.Connection,
    *,
    rows: list[sqlite3.Row],
    event_type: str,
    observation: dict[str, Any],
    observed_at: str,
) -> None:
    seen: set[str] = set()
    for row in rows:
        run_id = str(row["run_id"])
        if run_id in seen:
            continue
        seen.add(run_id)
        _append_observation_event(
            connection,
            run_id=run_id,
            event_type=event_type,
            observation=observation,
            observed_at=observed_at,
        )


def _append_observation_event(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    event_type: str,
    observation: dict[str, Any],
    observed_at: str,
) -> None:
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        return
    append_run_event_v2(
        connection,
        run_id=run_id,
        event_type=event_type,
        stage="reconcile",
        state_version=int(run["state_version"]),
        message="Shadow reconciler observation.",
        request_id=str(run["request_id"]),
        payload=observation,
        occurred_at=observed_at,
    )
