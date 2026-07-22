"""Additive schema for proof-bound Agent subprocess launch instances."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from .agent_control_plane_schema_readiness import assert_agent_control_plane_schema
from .agent_schema_trigger_namespace import assert_exact_process_trigger_sets
from .agent_process_instance_v22_schema import (
    AGENT_PROCESS_EVENT_GUARD_V21_STATEMENTS,
    AGENT_PROCESS_EVENT_GUARD_V22_STATEMENTS,
    AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX,
    AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX_STATEMENT,
    AGENT_PROCESS_V22_ENVELOPE_TRIGGER_STATEMENT,
)
from .agent_schema_migration_guard import assert_agent_schema_migration_precondition
from .agent_workspace_proof_schema import assert_agent_workspace_proof_schema


AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH = "AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH"
AGENT_PROCESS_INSTANCE_SCHEMA_NAMESPACE_COLLISION = "AGENT_PROCESS_INSTANCE_SCHEMA_NAMESPACE_COLLISION"
AGENT_PROCESS_INSTANCE_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS agent_process_instances (
        process_instance_id TEXT PRIMARY KEY CHECK (
            typeof(process_instance_id) = 'text' AND length(process_instance_id) >= 1
        ),
        contract_version TEXT NOT NULL CHECK (
            typeof(contract_version) = 'text'
            AND contract_version = 'agent-process-launch-intent.v1'
        ),
        run_id TEXT NOT NULL CHECK (typeof(run_id) = 'text' AND length(run_id) >= 1),
        authorization_id TEXT NOT NULL CHECK (
            typeof(authorization_id) = 'text' AND length(authorization_id) >= 1
        ),
        attempt_id TEXT NOT NULL CHECK (
            typeof(attempt_id) = 'text' AND length(attempt_id) >= 1
        ),
        lease_generation INTEGER NOT NULL CHECK (
            typeof(lease_generation) = 'integer' AND lease_generation >= 1
        ),
        logical_activity_id TEXT NOT NULL CHECK (
            typeof(logical_activity_id) = 'text' AND length(logical_activity_id) >= 1
        ),
        process_ordinal INTEGER NOT NULL CHECK (
            typeof(process_ordinal) = 'integer' AND process_ordinal IN (1, 2)
        ),
        process_kind TEXT NOT NULL CHECK (
            typeof(process_kind) = 'text'
            AND ((process_kind = 'dry_run' AND process_ordinal = 1)
            OR (process_kind = 'run' AND process_ordinal = 2)
            )
        ),
        workspace_proof_id TEXT NOT NULL UNIQUE CHECK (
            typeof(workspace_proof_id) = 'text' AND length(workspace_proof_id) >= 1
        ),
        tool_assets_hash TEXT NOT NULL CHECK (
            typeof(tool_assets_hash) = 'text' AND length(tool_assets_hash) = 64
            AND tool_assets_hash NOT GLOB '*[^0-9a-f]*'
        ),
        launch_spec_hash TEXT NOT NULL CHECK (
            typeof(launch_spec_hash) = 'text' AND length(launch_spec_hash) = 64
            AND launch_spec_hash NOT GLOB '*[^0-9a-f]*'
        ),
        gate_token_hash TEXT NOT NULL CHECK (
            typeof(gate_token_hash) = 'text' AND length(gate_token_hash) = 64
            AND gate_token_hash NOT GLOB '*[^0-9a-f]*'
        ),
        spawn_intent_event_id TEXT NOT NULL UNIQUE CHECK (
            typeof(spawn_intent_event_id) = 'text'
            AND length(spawn_intent_event_id) >= 1
        ),
        spawn_intent_event_hash TEXT NOT NULL CHECK (
            typeof(spawn_intent_event_hash) = 'text'
            AND length(spawn_intent_event_hash) = 64
            AND spawn_intent_event_hash NOT GLOB '*[^0-9a-f]*'
        ),
        state TEXT NOT NULL CHECK (
            typeof(state) = 'text' AND state IN (
                'prepared', 'started', 'exited', 'spawn_failed',
                'terminated', 'lost'
            )
        ),
        process_pid INTEGER CHECK (
            process_pid IS NULL OR (typeof(process_pid) = 'integer' AND process_pid >= 1)
        ),
        process_group_id INTEGER CHECK (
            process_group_id IS NULL
            OR (typeof(process_group_id) = 'integer' AND process_group_id >= 1)
        ),
        process_incarnation_json TEXT CHECK (
            process_incarnation_json IS NULL
            OR (typeof(process_incarnation_json) = 'text'
                AND length(process_incarnation_json) >= 1
                AND json_valid(process_incarnation_json))
        ),
        process_incarnation_hash TEXT CHECK (
            process_incarnation_hash IS NULL
            OR (
                typeof(process_incarnation_hash) = 'text'
                AND length(process_incarnation_hash) = 64
                AND process_incarnation_hash NOT GLOB '*[^0-9a-f]*'
            )
        ),
        started_event_id TEXT UNIQUE CHECK (
            started_event_id IS NULL
            OR (typeof(started_event_id) = 'text' AND length(started_event_id) >= 1)
        ),
        terminal_event_id TEXT UNIQUE CHECK (
            terminal_event_id IS NULL
            OR (typeof(terminal_event_id) = 'text' AND length(terminal_event_id) >= 1)
        ),
        exit_code INTEGER CHECK (exit_code IS NULL OR typeof(exit_code) = 'integer'),
        exit_reason TEXT CHECK (
            exit_reason IS NULL
            OR (typeof(exit_reason) = 'text' AND length(exit_reason) >= 1)
        ),
        prepared_at TEXT NOT NULL CHECK (
            typeof(prepared_at) = 'text' AND length(prepared_at) >= 1
        ),
        started_at TEXT CHECK (
            started_at IS NULL OR (typeof(started_at) = 'text' AND length(started_at) >= 1)
        ),
        finished_at TEXT CHECK (
            finished_at IS NULL OR (typeof(finished_at) = 'text' AND length(finished_at) >= 1)
        ),
        launch_intent_hash TEXT NOT NULL UNIQUE CHECK (
            typeof(launch_intent_hash) = 'text' AND length(launch_intent_hash) = 64
            AND launch_intent_hash NOT GLOB '*[^0-9a-f]*'
        ),
        UNIQUE(attempt_id, lease_generation, process_ordinal),
        UNIQUE(gate_token_hash),
        FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE RESTRICT,
        FOREIGN KEY (authorization_id)
            REFERENCES agent_run_authorizations(authorization_id) ON DELETE RESTRICT,
        FOREIGN KEY (attempt_id)
            REFERENCES run_attempts(attempt_id) ON DELETE RESTRICT,
        FOREIGN KEY (workspace_proof_id)
            REFERENCES agent_workspace_proofs(workspace_proof_id) ON DELETE RESTRICT,
        FOREIGN KEY (spawn_intent_event_id)
            REFERENCES run_events(event_id) ON DELETE RESTRICT,
        FOREIGN KEY (started_event_id)
            REFERENCES run_events(event_id) ON DELETE RESTRICT,
        FOREIGN KEY (terminal_event_id)
            REFERENCES run_events(event_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_process_instances_attempt_state
    ON agent_process_instances(attempt_id, lease_generation, state)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_process_instances_run_ordinal
    ON agent_process_instances(run_id, process_ordinal)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_process_instances_state_started
    ON agent_process_instances(state, started_at)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_process_instances_incarnation_hash
    ON agent_process_instances(process_incarnation_hash)
    WHERE process_incarnation_hash IS NOT NULL
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_insert_guard
    BEFORE INSERT ON agent_process_instances
    BEGIN
        SELECT CASE WHEN
            NEW.state <> 'prepared'
            OR NEW.process_pid IS NOT NULL
            OR NEW.process_group_id IS NOT NULL
            OR NEW.process_incarnation_json IS NOT NULL
            OR NEW.process_incarnation_hash IS NOT NULL
            OR NEW.started_event_id IS NOT NULL
            OR NEW.terminal_event_id IS NOT NULL
            OR NEW.exit_code IS NOT NULL
            OR NEW.exit_reason IS NOT NULL
            OR NEW.started_at IS NOT NULL
            OR NEW.finished_at IS NOT NULL
        THEN RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_PREPARED_SHAPE_INVALID') END;
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM agent_workspace_proofs AS proof
            WHERE proof.workspace_proof_id = NEW.workspace_proof_id
              AND proof.run_id = NEW.run_id
              AND proof.authorization_id = NEW.authorization_id
              AND proof.attempt_id = NEW.attempt_id
              AND proof.lease_generation = NEW.lease_generation
              AND proof.tool_assets_hash = NEW.tool_assets_hash
              AND proof.event_id = NEW.spawn_intent_event_id
              AND proof.process_ordinal = NEW.process_ordinal
              AND proof.process_boundary = CASE NEW.process_kind
                    WHEN 'dry_run' THEN 'pre_dry_run'
                    WHEN 'run' THEN 'pre_run'
                  END
        )
        THEN RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_PROOF_BINDING_INVALID') END;
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM run_events AS event
            WHERE event.event_id = NEW.spawn_intent_event_id
              AND event.run_id = NEW.run_id
              AND event.event_type = 'agent_process_spawn_intent_recorded'
              AND event.schema_version = 'run-event.v2'
              AND typeof(event.seq) = 'integer' AND event.seq > 0
              AND typeof(event.payload_hash) = 'text'
              AND length(event.payload_hash) = 64
              AND event.payload_hash NOT GLOB '*[^0-9a-f]*'
              AND typeof(event.event_hash) = 'text'
              AND length(event.event_hash) = 64
              AND event.event_hash NOT GLOB '*[^0-9a-f]*'
              AND event.event_hash = NEW.spawn_intent_event_hash
              AND typeof(event.details_json) = 'text'
              AND json_valid(event.details_json)
              AND json_type(event.details_json, '$.schema_version') = 'text'
              AND json_extract(event.details_json, '$.schema_version') = event.schema_version
              AND json_type(event.details_json, '$.sequence') = 'integer'
              AND json_extract(event.details_json, '$.sequence') = event.seq
              AND json_type(event.details_json, '$.payload_hash') = 'text'
              AND json_extract(event.details_json, '$.payload_hash') = event.payload_hash
              AND json_type(event.details_json, '$.event_hash') = 'text'
              AND json_extract(event.details_json, '$.event_hash') = event.event_hash
              AND json_type(event.details_json, '$.payload.attemptId') = 'text'
              AND json_extract(event.details_json, '$.payload.attemptId') = NEW.attempt_id
              AND json_type(event.details_json, '$.payload.leaseGeneration') = 'integer'
              AND json_extract(event.details_json, '$.payload.leaseGeneration') = NEW.lease_generation
              AND json_type(event.details_json, '$.payload.processKind') = 'text'
              AND json_extract(event.details_json, '$.payload.processKind') = NEW.process_kind
              AND json_type(event.details_json, '$.payload.processOrdinal') = 'integer'
              AND json_extract(event.details_json, '$.payload.processOrdinal') = NEW.process_ordinal
              AND json_type(event.details_json, '$.payload.workspaceProofId') = 'text'
              AND json_extract(event.details_json, '$.payload.workspaceProofId') = NEW.workspace_proof_id
              AND json_type(event.details_json, '$.payload.launchSpecHash') = 'text'
              AND json_extract(event.details_json, '$.payload.launchSpecHash') = NEW.launch_spec_hash
              AND json_type(event.details_json, '$.payload.gateTokenHash') = 'text'
              AND json_extract(event.details_json, '$.payload.gateTokenHash') = NEW.gate_token_hash
        )
        THEN RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_SPAWN_EVENT_INVALID') END;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_intent_immutable
    BEFORE UPDATE ON agent_process_instances
    WHEN OLD.process_instance_id IS NOT NEW.process_instance_id
      OR OLD.contract_version IS NOT NEW.contract_version
      OR OLD.run_id IS NOT NEW.run_id
      OR OLD.authorization_id IS NOT NEW.authorization_id
      OR OLD.attempt_id IS NOT NEW.attempt_id
      OR OLD.lease_generation IS NOT NEW.lease_generation
      OR OLD.logical_activity_id IS NOT NEW.logical_activity_id
      OR OLD.process_ordinal IS NOT NEW.process_ordinal
      OR OLD.process_kind IS NOT NEW.process_kind
      OR OLD.workspace_proof_id IS NOT NEW.workspace_proof_id
      OR OLD.tool_assets_hash IS NOT NEW.tool_assets_hash
      OR OLD.launch_spec_hash IS NOT NEW.launch_spec_hash
      OR OLD.gate_token_hash IS NOT NEW.gate_token_hash
      OR OLD.spawn_intent_event_id IS NOT NEW.spawn_intent_event_id
      OR OLD.spawn_intent_event_hash IS NOT NEW.spawn_intent_event_hash
      OR OLD.prepared_at IS NOT NEW.prepared_at
      OR OLD.launch_intent_hash IS NOT NEW.launch_intent_hash
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_INTENT_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_transition_guard
    BEFORE UPDATE ON agent_process_instances
    WHEN NOT (
        (OLD.state = 'prepared' AND NEW.state IN ('started', 'spawn_failed'))
        OR (
            OLD.state = 'started'
            AND NEW.state IN ('exited', 'terminated', 'lost')
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_TRANSITION_INVALID');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_started_identity_immutable
    BEFORE UPDATE ON agent_process_instances
    WHEN OLD.state = 'started'
      AND (
          OLD.process_pid IS NOT NEW.process_pid
          OR OLD.process_group_id IS NOT NEW.process_group_id
          OR OLD.process_incarnation_json IS NOT NEW.process_incarnation_json
          OR OLD.process_incarnation_hash IS NOT NEW.process_incarnation_hash
          OR OLD.started_event_id IS NOT NEW.started_event_id
          OR OLD.started_at IS NOT NEW.started_at
      )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_PROCESS_IDENTITY_IMMUTABLE');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_started_shape
    BEFORE UPDATE ON agent_process_instances
    WHEN OLD.state = 'prepared'
      AND NEW.state = 'started'
      AND (
          typeof(NEW.process_pid) <> 'integer'
          OR NEW.process_pid < 1
          OR typeof(NEW.process_group_id) <> 'integer'
          OR NEW.process_group_id < 1
          OR NEW.process_incarnation_json IS NULL
          OR length(NEW.process_incarnation_json) < 1
          OR NEW.process_incarnation_hash IS NULL
          OR NEW.started_event_id IS NULL
          OR length(NEW.started_event_id) < 1
          OR NEW.started_event_id = NEW.spawn_intent_event_id
          OR NEW.started_at IS NULL
          OR length(NEW.started_at) < 1
          OR NEW.terminal_event_id IS NOT NULL
          OR NEW.exit_code IS NOT NULL
          OR NEW.exit_reason IS NOT NULL
          OR NEW.finished_at IS NOT NULL
      )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_STARTED_SHAPE_INVALID');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_spawn_failed_shape
    BEFORE UPDATE ON agent_process_instances
    WHEN OLD.state = 'prepared'
      AND NEW.state = 'spawn_failed'
      AND (
          NEW.process_pid IS NOT NULL
          OR NEW.process_group_id IS NOT NULL
          OR NEW.process_incarnation_json IS NOT NULL
          OR NEW.process_incarnation_hash IS NOT NULL
          OR NEW.started_event_id IS NOT NULL
          OR NEW.started_at IS NOT NULL
          OR NEW.terminal_event_id IS NULL
          OR length(NEW.terminal_event_id) < 1
          OR NEW.terminal_event_id = NEW.spawn_intent_event_id
          OR NEW.exit_code IS NOT NULL
          OR NEW.exit_reason IS NULL
          OR length(NEW.exit_reason) < 1
          OR NEW.finished_at IS NULL
          OR length(NEW.finished_at) < 1
      )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_SPAWN_FAILED_SHAPE_INVALID');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_exited_shape
    BEFORE UPDATE ON agent_process_instances
    WHEN OLD.state = 'started'
      AND NEW.state = 'exited'
      AND (
          NEW.terminal_event_id IS NULL
          OR length(NEW.terminal_event_id) < 1
          OR NEW.terminal_event_id = NEW.spawn_intent_event_id
          OR NEW.terminal_event_id = NEW.started_event_id
          OR typeof(NEW.exit_code) <> 'integer'
          OR NEW.exit_reason IS NULL
          OR length(NEW.exit_reason) < 1
          OR NEW.finished_at IS NULL
          OR length(NEW.finished_at) < 1
      )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_EXITED_SHAPE_INVALID');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_stopped_shape
    BEFORE UPDATE ON agent_process_instances
    WHEN OLD.state = 'started'
      AND NEW.state IN ('terminated', 'lost')
      AND (
          NEW.terminal_event_id IS NULL
          OR length(NEW.terminal_event_id) < 1
          OR NEW.terminal_event_id = NEW.spawn_intent_event_id
          OR NEW.terminal_event_id = NEW.started_event_id
          OR NEW.exit_code IS NOT NULL
          OR NEW.exit_reason IS NULL
          OR length(NEW.exit_reason) < 1
          OR NEW.finished_at IS NULL
          OR length(NEW.finished_at) < 1
      )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_STOPPED_SHAPE_INVALID');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_event_binding
    BEFORE UPDATE ON agent_process_instances
    WHEN ((OLD.state = 'prepared' AND NEW.state IN ('started', 'spawn_failed'))
          OR (OLD.state = 'started' AND NEW.state IN ('exited', 'terminated', 'lost')))
      AND CASE WHEN NEW.state = 'started' THEN NEW.started_event_id
               ELSE NEW.terminal_event_id END IS NOT NULL
      AND NOT EXISTS (
            SELECT 1 FROM run_events AS event
            JOIN run_events AS prior ON prior.event_id = CASE
                WHEN NEW.state IN ('started', 'spawn_failed')
                THEN NEW.spawn_intent_event_id ELSE NEW.started_event_id END
            WHERE event.event_id = CASE WHEN NEW.state = 'started'
                    THEN NEW.started_event_id ELSE NEW.terminal_event_id END
              AND event.run_id = NEW.run_id
              AND event.event_type = CASE NEW.state
                    WHEN 'started' THEN 'agent_process_started'
                    WHEN 'spawn_failed' THEN 'agent_process_spawn_failed'
                    WHEN 'exited' THEN 'agent_process_exited'
                    WHEN 'terminated' THEN 'agent_process_terminated'
                    WHEN 'lost' THEN 'agent_process_lost' END
              AND event.schema_version = 'run-event.v2'
              AND typeof(event.seq) = 'integer' AND event.seq > prior.seq
              AND typeof(event.payload_hash) = 'text'
              AND length(event.payload_hash) = 64
              AND event.payload_hash NOT GLOB '*[^0-9a-f]*'
              AND typeof(event.event_hash) = 'text'
              AND length(event.event_hash) = 64
              AND event.event_hash NOT GLOB '*[^0-9a-f]*'
              AND typeof(event.details_json) = 'text'
              AND json_valid(event.details_json)
              AND json_type(event.details_json, '$.schema_version') = 'text'
              AND json_extract(event.details_json, '$.schema_version') = event.schema_version
              AND json_type(event.details_json, '$.sequence') = 'integer'
              AND json_extract(event.details_json, '$.sequence') = event.seq
              AND json_type(event.details_json, '$.payload_hash') = 'text'
              AND json_extract(event.details_json, '$.payload_hash') = event.payload_hash
              AND json_type(event.details_json, '$.event_hash') = 'text'
              AND json_extract(event.details_json, '$.event_hash') = event.event_hash
              AND json_type(event.details_json, '$.payload.processInstanceId') = 'text'
              AND json_extract(event.details_json, '$.payload.processInstanceId') = NEW.process_instance_id
              AND json_type(event.details_json, '$.payload.attemptId') = 'text'
              AND json_extract(event.details_json, '$.payload.attemptId') = NEW.attempt_id
              AND json_type(event.details_json, '$.payload.leaseGeneration') = 'integer'
              AND json_extract(event.details_json, '$.payload.leaseGeneration') = NEW.lease_generation
              AND json_type(event.details_json, '$.payload.processKind') = 'text'
              AND json_extract(event.details_json, '$.payload.processKind') = NEW.process_kind
              AND json_type(event.details_json, '$.payload.processOrdinal') = 'integer'
              AND json_extract(event.details_json, '$.payload.processOrdinal') = NEW.process_ordinal
        )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_EVENT_BINDING_INVALID');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_event_role_unique_insert
    BEFORE INSERT ON agent_process_instances
    WHEN (NEW.started_event_id IS NOT NULL AND NEW.started_event_id = NEW.spawn_intent_event_id)
      OR (NEW.terminal_event_id IS NOT NULL AND NEW.terminal_event_id IN (
            NEW.spawn_intent_event_id, NEW.started_event_id))
      OR EXISTS (
        SELECT 1 FROM agent_process_instances AS existing
        WHERE existing.spawn_intent_event_id IN (
                NEW.spawn_intent_event_id, NEW.started_event_id, NEW.terminal_event_id)
           OR existing.started_event_id IN (
                NEW.spawn_intent_event_id, NEW.started_event_id, NEW.terminal_event_id)
           OR existing.terminal_event_id IN (
                NEW.spawn_intent_event_id, NEW.started_event_id, NEW.terminal_event_id)
      )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_EVENT_ROLE_REUSED');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_event_role_unique_update
    BEFORE UPDATE ON agent_process_instances
    WHEN (NEW.started_event_id IS NOT NULL AND NEW.started_event_id = NEW.spawn_intent_event_id)
      OR (NEW.terminal_event_id IS NOT NULL AND NEW.terminal_event_id IN (
            NEW.spawn_intent_event_id, NEW.started_event_id))
      OR EXISTS (
        SELECT 1 FROM agent_process_instances AS existing
        WHERE existing.process_instance_id <> NEW.process_instance_id
          AND (existing.spawn_intent_event_id IN (
                    NEW.spawn_intent_event_id, NEW.started_event_id, NEW.terminal_event_id)
            OR existing.started_event_id IN (
                    NEW.spawn_intent_event_id, NEW.started_event_id, NEW.terminal_event_id)
            OR existing.terminal_event_id IN (
                    NEW.spawn_intent_event_id, NEW.started_event_id, NEW.terminal_event_id))
      )
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_EVENT_ROLE_REUSED');
    END
    """,
    *AGENT_PROCESS_EVENT_GUARD_V22_STATEMENTS,
    """
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_no_delete
    BEFORE DELETE ON agent_process_instances
    BEGIN
        SELECT RAISE(ABORT, 'AGENT_PROCESS_INSTANCE_IMMUTABLE');
    END
    """,
    AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX_STATEMENT,
    AGENT_PROCESS_V22_ENVELOPE_TRIGGER_STATEMENT,
)

