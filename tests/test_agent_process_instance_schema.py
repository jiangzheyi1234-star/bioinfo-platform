from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.remote_runner import agent_process_instance_schema
from apps.remote_runner.agent_process_instance_schema import (
    AGENT_PROCESS_INSTANCE_SCHEMA_NAMESPACE_COLLISION,
    AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH,
    assert_agent_process_instance_schema,
    migrate_agent_process_instance_schema,
)
from apps.remote_runner.agent_schema_migration_guard import (
    AGENT_SCHEMA_MIGRATION_PRECONDITION_INVALID,
)
from apps.remote_runner.agent_workspace_proof_schema import (
    AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH,
)
from apps.remote_runner.sqlite_migrations import initialize_or_migrate_runtime_db
from tests.agent_process_instance_schema_fixtures import (
    TIMESTAMP,
    append_process_event,
    connection,
    digest,
    downgrade_process_schema,
    finish,
    foreign_keys,
    insert_prepared,
    lifecycle_payload,
    record_migration,
    seed_intent,
    start,
    unique_column_sets,
)
from tests.helpers.reference_database import make_remote_runner_config


def _initialized_path(tmp_path: Path) -> Path:
    cfg = make_remote_runner_config(tmp_path)
    initialize_or_migrate_runtime_db(cfg.db_path)
    return Path(cfg.db_path)


def test_process_readiness_rejects_extra_side_effect_trigger(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        db.execute(
            "CREATE TRIGGER forged_process_side_effect "
            "AFTER INSERT ON agent_process_instances BEGIN SELECT 1; END"
        )
        with pytest.raises(
            RuntimeError,
            match=(
                rf"^{AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH}: "
                r"triggers:agent_process_instances$"
            ),
        ):
            assert_agent_process_instance_schema(db)


def test_additive_migration_records_v21_and_exact_schema(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    downgrade_process_schema(path)

    with connection(path) as db:
        migrate_agent_process_instance_schema(db, record_migration=record_migration)
        assert_agent_process_instance_schema(db, schema_version=21)
        version = db.execute("PRAGMA user_version").fetchone()[0]
        ledger = db.execute(
            "SELECT name FROM schema_migrations WHERE version = 21"
        ).fetchone()
        indexes = {
            str(row[0])
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND name LIKE 'idx_agent_process_instances_%'"
            )
        }
        fks = foreign_keys(db)
        uniques = unique_column_sets(db)

    assert version == 21
    assert tuple(ledger) == ("021_agent_process_instance",)
    assert indexes == {
        "idx_agent_process_instances_attempt_state",
        "idx_agent_process_instances_incarnation_hash",
        "idx_agent_process_instances_run_ordinal",
        "idx_agent_process_instances_state_started",
    }
    assert uniques == {
        ("attempt_id", "lease_generation", "process_ordinal"),
        ("gate_token_hash",),
        ("launch_intent_hash",),
        ("spawn_intent_event_id",),
        ("started_event_id",),
        ("terminal_event_id",),
        ("workspace_proof_id",),
    }
    assert fks == {
        ("attempt_id", "run_attempts", "attempt_id", "RESTRICT"),
        (
            "authorization_id",
            "agent_run_authorizations",
            "authorization_id",
            "RESTRICT",
        ),
        ("run_id", "runs", "run_id", "RESTRICT"),
        ("spawn_intent_event_id", "run_events", "event_id", "RESTRICT"),
        ("started_event_id", "run_events", "event_id", "RESTRICT"),
        ("terminal_event_id", "run_events", "event_id", "RESTRICT"),
        (
            "workspace_proof_id",
            "agent_workspace_proofs",
            "workspace_proof_id",
            "RESTRICT",
        ),
    }


def test_migration_rolls_back_partial_schema_and_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _initialized_path(tmp_path)
    downgrade_process_schema(path)

    def fail_after_ddl(db: sqlite3.Connection, *, schema_version: int) -> None:
        assert schema_version == 21
        db.execute("CREATE TABLE agent_process_instances (value TEXT)")
        raise RuntimeError("forced process schema failure")

    monkeypatch.setattr(
        agent_process_instance_schema,
        "ensure_agent_process_instance_schema",
        fail_after_ddl,
    )
    with connection(path) as db:
        with pytest.raises(RuntimeError, match="forced process schema failure"):
            migrate_agent_process_instance_schema(db, record_migration=record_migration)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 20
        assert (
            db.execute("SELECT 1 FROM schema_migrations WHERE version = 21").fetchone()
            is None
        )
        assert (
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'agent_process_instances'"
            ).fetchone()
            is None
        )


