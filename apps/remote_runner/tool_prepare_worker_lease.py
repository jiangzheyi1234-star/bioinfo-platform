from __future__ import annotations

from typing import Any

from .tool_prepare_claims import release_tool_prepare_worker_claim


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


__all__ = ["release_tool_prepare_worker_claim", "tool_prepare_worker_activity"]