AGENT_PROCESS_INSTANCE_SCHEMA_SQL = "\n".join(f"{statement.strip()};" for statement in AGENT_PROCESS_INSTANCE_SCHEMA_STATEMENTS)
_V22_TO_V21_EVENT_GUARD = dict(zip(AGENT_PROCESS_EVENT_GUARD_V22_STATEMENTS,
    AGENT_PROCESS_EVENT_GUARD_V21_STATEMENTS, strict=True))
_AGENT_PROCESS_INSTANCE_V21_SCHEMA_STATEMENTS = tuple(
    _V22_TO_V21_EVENT_GUARD.get(statement, statement)
    for statement in AGENT_PROCESS_INSTANCE_SCHEMA_STATEMENTS
    if statement not in {AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX_STATEMENT,
        AGENT_PROCESS_V22_ENVELOPE_TRIGGER_STATEMENT}
)
AGENT_PROCESS_INSTANCE_V21_SCHEMA_SQL = "\n".join(f"{statement.strip()};" for statement in _AGENT_PROCESS_INSTANCE_V21_SCHEMA_STATEMENTS)

_SCHEMA_OBJECT_IDENTITIES = (
    ("table", "agent_process_instances"),
    ("index", "idx_agent_process_instances_attempt_state"),
    ("index", "idx_agent_process_instances_run_ordinal"),
    ("index", "idx_agent_process_instances_state_started"),
    ("index", "idx_agent_process_instances_incarnation_hash"),
    ("trigger", "agent_process_instances_insert_guard"),
    ("trigger", "agent_process_instances_intent_immutable"),
    ("trigger", "agent_process_instances_transition_guard"),
    ("trigger", "agent_process_instances_started_identity_immutable"),
    ("trigger", "agent_process_instances_started_shape"),
    ("trigger", "agent_process_instances_spawn_failed_shape"),
    ("trigger", "agent_process_instances_exited_shape"),
    ("trigger", "agent_process_instances_stopped_shape"),
    ("trigger", "agent_process_instances_event_binding"),
    ("trigger", "agent_process_instances_event_role_unique_insert"),
    ("trigger", "agent_process_instances_event_role_unique_update"),
    ("trigger", "agent_process_instances_run_events_no_update"),
    ("trigger", "agent_process_instances_run_events_no_delete"),
    ("trigger", "agent_process_instances_no_delete"),
    ("index", AGENT_PROCESS_LOGICAL_ACTIVITY_UNIQUE_INDEX),
    ("trigger", "agent_process_instances_envelope_guard"),
)
_V21_SCHEMA_OBJECT_IDENTITIES = _SCHEMA_OBJECT_IDENTITIES[:-2]