def test_migration_requires_exact_v20_workspace_proof_schema(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    downgrade_process_schema(path)
    with connection(path) as db:
        db.execute("DROP INDEX idx_agent_workspace_proofs_authorization")
        with pytest.raises(
            RuntimeError,
            match=AGENT_WORKSPACE_PROOF_SCHEMA_SIGNATURE_MISMATCH,
        ):
            migrate_agent_process_instance_schema(db, record_migration=record_migration)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 20
        assert (
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'agent_process_instances'"
            ).fetchone()
            is None
        )


@pytest.mark.parametrize(
    ("mutation", "component"),
    [
        ("missing", "prior-ledger"),
        ("wrong_name", "prior-ledger"),
        ("bad_checksum", "prior-ledger"),
        ("target", "target-ledger"),
    ],
)
def test_migration_requires_credible_v20_ledger_and_no_v21_entry(
    tmp_path: Path,
    mutation: str,
    component: str,
) -> None:
    path = _initialized_path(tmp_path)
    downgrade_process_schema(path)
    with connection(path) as db:
        if mutation == "missing":
            db.execute("DELETE FROM schema_migrations WHERE version = 20")
        elif mutation == "wrong_name":
            db.execute("UPDATE schema_migrations SET name = 'wrong' WHERE version = 20")
        elif mutation == "bad_checksum":
            db.execute(
                "UPDATE schema_migrations SET checksum = 'bad' WHERE version = 20"
            )
        else:
            db.execute(
                "INSERT INTO schema_migrations VALUES (21, ?, ?, ?)",
                ("021_agent_process_instance", digest("target"), TIMESTAMP),
            )
        db.commit()
        with pytest.raises(
            RuntimeError,
            match=rf"{AGENT_SCHEMA_MIGRATION_PRECONDITION_INVALID}: {component}",
        ):
            migrate_agent_process_instance_schema(
                db,
                record_migration=record_migration,
            )
        assert db.execute("PRAGMA user_version").fetchone()[0] == 20
        assert (
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'agent_process_instances'"
            ).fetchone()
            is None
        )


