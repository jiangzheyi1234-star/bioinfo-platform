"""V22 uniqueness and run-event guards for durable Agent processes."""

from __future__ import annotations

import sqlite3


AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX = (
    "idx_agent_process_instances_logical_activity_unique"
)
AGENT_PROCESS_LOGICAL_ACTIVITY_DUPLICATE = (
    "AGENT_PROCESS_LOGICAL_ACTIVITY_DUPLICATE"
)
AGENT_PROCESS_V22_SCHEMA_NAMESPACE_COLLISION = (
    "AGENT_PROCESS_V22_SCHEMA_NAMESPACE_COLLISION"
)

AGENT_PROCESS_EVENT_GUARD_V21_STATEMENTS = (
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_run_events_no_update
    BEFORE UPDATE ON run_events
    WHEN EXISTS (
        SELECT 1 FROM agent_process_instances
        WHERE OLD.event_id IN (
            spawn_intent_event_id, started_event_id, terminal_event_id)
    )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_EVENT_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_run_events_no_delete
    BEFORE DELETE ON run_events
    WHEN EXISTS (
        SELECT 1 FROM agent_process_instances
        WHERE OLD.event_id IN (
            spawn_intent_event_id, started_event_id, terminal_event_id)
    )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_EVENT_IMMUTABLE');
    END
    """,
)

AGENT_PROCESS_EVENT_GUARD_V22_STATEMENTS = (
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_run_events_no_update
    BEFORE UPDATE ON run_events
    WHEN OLD.schema_version = 'run-event.v2'
      AND OLD.seq > 0
      AND EXISTS (
        SELECT 1 FROM agent_process_instances
        WHERE run_id = OLD.run_id
      )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_EVENT_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_run_events_no_delete
    BEFORE DELETE ON run_events
    WHEN OLD.schema_version = 'run-event.v2'
      AND OLD.seq > 0
      AND EXISTS (
        SELECT 1 FROM agent_process_instances
        WHERE run_id = OLD.run_id
      )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_EVENT_IMMUTABLE');
    END
    """,
)

AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX_STATEMENT = f"""
    CREATE UNIQUE INDEX IF NOT EXISTS {AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX}
    ON agent_process_instances(logical_activity_id)
    """

AGENT_PROCESS_V22_ENVELOPE_TRIGGER_STATEMENT = """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_envelope_guard
    BEFORE INSERT ON agent_process_instances
    WHEN NOT EXISTS (
        SELECT 1
        FROM run_events AS event
        JOIN runs AS run ON run.run_id = event.run_id
        JOIN agent_workspace_proofs AS proof
          ON proof.workspace_proof_id = NEW.workspace_proof_id
        WHERE event.event_id = NEW.spawn_intent_event_id
          AND event.run_id = NEW.run_id
          AND event.stage = 'agent_process'
          AND event.message = 'Agent process launch intent prepared.'
          AND event.actor = 'remote-runner'
          AND event.from_status IS NULL
          AND event.to_status IS NULL
          AND event.command_id IS NULL
          AND event.correlation_id IS NULL
          AND event.request_id = run.request_id
          AND event.state_version = run.state_version
          AND event.created_at = NEW.prepared_at
          AND proof.created_at = NEW.prepared_at
    )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_ENVELOPE_INVALID');
    END
    """


def upgrade_agent_process_instance_schema_to_v22(
    connection: sqlite3.Connection,
) -> None:
    """Replace exact V21 event guards and add retry-stable uniqueness."""

    collision = connection.execute(
        "SELECT type FROM sqlite_master WHERE name IN (?, ?) LIMIT 1",
        (
            AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX,
            "agent_process_instances_envelope_guard",
        ),
    ).fetchone()
    if collision is not None:
        raise RuntimeError(AGENT_PROCESS_V22_SCHEMA_NAMESPACE_COLLISION)
    duplicate = connection.execute(
        "SELECT 1 FROM agent_process_instances "
        "GROUP BY logical_activity_id HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate is not None:
        raise RuntimeError(AGENT_PROCESS_LOGICAL_ACTIVITY_DUPLICATE)

    for trigger_name in (
        "agent_process_instances_run_events_no_update",
        "agent_process_instances_run_events_no_delete",
    ):
        connection.execute(f'DROP TRIGGER "{trigger_name}"')
    for statement in AGENT_PROCESS_EVENT_GUARD_V22_STATEMENTS:
        connection.execute(statement)
    connection.execute(AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX_STATEMENT)
    connection.execute(AGENT_PROCESS_V22_ENVELOPE_TRIGGER_STATEMENT)


__all__ = [
    "AGENT_PROCESS_EVENT_GUARD_V21_STATEMENTS",
    "AGENT_PROCESS_EVENT_GUARD_V22_STATEMENTS",
    "AGENT_PROCESS_LOGICAL_ACTIVITY_DUPLICATE",
    "AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX",
    "AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX_STATEMENT",
    "AGENT_PROCESS_V22_ENVELOPE_TRIGGER_STATEMENT",
    "AGENT_PROCESS_V22_SCHEMA_NAMESPACE_COLLISION",
    "upgrade_agent_process_instance_schema_to_v22",
]
