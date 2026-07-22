"""V23 exact lifecycle-event binding for durable Agent processes."""

from __future__ import annotations

import sqlite3

from .agent_process_instance_schema import assert_agent_process_instance_schema
from .agent_process_lifecycle_reasons import (
    AGENT_PROCESS_LIFECYCLE_REASON_SQL_PREDICATE,
)


AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME = (
    "agent_process_instances_lifecycle_event_exact"
)
AGENT_PROCESS_LIFECYCLE_SCHEMA_SIGNATURE_MISMATCH = (
    "AGENT_PROCESS_LIFECYCLE_SCHEMA_SIGNATURE_MISMATCH"
)
AGENT_PROCESS_LIFECYCLE_SCHEMA_NAMESPACE_COLLISION = (
    "AGENT_PROCESS_LIFECYCLE_SCHEMA_NAMESPACE_COLLISION"
)
AGENT_PROCESS_LIFECYCLE_MIGRATION_STATE_UNSUPPORTED = (
    "AGENT_PROCESS_LIFECYCLE_MIGRATION_STATE_UNSUPPORTED"
)

AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_STATEMENT = f"""
    CREATE TRIGGER IF NOT EXISTS agent_process_instances_lifecycle_event_exact
    BEFORE UPDATE ON agent_process_instances
    WHEN (
        (OLD.state = 'prepared' AND NEW.state IN ('started', 'spawn_failed'))
        OR (OLD.state = 'started'
            AND NEW.state IN ('exited', 'terminated', 'lost'))
    )
    AND NOT EXISTS (
        SELECT 1
        FROM run_events AS event
        JOIN runs AS run ON run.run_id = event.run_id
        JOIN run_events AS prior_process
          ON prior_process.event_id = CASE
              WHEN NEW.state IN ('started', 'spawn_failed')
              THEN NEW.spawn_intent_event_id
              ELSE NEW.started_event_id
             END
        JOIN run_events AS prior_global
          ON prior_global.run_id = event.run_id
         AND prior_global.seq = event.seq - 1
        WHERE event.event_id = CASE
                  WHEN NEW.state = 'started' THEN NEW.started_event_id
                  ELSE NEW.terminal_event_id
              END
          AND event.run_id = NEW.run_id
          AND event.event_type = CASE NEW.state
                  WHEN 'started' THEN 'agent_process_started'
                  WHEN 'spawn_failed' THEN 'agent_process_spawn_failed'
                  WHEN 'exited' THEN 'agent_process_exited'
                  WHEN 'terminated' THEN 'agent_process_terminated'
                  WHEN 'lost' THEN 'agent_process_lost'
              END
          AND event.schema_version = 'run-event.v2'
          AND event.stage = 'agent_process'
          AND event.message = CASE NEW.state
                  WHEN 'started'
                    THEN 'Agent process started after authorization commit.'
                  WHEN 'spawn_failed'
                    THEN 'Agent process spawn failed before start.'
                  WHEN 'exited'
                    THEN 'Agent process exited and was reaped.'
                  WHEN 'terminated'
                    THEN 'Agent process termination confirmed.'
                  WHEN 'lost'
                    THEN 'Agent process identity lost.'
              END
          AND event.actor = 'remote-runner'
          AND event.from_status IS NULL
          AND event.to_status IS NULL
          AND event.command_id IS NULL
          AND event.correlation_id IS NULL
          AND event.request_id = run.request_id
          AND event.state_version = run.state_version
          AND event.created_at = CASE
                  WHEN NEW.state = 'started' THEN NEW.started_at
                  ELSE NEW.finished_at
              END
          AND typeof(event.seq) = 'integer'
          AND event.seq > 1
          AND event.prev_event_hash = prior_global.event_hash
          AND prior_global.event_hash IS NOT NULL
          AND prior_process.run_id = NEW.run_id
          AND prior_process.event_type = CASE
                  WHEN NEW.state IN ('started', 'spawn_failed')
                    THEN 'agent_process_spawn_intent_recorded'
                  ELSE 'agent_process_started'
              END
          AND json_type(event.details_json, '$') = 'object'
          AND (SELECT COUNT(*) FROM json_each(event.details_json)) = 10
          AND json_type(event.details_json, '$.schema_version') = 'text'
          AND json_extract(event.details_json, '$.schema_version')
                = event.schema_version
          AND json_type(event.details_json, '$.occurred_at') = 'text'
          AND json_extract(event.details_json, '$.occurred_at')
                = event.created_at
          AND json_type(event.details_json, '$.sequence') = 'integer'
          AND json_extract(event.details_json, '$.sequence') = event.seq
          AND json_type(event.details_json, '$.command_id') = 'null'
          AND json_type(event.details_json, '$.correlation_id') = 'null'
          AND json_type(event.details_json, '$.actor') = 'text'
          AND json_extract(event.details_json, '$.actor') = event.actor
          AND json_type(event.details_json, '$.payload_hash') = 'text'
          AND json_extract(event.details_json, '$.payload_hash')
                = event.payload_hash
          AND json_type(event.details_json, '$.event_hash') = 'text'
          AND json_extract(event.details_json, '$.event_hash')
                = event.event_hash
          AND json_type(event.details_json, '$.prev_event_hash') = 'text'
          AND json_extract(event.details_json, '$.prev_event_hash')
                = event.prev_event_hash
          AND json_type(event.details_json, '$.payload') = 'object'
          AND (SELECT COUNT(*)
               FROM json_each(event.details_json, '$.payload')) = CASE NEW.state
                  WHEN 'spawn_failed' THEN 9
                  ELSE 11
              END
          AND json_type(
                event.details_json, '$.payload.processInstanceId') = 'text'
          AND json_extract(
                event.details_json, '$.payload.processInstanceId')
                = NEW.process_instance_id
          AND json_type(event.details_json, '$.payload.attemptId') = 'text'
          AND json_extract(event.details_json, '$.payload.attemptId')
                = NEW.attempt_id
          AND json_type(
                event.details_json, '$.payload.leaseGeneration') = 'integer'
          AND json_extract(
                event.details_json, '$.payload.leaseGeneration')
                = NEW.lease_generation
          AND json_type(event.details_json, '$.payload.processKind') = 'text'
          AND json_extract(event.details_json, '$.payload.processKind')
                = NEW.process_kind
          AND json_type(
                event.details_json, '$.payload.processOrdinal') = 'integer'
          AND json_extract(
                event.details_json, '$.payload.processOrdinal')
                = NEW.process_ordinal
          AND json_type(
                event.details_json, '$.payload.launchSpecHash') = 'text'
          AND json_extract(
                event.details_json, '$.payload.launchSpecHash')
                = NEW.launch_spec_hash
          AND json_type(
                event.details_json, '$.payload.priorProcessEventId') = 'text'
          AND json_extract(
                event.details_json, '$.payload.priorProcessEventId')
                = prior_process.event_id
          AND json_type(
                event.details_json, '$.payload.priorProcessEventHash') = 'text'
          AND json_extract(
                event.details_json, '$.payload.priorProcessEventHash')
                = prior_process.event_hash
          AND (
              NEW.state = 'started'
              OR {AGENT_PROCESS_LIFECYCLE_REASON_SQL_PREDICATE}
          )
          AND CASE NEW.state
              WHEN 'started' THEN
                  NEW.process_group_id = NEW.process_pid
                  AND json_type(event.details_json, '$.payload.processPid')
                        = 'integer'
                  AND json_extract(event.details_json, '$.payload.processPid')
                        = NEW.process_pid
                  AND json_type(
                        event.details_json, '$.payload.processGroupId')
                        = 'integer'
                  AND json_extract(
                        event.details_json, '$.payload.processGroupId')
                        = NEW.process_group_id
                  AND json_type(
                        event.details_json,
                        '$.payload.processIncarnationHash') = 'text'
                  AND json_extract(
                        event.details_json,
                        '$.payload.processIncarnationHash')
                        = NEW.process_incarnation_hash
                  -- SQLite validates the exact evidence shape here. The
                  -- application read model separately recomputes the
                  -- incarnation SHA-256 because SQLite has no SHA primitive.
                  AND json_valid(NEW.process_incarnation_json)
                  AND json_type(NEW.process_incarnation_json, '$') = 'object'
                  AND (
                      (
                          (SELECT COUNT(*)
                           FROM json_each(NEW.process_incarnation_json)) = 5
                          AND json_type(
                                NEW.process_incarnation_json,
                                '$.schemaVersion') = 'text'
                          AND json_extract(
                                NEW.process_incarnation_json,
                                '$.schemaVersion')
                                = 'h2ometa.linux-process-incarnation.v1'
                          AND json_type(
                                NEW.process_incarnation_json,
                                '$.evidenceProfile') = 'text'
                          AND json_extract(
                                NEW.process_incarnation_json,
                                '$.evidenceProfile')
                                = 'linux-procfs-boot-id-pid-starttime-v1'
                          AND json_type(
                                NEW.process_incarnation_json,
                                '$.pid') = 'integer'
                          AND json_extract(
                                NEW.process_incarnation_json,
                                '$.pid') = NEW.process_pid
                          AND json_type(
                                NEW.process_incarnation_json,
                                '$.procStartTicks') = 'integer'
                          AND json_extract(
                                NEW.process_incarnation_json,
                                '$.procStartTicks') > 0
                          AND json_type(
                                NEW.process_incarnation_json,
                                '$.bootId') = 'text'
                          AND length(json_extract(
                                NEW.process_incarnation_json,
                                '$.bootId')) = 36
                          AND substr(json_extract(
                                NEW.process_incarnation_json,
                                '$.bootId'), 9, 1) = '-'
                          AND substr(json_extract(
                                NEW.process_incarnation_json,
                                '$.bootId'), 14, 1) = '-'
                          AND substr(json_extract(
                                NEW.process_incarnation_json,
                                '$.bootId'), 19, 1) = '-'
                          AND substr(json_extract(
                                NEW.process_incarnation_json,
                                '$.bootId'), 24, 1) = '-'
                          AND length(replace(json_extract(
                                NEW.process_incarnation_json,
                                '$.bootId'), '-', '')) = 32
                          AND replace(json_extract(
                                NEW.process_incarnation_json,
                                '$.bootId'), '-', '')
                                NOT GLOB '*[^0-9a-f]*'
                      )
                      OR (
                          (SELECT COUNT(*)
                           FROM json_each(NEW.process_incarnation_json)) = 4
                          AND json_type(
                                NEW.process_incarnation_json,
                                '$.schemaVersion') = 'text'
                          AND json_extract(
                                NEW.process_incarnation_json,
                                '$.schemaVersion')
                                = 'h2ometa.windows-process-incarnation.v1'
                          AND json_type(
                                NEW.process_incarnation_json,
                                '$.evidenceProfile') = 'text'
                          AND json_extract(
                                NEW.process_incarnation_json,
                                '$.evidenceProfile')
                                = 'windows-process-pid-creation-filetime-v1'
                          AND json_type(
                                NEW.process_incarnation_json,
                                '$.pid') = 'integer'
                          AND json_extract(
                                NEW.process_incarnation_json,
                                '$.pid') = NEW.process_pid
                          AND json_type(
                                NEW.process_incarnation_json,
                                '$.creationTimeFiletime') = 'text'
                          AND length(json_extract(
                                NEW.process_incarnation_json,
                                '$.creationTimeFiletime')) BETWEEN 1 AND 20
                          AND substr(json_extract(
                                NEW.process_incarnation_json,
                                '$.creationTimeFiletime'), 1, 1) GLOB '[1-9]'
                          AND json_extract(
                                NEW.process_incarnation_json,
                                '$.creationTimeFiletime')
                                NOT GLOB '*[^0-9]*'
                          AND (
                              length(json_extract(
                                    NEW.process_incarnation_json,
                                    '$.creationTimeFiletime')) < 20
                              OR json_extract(
                                    NEW.process_incarnation_json,
                                    '$.creationTimeFiletime')
                                    <= '18446744073709551615' COLLATE BINARY
                          )
                      )
                  )
              WHEN 'spawn_failed' THEN
                  json_type(event.details_json, '$.payload.failureCode') = 'text'
                  AND json_extract(event.details_json, '$.payload.failureCode')
                        = NEW.exit_reason
              WHEN 'exited' THEN
                  json_type(
                        event.details_json,
                        '$.payload.processIncarnationHash') = 'text'
                  AND json_extract(
                        event.details_json,
                        '$.payload.processIncarnationHash')
                        = NEW.process_incarnation_hash
                  AND json_type(event.details_json, '$.payload.exitCode')
                        = 'integer'
                  AND json_extract(event.details_json, '$.payload.exitCode')
                        = NEW.exit_code
                  AND json_type(event.details_json, '$.payload.exitReason')
                        = 'text'
                  AND json_extract(event.details_json, '$.payload.exitReason')
                        = NEW.exit_reason
              WHEN 'terminated' THEN
                  json_type(
                        event.details_json,
                        '$.payload.processIncarnationHash') = 'text'
                  AND json_extract(
                        event.details_json,
                        '$.payload.processIncarnationHash')
                        = NEW.process_incarnation_hash
                  AND json_type(event.details_json, '$.payload.exitReason')
                        = 'text'
                  AND json_extract(event.details_json, '$.payload.exitReason')
                        = NEW.exit_reason
                  AND json_type(event.details_json, '$.payload.evidenceHash')
                        = 'text'
                  AND length(json_extract(
                        event.details_json, '$.payload.evidenceHash')) = 64
                  AND json_extract(
                        event.details_json, '$.payload.evidenceHash')
                        NOT GLOB '*[^0-9a-f]*'
              WHEN 'lost' THEN
                  json_type(
                        event.details_json,
                        '$.payload.processIncarnationHash') = 'text'
                  AND json_extract(
                        event.details_json,
                        '$.payload.processIncarnationHash')
                        = NEW.process_incarnation_hash
                  AND json_type(event.details_json, '$.payload.exitReason')
                        = 'text'
                  AND json_extract(event.details_json, '$.payload.exitReason')
                        = NEW.exit_reason
                  AND json_type(event.details_json, '$.payload.evidenceHash')
                        = 'text'
                  AND length(json_extract(
                        event.details_json, '$.payload.evidenceHash')) = 64
                  AND json_extract(
                        event.details_json, '$.payload.evidenceHash')
                        NOT GLOB '*[^0-9a-f]*'
              ELSE 0
          END
    )
    BEGIN
        SELECT RAISE(
            ABORT, 'AGENT_PROCESS_INSTANCE_LIFECYCLE_EVENT_INVALID');
    END
    """

