"""Single-transaction AgentSession snapshot read model."""

from __future__ import annotations

from typing import Any

from core.contracts.agent_snapshot import (
    AGENT_SESSION_SNAPSHOT_CONTRACT_VERSION,
    AgentSessionSnapshot,
)

from .agent_plan_storage import (
    agent_approval_row_to_dict,
    agent_plan_row_to_dict,
)
from .agent_session_storage import (
    AgentSessionStorageConflictError,
    AgentSessionStorageNotFoundError,
    agent_session_event_row_to_dict,
    agent_session_row_to_dict,
    verify_agent_event_rows_hash_chain,
)
from .config import RemoteRunnerConfig
from .storage_core import get_connection


def read_agent_session_snapshot(
    cfg: RemoteRunnerConfig,
    session_id: str,
) -> dict[str, Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("AGENT_SESSION_ID_REQUIRED")

    with get_connection(cfg) as connection:
        try:
            connection.execute("BEGIN")
            session_row = connection.execute(
                "SELECT * FROM agent_sessions WHERE session_id = ?",
                (normalized_session_id,),
            ).fetchone()
            if session_row is None:
                raise AgentSessionStorageNotFoundError("AGENT_SESSION_NOT_FOUND")
            session = agent_session_row_to_dict(session_row)
            event_rows = connection.execute(
                "SELECT * FROM agent_events WHERE session_id = ? ORDER BY seq ASC",
                (normalized_session_id,),
            ).fetchall()
            event_integrity = verify_agent_event_rows_hash_chain(event_rows)
            if not event_integrity["valid"]:
                raise AgentSessionStorageConflictError(
                    "AGENT_SESSION_EVENT_HASH_CHAIN_INVALID: "
                    f"{event_integrity['reason']}"
                )
            plan_rows = connection.execute(
                """
                SELECT * FROM agent_plan_revisions
                WHERE session_id = ?
                ORDER BY plan_generation ASC
                """,
                (normalized_session_id,),
            ).fetchall()
            approval_rows = connection.execute(
                """
                SELECT * FROM agent_approvals
                WHERE session_id = ?
                ORDER BY created_at ASC, approval_id ASC
                """,
                (normalized_session_id,),
            ).fetchall()
            snapshot = AgentSessionSnapshot.model_validate(
                {
                    "contractVersion": AGENT_SESSION_SNAPSHOT_CONTRACT_VERSION,
                    "session": session,
                    "events": [agent_session_event_row_to_dict(row) for row in event_rows],
                    "plans": [agent_plan_row_to_dict(row) for row in plan_rows],
                    "approvals": [agent_approval_row_to_dict(row) for row in approval_rows],
                }
            ).runtime_payload()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return snapshot


__all__ = ["read_agent_session_snapshot"]