_EXPECTED_COLUMNS = (
    (0, "process_instance_id", "TEXT", 0, None, 1),
    (1, "contract_version", "TEXT", 1, None, 0),
    (2, "run_id", "TEXT", 1, None, 0),
    (3, "authorization_id", "TEXT", 1, None, 0),
    (4, "attempt_id", "TEXT", 1, None, 0),
    (5, "lease_generation", "INTEGER", 1, None, 0),
    (6, "logical_activity_id", "TEXT", 1, None, 0),
    (7, "process_ordinal", "INTEGER", 1, None, 0),
    (8, "process_kind", "TEXT", 1, None, 0),
    (9, "workspace_proof_id", "TEXT", 1, None, 0),
    (10, "tool_assets_hash", "TEXT", 1, None, 0),
    (11, "launch_spec_hash", "TEXT", 1, None, 0),
    (12, "gate_token_hash", "TEXT", 1, None, 0),
    (13, "spawn_intent_event_id", "TEXT", 1, None, 0),
    (14, "spawn_intent_event_hash", "TEXT", 1, None, 0),
    (15, "state", "TEXT", 1, None, 0),
    (16, "process_pid", "INTEGER", 0, None, 0),
    (17, "process_group_id", "INTEGER", 0, None, 0),
    (18, "process_incarnation_json", "TEXT", 0, None, 0),
    (19, "process_incarnation_hash", "TEXT", 0, None, 0),
    (20, "started_event_id", "TEXT", 0, None, 0),
    (21, "terminal_event_id", "TEXT", 0, None, 0),
    (22, "exit_code", "INTEGER", 0, None, 0),
    (23, "exit_reason", "TEXT", 0, None, 0),
    (24, "prepared_at", "TEXT", 1, None, 0),
    (25, "started_at", "TEXT", 0, None, 0),
    (26, "finished_at", "TEXT", 0, None, 0),
    (27, "launch_intent_hash", "TEXT", 1, None, 0),
)