AGENT_PROCESS_INSTANCE_V23_SCHEMA_SQL = (
    f"{AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_STATEMENT.strip()};"
)


def ensure_agent_process_instance_v23_schema(
    connection: sqlite3.Connection,
) -> None:
    """Create the additive exact lifecycle trigger for a fresh V23 DB."""

    connection.execute(AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_STATEMENT)


def assert_agent_process_instance_v23_schema(
    connection: sqlite3.Connection,
) -> None:
    """Require the V22 process schema plus the exact V23 trigger."""

    assert_agent_process_instance_schema(
        connection,
        schema_version=22,
        additional_trigger_names=(AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME,),
    )
    row = connection.execute(
        "SELECT type, sql FROM sqlite_master WHERE name = ?",
        (AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME,),
    ).fetchone()
    expected = " ".join(
        AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_STATEMENT.replace(
            "IF NOT EXISTS", ""
        ).split()
    ).casefold()
    if (
        row is None
        or str(row[0]) != "trigger"
        or row[1] is None
        or " ".join(str(row[1]).split()).casefold() != expected
    ):
        raise RuntimeError(
            f"{AGENT_PROCESS_LIFECYCLE_SCHEMA_SIGNATURE_MISMATCH}: trigger"
        )


def upgrade_agent_process_instance_schema_to_v23(
    connection: sqlite3.Connection,
) -> None:
    """Add lifecycle enforcement without accepting legacy lifecycle rows."""

    collision = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = ? LIMIT 1",
        (AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME,),
    ).fetchone()
    if collision is not None:
        raise RuntimeError(AGENT_PROCESS_LIFECYCLE_SCHEMA_NAMESPACE_COLLISION)
    unsupported = connection.execute(
        "SELECT 1 FROM agent_process_instances WHERE state <> 'prepared' LIMIT 1"
    ).fetchone()
    if unsupported is not None:
        raise RuntimeError(AGENT_PROCESS_LIFECYCLE_MIGRATION_STATE_UNSUPPORTED)
    ensure_agent_process_instance_v23_schema(connection)
    assert_agent_process_instance_v23_schema(connection)


__all__ = [
    "AGENT_PROCESS_INSTANCE_V23_SCHEMA_SQL",
    "AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_NAME",
    "AGENT_PROCESS_LIFECYCLE_EXACT_TRIGGER_STATEMENT",
    "AGENT_PROCESS_LIFECYCLE_MIGRATION_STATE_UNSUPPORTED",
    "AGENT_PROCESS_LIFECYCLE_SCHEMA_NAMESPACE_COLLISION",
    "AGENT_PROCESS_LIFECYCLE_SCHEMA_SIGNATURE_MISMATCH",
    "assert_agent_process_instance_v23_schema",
    "ensure_agent_process_instance_v23_schema",
    "upgrade_agent_process_instance_schema_to_v23",
]