def test_migration_rejects_prefilled_v21_namespace_atomically(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    downgrade_process_schema(path)
    with connection(path) as db:
        db.execute("CREATE TABLE agent_process_instances (marker TEXT NOT NULL)")
        db.execute("INSERT INTO agent_process_instances VALUES ('prefilled')")
        db.commit()
        with pytest.raises(
            RuntimeError,
            match=(
                rf"{AGENT_PROCESS_INSTANCE_SCHEMA_NAMESPACE_COLLISION}: "
                "table:agent_process_instances"
            ),
        ):
            migrate_agent_process_instance_schema(db, record_migration=record_migration)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 20
        assert tuple(
            db.execute("SELECT marker FROM agent_process_instances").fetchone()
        ) == ("prefilled",)
        assert (
            db.execute("SELECT 1 FROM schema_migrations WHERE version = 21").fetchone()
            is None
        )


def test_schema_assertion_rejects_wrong_partial_unique_index(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        db.execute("DROP INDEX idx_agent_process_instances_incarnation_hash")
        db.execute(
            "CREATE UNIQUE INDEX idx_agent_process_instances_incarnation_hash "
            "ON agent_process_instances(process_incarnation_hash)"
        )
        with pytest.raises(
            RuntimeError,
            match=(
                rf"{AGENT_PROCESS_INSTANCE_SCHEMA_SIGNATURE_MISMATCH}: "
                "object-sql:idx_agent_process_instances_incarnation_hash"
            ),
        ):
            assert_agent_process_instance_schema(db)


@pytest.mark.parametrize(
    ("process_kind", "ordinal", "boundary"),
    [("dry_run", 1, "pre_dry_run"), ("run", 2, "pre_run")],
)
def test_prepared_intent_binds_real_spawn_event_wrapper(
    tmp_path: Path,
    process_kind: str,
    ordinal: int,
    boundary: str,
) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        intent = seed_intent(
            db,
            tag=process_kind,
            process_kind=process_kind,
            process_ordinal=ordinal,
            proof_boundary=boundary,
        )
        insert_prepared(db, intent)
        event = db.execute(
            "SELECT * FROM run_events WHERE event_id = ?",
            (intent["spawn_event_id"],),
        ).fetchone()
        row = db.execute(
            "SELECT * FROM agent_process_instances WHERE process_instance_id = ?",
            (intent["process_instance_id"],),
        ).fetchone()

    assert row["state"] == "prepared"
    assert row["spawn_intent_event_hash"] == event["event_hash"]
    assert event["event_type"] == "agent_process_spawn_intent_recorded"
    assert "processInstanceId" not in str(event["details_json"])


@pytest.mark.parametrize(
    "mutation",
    ["event_type", "event_hash", "payload", "payload_hash", "blob_json"],
)
def test_spawn_event_tampering_is_rejected(tmp_path: Path, mutation: str) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        intent = seed_intent(db, tag=mutation)
        event_id = intent["spawn_event_id"]
        if mutation == "event_type":
            db.execute(
                "UPDATE run_events SET event_type = 'wrong' WHERE event_id = ?",
                (event_id,),
            )
        elif mutation == "event_hash":
            db.execute(
                "UPDATE run_events SET event_hash = ? WHERE event_id = ?",
                (digest("wrong"), event_id),
            )
        elif mutation == "payload":
            db.execute(
                "UPDATE run_events SET details_json = json_set(details_json, "
                "'$.payload.attemptId', 'wrong') WHERE event_id = ?",
                (event_id,),
            )
        elif mutation == "payload_hash":
            db.execute(
                "UPDATE run_events SET payload_hash = upper(payload_hash) WHERE event_id = ?",
                (event_id,),
            )
        else:
            db.execute(
                "UPDATE run_events SET details_json = CAST(details_json AS BLOB) WHERE event_id = ?",
                (event_id,),
            )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="AGENT_PROCESS_INSTANCE_SPAWN_EVENT_INVALID",
        ):
            insert_prepared(db, intent)


@pytest.mark.parametrize("state", ["exited", "terminated", "lost"])
def test_real_started_and_terminal_events_follow_mapping(
    tmp_path: Path,
    state: str,
) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        intent = seed_intent(db, tag=state)
        insert_prepared(db, intent)
        started = start(db, intent)
        terminal = finish(db, intent, state=state)
        row = db.execute(
            "SELECT * FROM agent_process_instances WHERE process_instance_id = ?",
            (intent["process_instance_id"],),
        ).fetchone()
        sequences = db.execute(
            "SELECT seq FROM run_events WHERE event_id IN (?, ?) ORDER BY seq",
            (started["eventId"], terminal["eventId"]),
        ).fetchall()

    assert row["state"] == state
    assert row["exit_code"] == (0 if state == "exited" else None)
    assert [item[0] for item in sequences] == [2, 3]


def test_spawn_failed_event_closes_without_process_identity(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        intent = seed_intent(db, tag="spawn_failed")
        insert_prepared(db, intent)
        finish(db, intent, state="spawn_failed")
        row = db.execute(
            "SELECT * FROM agent_process_instances WHERE process_instance_id = ?",
            (intent["process_instance_id"],),
        ).fetchone()
    assert row["state"] == "spawn_failed"
    assert row["process_pid"] is None
    assert row["exit_code"] is None


def test_lifecycle_event_type_payload_and_sequence_are_exact(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        wrong_type = seed_intent(db, tag="wrong_type")
        insert_prepared(db, wrong_type)
        event = append_process_event(db, wrong_type, event_type="agent_process_lost")
        with pytest.raises(
            sqlite3.IntegrityError,
            match="AGENT_PROCESS_INSTANCE_LIFECYCLE_EVENT_INVALID",
        ):
            start(db, wrong_type, event=event)

        wrong_payload = seed_intent(db, tag="wrong_payload")
        insert_prepared(db, wrong_payload)
        payload = lifecycle_payload(wrong_payload) | {"attemptId": "wrong"}
        event = append_process_event(
            db, wrong_payload, event_type="agent_process_started", payload=payload
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="AGENT_PROCESS_INSTANCE_LIFECYCLE_EVENT_INVALID",
        ):
            start(db, wrong_payload, event=event)

        wrong_seq = seed_intent(db, tag="wrong_seq")
        insert_prepared(db, wrong_seq)
        early_terminal = append_process_event(
            db, wrong_seq, event_type="agent_process_exited"
        )
        start(db, wrong_seq)
        with pytest.raises(
            sqlite3.IntegrityError,
            match="AGENT_PROCESS_INSTANCE_LIFECYCLE_EVENT_INVALID",
        ):
            finish(db, wrong_seq, state="exited", event=early_terminal)


def test_referenced_run_events_are_immutable(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        intent = seed_intent(db, tag="immutable")
        insert_prepared(db, intent)
        started = start(db, intent)
        terminal = finish(db, intent, state="exited")
        event_ids = [intent["spawn_event_id"], started["eventId"], terminal["eventId"]]
        for event_id in event_ids:
            with pytest.raises(sqlite3.IntegrityError, match="EVENT_IMMUTABLE"):
                db.execute(
                    "UPDATE run_events SET message = 'tampered' WHERE event_id = ?",
                    (event_id,),
                )
            with pytest.raises(sqlite3.IntegrityError, match="EVENT_IMMUTABLE"):
                db.execute("DELETE FROM run_events WHERE event_id = ?", (event_id,))


def test_event_roles_are_globally_non_reusable(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        first = seed_intent(db, tag="role_first")
        second = seed_intent(db, tag="role_second")
        insert_prepared(db, first)
        insert_prepared(db, second)
        started = start(db, first)
        for reused in (first["spawn_event_id"], started["eventId"]):
            with pytest.raises(sqlite3.IntegrityError):
                start(db, second, event={"eventId": reused})
        state = db.execute(
            "SELECT state FROM agent_process_instances WHERE process_instance_id = ?",
            (second["process_instance_id"],),
        ).fetchone()[0]
    assert state == "prepared"


def test_gate_token_and_incarnation_hash_are_globally_unique(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        shared_gate = digest("shared-gate")
        gate_a = seed_intent(db, tag="gate_a", gate_token_hash=shared_gate)
        gate_b = seed_intent(db, tag="gate_b", gate_token_hash=shared_gate)
        insert_prepared(db, gate_a)
        with pytest.raises(sqlite3.IntegrityError, match="gate_token_hash"):
            insert_prepared(db, gate_b)

        process_a = seed_intent(db, tag="process_a")
        process_b = seed_intent(db, tag="process_b")
        insert_prepared(db, process_a)
        insert_prepared(db, process_b)
        incarnation_hash = digest("shared-incarnation")
        start(db, process_a, incarnation_hash=incarnation_hash)
        with pytest.raises(sqlite3.IntegrityError, match="process_incarnation_hash"):
            start(db, process_b, incarnation_hash=incarnation_hash)


def test_logical_activity_is_globally_unique_in_v22(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        first = seed_intent(db, tag="logical_unique_first")
        second = seed_intent(db, tag="logical_unique_second")
        insert_prepared(db, first, logical_activity_id="retry-stable-activity")
        with pytest.raises(sqlite3.IntegrityError, match="logical_activity_id"):
            insert_prepared(db, second, logical_activity_id="retry-stable-activity")


def test_blob_values_cannot_bypass_text_and_json_contracts(tmp_path: Path) -> None:
    path = _initialized_path(tmp_path)
    with connection(path) as db:
        id_blob = seed_intent(db, tag="id_blob")
        with pytest.raises(sqlite3.IntegrityError):
            insert_prepared(
                db, id_blob, process_instance_id=sqlite3.Binary(b"process_blob")
            )

        hash_blob = seed_intent(db, tag="hash_blob")
        with pytest.raises(sqlite3.IntegrityError):
            insert_prepared(db, hash_blob, launch_intent_hash=sqlite3.Binary(b"a" * 64))

        timestamp_blob = seed_intent(db, tag="timestamp_blob")
        with pytest.raises(sqlite3.IntegrityError):
            insert_prepared(
                db, timestamp_blob, prepared_at=sqlite3.Binary(TIMESTAMP.encode())
            )

        incarnation_blob = seed_intent(db, tag="incarnation_blob")
        insert_prepared(db, incarnation_blob)
        with pytest.raises(sqlite3.IntegrityError):
            start(db, incarnation_blob, incarnation_json=sqlite3.Binary(b"{}"))
