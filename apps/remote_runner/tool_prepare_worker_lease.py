from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


def release_tool_prepare_worker_claim(
    cfg: RemoteRunnerConfig,
    *,
    job_id: str,
    worker_id: str,
    now: str | None = None,
) -> bool:
    released_at = str(now or now_iso())
    with get_connection(cfg) as connection:
        cursor = connection.execute(
            """
            UPDATE tool_prepare_jobs
            SET claimed_by = '', claimed_until = NULL, heartbeat_at = NULL, updated_at = ?
            WHERE job_id = ? AND claimed_by = ?
            """,
            (released_at, str(job_id or "").strip(), str(worker_id or "").strip()),
        )
        connection.commit()
    return cursor.rowcount == 1


def tool_prepare_worker_activity(connection, *, now: str) -> dict[str, Any]:
    _ = now
    rows = connection.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM tool_prepare_jobs
        WHERE status IN ('queued', 'running')
        GROUP BY status
        """
    ).fetchall()
    counts = {"queued": 0, "running": 0}
    for row in rows:
        counts[str(row["status"])] = int(row["count"] or 0)
    active_claims = int(
        connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM tool_prepare_jobs
            WHERE COALESCE(claimed_by, '') <> ''
            """
        ).fetchone()["count"]
    )
    return {
        **counts,
        "active": counts["queued"] + counts["running"],
        "activeClaims": active_claims,
    }