_EXPECTED_UNIQUE_COLUMN_SETS = (
    ("attempt_id", "lease_generation", "process_ordinal"),
    ("gate_token_hash",),
    ("launch_intent_hash",),
    ("spawn_intent_event_id",),
    ("started_event_id",),
    ("terminal_event_id",),
    ("workspace_proof_id",),
)

_EXPECTED_FOREIGN_KEYS = (
    (
        "attempt_id",
        "run_attempts",
        "attempt_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ),
    (
        "authorization_id",
        "agent_run_authorizations",
        "authorization_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ),
    ("run_id", "runs", "run_id", "NO ACTION", "RESTRICT", "NONE"),
    (
        "spawn_intent_event_id",
        "run_events",
        "event_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ),
    (
        "started_event_id",
        "run_events",
        "event_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ),
    (
        "terminal_event_id",
        "run_events",
        "event_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ),
    (
        "workspace_proof_id",
        "agent_workspace_proofs",
        "workspace_proof_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ),
)

_EXPECTED_OBJECT_SQL = {
    identity: " ".join(statement.replace("IF NOT EXISTS", "").split()).casefold()
    for identity, statement in zip(_SCHEMA_OBJECT_IDENTITIES,
        AGENT_PROCESS_INSTANCE_SCHEMA_STATEMENTS, strict=True)
}
_V21_EXPECTED_OBJECT_SQL = {
    identity: " ".join(statement.replace("IF NOT EXISTS", "").split()).casefold()
    for identity, statement in zip(_V21_SCHEMA_OBJECT_IDENTITIES, _AGENT_PROCESS_INSTANCE_V21_SCHEMA_STATEMENTS, strict=True)
}
RecordMigration = Callable[[sqlite3.Connection, int, str], None]


def ensure_agent_process_instance_schema(
    connection: sqlite3.Connection,
    *,
    schema_version: int = 22,
) -> None:
    statements = _AGENT_PROCESS_INSTANCE_V21_SCHEMA_STATEMENTS if schema_version == 21 else AGENT_PROCESS_INSTANCE_SCHEMA_STATEMENTS
    if schema_version not in {21, 22}:
        _raise_schema_mismatch("schema-version")
    for statement in statements:
        connection.execute(statement)


def assert_agent_process_instance_schema(
    connection: sqlite3.Connection,
    *,
    schema_version: int = 22,
) -> None:
    if schema_version == 21:
        identities = _V21_SCHEMA_OBJECT_IDENTITIES
        expected_object_sql = _V21_EXPECTED_OBJECT_SQL
    elif schema_version == 22:
        identities = _SCHEMA_OBJECT_IDENTITIES
        expected_object_sql = _EXPECTED_OBJECT_SQL
    else:
        _raise_schema_mismatch("schema-version")
    for object_type, object_name in identities:
        row = connection.execute(
            "SELECT type, sql FROM sqlite_master WHERE name = ?",
            (object_name,),
        ).fetchone()
        if row is None or str(row[0]) != object_type or row[1] is None:
            _raise_schema_mismatch(f"missing-or-wrong-type:{object_name}")
        actual_sql = " ".join(str(row[1]).split()).casefold()
        if actual_sql != expected_object_sql[(object_type, object_name)]:
            _raise_schema_mismatch(f"object-sql:{object_name}")

    columns = tuple(
        (
            int(row[0]),
            str(row[1]),
            str(row[2]),
            int(row[3]),
            None if row[4] is None else str(row[4]),
            int(row[5]),
        )
        for row in connection.execute(
            "PRAGMA table_info(agent_process_instances)"
        ).fetchall()
    )
    if columns != _EXPECTED_COLUMNS:
        _raise_schema_mismatch("columns")

    unique_column_sets = tuple(
        sorted(
            tuple(
                str(column[2])
                for column in connection.execute(
                    f"PRAGMA index_info({_quote_pragma_identifier(str(index[1]))})"
                ).fetchall()
            )
            for index in connection.execute(
                "PRAGMA index_list(agent_process_instances)"
            ).fetchall()
            if bool(index[2]) and str(index[3]) == "u"
        )
    )
    if unique_column_sets != _EXPECTED_UNIQUE_COLUMN_SETS:
        _raise_schema_mismatch("unique-constraints")

    foreign_keys = tuple(
        sorted(
            (
                str(row[3]),
                str(row[2]),
                str(row[4]),
                str(row[5]).upper(),
                str(row[6]).upper(),
                str(row[7]).upper(),
            )
            for row in connection.execute(
                "PRAGMA foreign_key_list(agent_process_instances)"
            ).fetchall()
        )
    )
    if foreign_keys != _EXPECTED_FOREIGN_KEYS:
        _raise_schema_mismatch("foreign-keys")
    assert_exact_process_trigger_sets(connection, trigger_names=tuple(name for kind, name in identities if kind == "trigger"), error_code=AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH)


def migrate_agent_process_instance_schema(
    connection: sqlite3.Connection,
    *,
    record_migration: RecordMigration,
) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        assert_agent_control_plane_schema(connection)
        assert_agent_schema_migration_precondition(
            connection,
            prior_version=20,
            prior_name="020_agent_workspace_proof",
            target_version=21,
        )
        assert_agent_workspace_proof_schema(connection)
        _assert_no_preexisting_process_schema(connection)
        _ensure_schema_migrations_table(connection)
        ensure_agent_process_instance_schema(connection, schema_version=21)
        assert_agent_process_instance_schema(connection, schema_version=21)
        record_migration(connection, 21, "021_agent_process_instance")
        connection.execute("PRAGMA user_version = 21")
        connection.commit()
    except Exception:
        connection.rollback()
        raise

def _assert_no_preexisting_process_schema(connection: sqlite3.Connection) -> None:
    collision = connection.execute(
        """
        SELECT type, name FROM sqlite_master
        WHERE name = 'agent_process_instances'
           OR name GLOB 'agent_process_instances_*'
           OR name GLOB 'idx_agent_process_instances_*'
        ORDER BY name, type LIMIT 1
        """
    ).fetchone()
    if collision is not None:
        raise RuntimeError(
            f"{AGENT_PROCESS_INSTANCE_SCHEMA_NAMESPACE_COLLISION}: "
            f"{collision[0]}:{collision[1]}"
        )


def _ensure_schema_migrations_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _raise_schema_mismatch(component: str) -> None:
    raise RuntimeError(
        f"{AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH}: {component}"
    )


def _quote_pragma_identifier(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


__all__ = [
    "AGENT_PROCESS_INSTANCE_SCHEMA_NAMESPACE_COLLISION",
    "AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH",
    "AGENT_PROCESS_INSTANCE_SCHEMA_SQL",
    "AGENT_PROCESS_INSTANCE_V21_SCHEMA_SQL",
    "assert_agent_process_instance_schema",
    "ensure_agent_process_instance_schema",
    "migrate_agent_process_instance_schema",
]
