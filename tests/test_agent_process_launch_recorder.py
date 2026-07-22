from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import dataclasses
import hashlib
import json
import sqlite3
import stat
from pathlib import Path
import threading

import pytest

from apps.remote_runner import agent_process_launch_recorder as recorder
from apps.remote_runner.agent_process_launch_recorder import (
    AgentProcessLaunchPreparationError,
    agent_process_gate_token_hash,
    prepare_agent_process_launch,
)
from apps.remote_runner.agent_workspace_manifest import (
    AgentGenerationBundleManifest,
    seal_agent_generation_bundle,
)
from apps.remote_runner.event_contracts import (
    append_run_event_v2,
    verify_run_event_hash_chain,
)
from apps.remote_runner.storage_core import get_connection
from core.contracts.agent_process_launch_spec import agent_process_launch_spec_hash
from core.contracts.agent_workspace_proof import (
    AgentWorkspaceManifestEntryV1,
    agent_workspace_manifest_hash,
    agent_workspace_tool_assets_hash,
)
from tests.agent_process_launch_recorder_fixtures import (
    ATTEMPT_ID,
    LEASE_GENERATION,
    RUN_ID,
    SeededRecorderContext,
    build_recorder_launch_command,
    seed_recorder_context,
)


GATE_TOKEN = bytes(range(32))
PREPARED_AT = "2099-06-07T10:00:01Z"


@pytest.fixture
def context(tmp_path: Path) -> SeededRecorderContext:
    return seed_recorder_context(tmp_path)


@pytest.fixture(autouse=True)
def deterministic_secret_and_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recorder.secrets, "token_bytes", lambda size: GATE_TOKEN)
    monkeypatch.setattr(recorder, "now_iso", lambda: PREPARED_AT)


def _prepare(context: SeededRecorderContext):
    return _prepare_with_workspace(context)


def _prepare_with_workspace(
    context: SeededRecorderContext,
    *,
    workdir: Path | None = None,
    manifest: AgentGenerationBundleManifest | None = None,
    environment_marker: str = "default",
):
    effective_workdir = context.workdir if workdir is None else workdir
    return prepare_agent_process_launch(
        context.cfg,
        expected_authorization=context.authorization,
        run_id=RUN_ID,
        attempt_id=ATTEMPT_ID,
        lease_generation=LEASE_GENERATION,
        launch_command=build_recorder_launch_command(
            effective_workdir,
            environment_marker=environment_marker,
        ),
        managed_workdir=effective_workdir,
        sealed_manifest=context.manifest if manifest is None else manifest,
    )


def _table_counts(context: SeededRecorderContext) -> dict[str, int]:
    connection = get_connection(context.cfg)
    try:
        return {
            "proofs": connection.execute(
                "SELECT COUNT(*) FROM agent_workspace_proofs"
            ).fetchone()[0],
            "processes": connection.execute(
                "SELECT COUNT(*) FROM agent_process_instances"
            ).fetchone()[0],
            "spawn_events": connection.execute(
                "SELECT COUNT(*) FROM run_events "
                "WHERE event_type = 'agent_process_spawn_intent_recorded'"
            ).fetchone()[0],
        }
    finally:
        connection.close()


def _assert_manifest_failure(
    context: SeededRecorderContext,
    *,
    workdir: Path | None = None,
    manifest: AgentGenerationBundleManifest | None = None,
) -> AgentProcessLaunchPreparationError:
    before = _table_counts(context)
    with pytest.raises(
        AgentProcessLaunchPreparationError,
        match="AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: manifest",
    ) as raised:
        _prepare_with_workspace(context, workdir=workdir, manifest=manifest)
    assert _table_counts(context) == before
    return raised.value


def _enable_owner_write(path: Path) -> None:
    path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)


def test_prepare_atomically_binds_proof_event_intent_and_keeps_secret_memory_only(
    context: SeededRecorderContext,
) -> None:
    environment_marker = "sk-live-" + "q" * 40
    prepared = _prepare_with_workspace(
        context,
        environment_marker=environment_marker,
    )

    assert prepared.gate_token == GATE_TOKEN
    assert prepared.process_intent.gateTokenHash == agent_process_gate_token_hash(
        GATE_TOKEN
    )
    assert (
        prepared.process_intent.gateTokenHash != hashlib.sha256(GATE_TOKEN).hexdigest()
    )
    assert prepared.workspace_proof.toolAssetsHash == agent_workspace_tool_assets_hash(
        context.manifest.entries
    )
    assert prepared.process_intent.workspaceProofId == (
        prepared.workspace_proof.workspaceProofId
    )
    assert prepared.process_intent.spawnIntentEventId == prepared.spawn_event["eventId"]
    assert (
        prepared.process_intent.spawnIntentEventHash
        == prepared.spawn_event["event_hash"]
    )
    assert prepared.process_intent.launchSpecHash == prepared.launch_spec.launchSpecHash
    assert prepared.launch_spec.launchSpecHash == agent_process_launch_spec_hash(
        prepared.launch_spec,
        hash_key=GATE_TOKEN,
    )
    assert prepared.launch_spec.serverBindings.workspaceProofId == (
        prepared.workspace_proof.workspaceProofId
    )
    assert prepared.launch_spec.serverBindings.workspaceProofHash == (
        prepared.workspace_proof.proofHash
    )
    assert prepared.launch_spec.serverBindings.runtimeLockHash == (
        context.authorization.runtime_lock_hash
    )
    assert prepared.launch_spec.serverBindings.runtimeProofHash == (
        context.authorization.runtime_proof_hash
    )
    assert "processInstanceId" not in prepared.spawn_event["payload"]
    assert _table_counts(context) == {
        "proofs": 1,
        "processes": 1,
        "spawn_events": 1,
    }

    connection = get_connection(context.cfg)
    try:
        process = connection.execute("SELECT * FROM agent_process_instances").fetchone()
        assert process["state"] == "prepared"
        assert all(
            process[field] is None
            for field in (
                "process_pid",
                "process_group_id",
                "process_incarnation_json",
                "process_incarnation_hash",
                "started_event_id",
                "terminal_event_id",
                "exit_code",
                "exit_reason",
                "started_at",
                "finished_at",
            )
        )
        dump = "\n".join(connection.iterdump())
        assert GATE_TOKEN.hex() not in dump.casefold()
        assert base64.b64encode(GATE_TOKEN).decode("ascii") not in dump
        assert "H2OMETA_TEST_BOUND" not in dump
        assert environment_marker not in dump
        assert verify_run_event_hash_chain(connection, RUN_ID) == {
            "valid": True,
            "checked": 3,
            "reason": None,
        }
    finally:
        connection.close()
    persisted_encodings = (
        GATE_TOKEN,
        GATE_TOKEN.hex().encode("ascii"),
        GATE_TOKEN.hex().upper().encode("ascii"),
        base64.b64encode(GATE_TOKEN),
        repr(GATE_TOKEN).encode("utf-8"),
    )
    database = Path(context.cfg.db_path)
    for path in database.parent.glob(f"{database.name}*"):
        if path.is_file():
            payload = path.read_bytes()
            assert all(encoding not in payload for encoding in persisted_encodings)
    assert GATE_TOKEN.hex() not in repr(prepared)
    assert repr(GATE_TOKEN) not in repr(prepared)
    assert environment_marker not in repr(prepared)


def test_second_preparation_never_reissues_a_gate_token(
    context: SeededRecorderContext,
) -> None:
    first = _prepare(context)

    with pytest.raises(
        AgentProcessLaunchPreparationError,
        match="AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: replay",
    ):
        _prepare(context)

    assert first.gate_token == GATE_TOKEN
    assert _table_counts(context) == {
        "proofs": 1,
        "processes": 1,
        "spawn_events": 1,
    }


def test_cross_lease_preparation_is_blocked_until_logical_activity_reconciles(
    context: SeededRecorderContext,
) -> None:
    first = _prepare(context)
    connection = get_connection(context.cfg)
    try:
        connection.execute(
            "UPDATE run_attempts SET lease_generation = 2 WHERE attempt_id = ?",
            (ATTEMPT_ID,),
        )
        connection.execute(
            "UPDATE run_leases SET lease_generation = 2 WHERE run_id = ?",
            (RUN_ID,),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        AgentProcessLaunchPreparationError,
        match="AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: replay",
    ):
        prepare_agent_process_launch(
            context.cfg,
            expected_authorization=context.authorization,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            lease_generation=2,
            launch_command=build_recorder_launch_command(context.workdir),
            managed_workdir=context.workdir,
            sealed_manifest=context.manifest,
        )

    assert first.process_intent.leaseGeneration == 1
    assert _table_counts(context) == {
        "proofs": 1,
        "processes": 1,
        "spawn_events": 1,
    }


def test_concurrent_prepare_returns_one_gate_token_and_one_replay(
    context: SeededRecorderContext,
) -> None:
    ready = threading.Barrier(2)

    def prepare_once() -> tuple[str, object]:
        ready.wait(timeout=10)
        try:
            return "prepared", _prepare(context).gate_token
        except AgentProcessLaunchPreparationError as exc:
            return "rejected", exc.component

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: prepare_once(), range(2)))

    assert sorted(outcomes) == [
        ("prepared", GATE_TOKEN),
        ("rejected", "replay"),
    ]
    assert _table_counts(context) == {
        "proofs": 1,
        "processes": 1,
        "spawn_events": 1,
    }


def test_semantically_wrong_materialization_event_is_rejected_with_valid_chain(
    tmp_path: Path,
) -> None:
    context = seed_recorder_context(
        tmp_path,
        materialization_overrides={"authorizationId": "agrauth_wrong"},
    )
    connection = get_connection(context.cfg)
    try:
        assert verify_run_event_hash_chain(connection, RUN_ID)["valid"] is True
    finally:
        connection.close()

    with pytest.raises(
        AgentProcessLaunchPreparationError,
        match="AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: input_event",
    ):
        _prepare(context)
    assert _table_counts(context) == {
        "proofs": 0,
        "processes": 0,
        "spawn_events": 0,
    }


def test_caller_consistent_but_durable_input_authority_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    forged_hash = hashlib.sha256(b"caller-forged-input").hexdigest()
    context = seed_recorder_context(
        tmp_path,
        materialization_overrides={
            "inputs": [
                {
                    "uploadId": "upload-launch-recorder",
                    "filename": "reads.fastq",
                    "role": "reads",
                    "sha256": forged_hash,
                    "sizeBytes": len(b"caller-forged-input"),
                    "mimeType": "text/plain",
                }
            ]
        },
        verified_input_overrides={
            "sha256": forged_hash,
            "sizeBytes": len(b"caller-forged-input"),
        },
    )
    connection = get_connection(context.cfg)
    try:
        assert verify_run_event_hash_chain(connection, RUN_ID)["valid"] is True
    finally:
        connection.close()

    with pytest.raises(
        AgentProcessLaunchPreparationError,
        match="AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: input_event",
    ):
        _prepare(context)
    assert _table_counts(context) == {
        "proofs": 0,
        "processes": 0,
        "spawn_events": 0,
    }


@pytest.mark.parametrize("mutation", ["delete", "replace"])
def test_private_input_bytes_are_revalidated_before_gate_token_is_issued(
    context: SeededRecorderContext,
    mutation: str,
) -> None:
    private_input = Path(str(context.authorization.verified_inputs[0]["path"]))
    _enable_owner_write(private_input)
    if mutation == "delete":
        private_input.unlink()
    else:
        private_input.write_bytes(b"forged-input")
        private_input.chmod(0o400)

    with pytest.raises(
        AgentProcessLaunchPreparationError,
        match="AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: input_event",
    ):
        _prepare(context)
    assert _table_counts(context) == {
        "proofs": 0,
        "processes": 0,
        "spawn_events": 0,
    }


@pytest.mark.parametrize(
    ("mutation", "component"),
    [
        ("attempt_cancel", "cancellation"),
        ("run_cancel", "cancellation"),
        ("job_unclaimed", "storage"),
        ("lease_expired", "storage"),
        ("event_chain", "event_chain"),
        ("hidden_v2_sequence", "event_chain"),
        ("wrong_generation", "authority"),
        ("authority_drift", "authority"),
        ("run_spec_drift", "authority"),
        ("duplicate_input_event", "input_event"),
    ],
)
def test_authority_cancellation_lease_and_chain_fences_leave_zero_launch_writes(
    context: SeededRecorderContext,
    mutation: str,
    component: str,
) -> None:
    connection = get_connection(context.cfg)
    try:
        if mutation == "attempt_cancel":
            connection.execute(
                "UPDATE run_attempts SET cancel_requested_at = ? WHERE attempt_id = ?",
                (PREPARED_AT, ATTEMPT_ID),
            )
        elif mutation == "run_cancel":
            connection.execute(
                "UPDATE runs SET status = 'canceling' WHERE run_id = ?",
                (RUN_ID,),
            )
        elif mutation == "job_unclaimed":
            connection.execute(
                "UPDATE run_jobs SET state = 'available' WHERE run_id = ?",
                (RUN_ID,),
            )
        elif mutation == "lease_expired":
            connection.execute(
                "UPDATE run_leases SET expires_at = '2000-01-01T00:00:00Z' "
                "WHERE run_id = ?",
                (RUN_ID,),
            )
        elif mutation == "event_chain":
            connection.execute(
                "UPDATE run_events SET event_hash = ? WHERE run_id = ?",
                ("f" * 64, RUN_ID),
            )
        elif mutation == "hidden_v2_sequence":
            row = connection.execute(
                "SELECT event_id, details_json FROM run_events "
                "WHERE run_id = ? AND event_type = 'agent_input_materialized'",
                (RUN_ID,),
            ).fetchone()
            details = json.loads(row["details_json"])
            details["sequence"] = 0
            connection.execute(
                "UPDATE run_events SET seq = 0, details_json = ? WHERE event_id = ?",
                (
                    json.dumps(details, sort_keys=True, separators=(",", ":")),
                    row["event_id"],
                ),
            )
        elif mutation == "run_spec_drift":
            connection.execute(
                "UPDATE runs SET run_spec_json = ? WHERE run_id = ?",
                (json.dumps({"pipelineId": "tampered"}), RUN_ID),
            )
        elif mutation == "duplicate_input_event":
            row = connection.execute(
                "SELECT details_json FROM run_events "
                "WHERE run_id = ? AND event_type = 'agent_input_materialized'",
                (RUN_ID,),
            ).fetchone()
            append_run_event_v2(
                connection,
                run_id=RUN_ID,
                event_type="agent_input_materialized",
                stage="agent_input",
                state_version=2,
                message="Agent-authorized input materialized and verified.",
                request_id="request-agent-launch-recorder",
                payload=json.loads(row["details_json"])["payload"],
                occurred_at="2099-06-07T10:00:00.500000Z",
            )
        connection.commit()
    finally:
        connection.close()

    authorization = context.authorization
    generation = LEASE_GENERATION
    if mutation == "wrong_generation":
        generation += 1
    if mutation == "authority_drift":
        authorization = dataclasses.replace(
            authorization,
            runtime_lock_hash="e" * 64,
        )
    with pytest.raises(
        AgentProcessLaunchPreparationError,
        match=rf"AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: {component}",
    ):
        prepare_agent_process_launch(
            context.cfg,
            expected_authorization=authorization,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            lease_generation=generation,
            launch_command=build_recorder_launch_command(context.workdir),
            managed_workdir=context.workdir,
            sealed_manifest=context.manifest,
        )
    assert _table_counts(context) == {
        "proofs": 0,
        "processes": 0,
        "spawn_events": 0,
    }


@pytest.mark.parametrize("fault_point", ["proof", "event", "process"])
def test_fault_injection_rolls_back_all_three_launch_records(
    context: SeededRecorderContext,
    fault_point: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = {
        "proof": "agent_workspace_proofs",
        "event": "run_events",
        "process": "agent_process_instances",
    }[fault_point]
    when = (
        " WHEN NEW.event_type = 'agent_process_spawn_intent_recorded'"
        if fault_point == "event"
        else ""
    )
    real_ensure = recorder.ensure_runtime_schema_current

    def ensure_then_inject_fault(connection):
        real_ensure(connection)
        connection.execute(
            f"CREATE TRIGGER abort_{fault_point}_launch BEFORE INSERT ON {target}"
            f"{when} BEGIN SELECT RAISE(ABORT, 'forced launch fault'); END"
        )

    monkeypatch.setattr(
        recorder,
        "ensure_runtime_schema_current",
        ensure_then_inject_fault,
    )

    with pytest.raises(
        AgentProcessLaunchPreparationError,
        match="AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: storage",
    ):
        _prepare(context)

    assert _table_counts(context) == {
        "proofs": 0,
        "processes": 0,
        "spawn_events": 0,
    }
    connection = get_connection(context.cfg)
    try:
        assert verify_run_event_hash_chain(connection, RUN_ID) == {
            "valid": True,
            "checked": 2,
            "reason": None,
        }
    finally:
        connection.close()


def test_unsealed_bundle_is_rejected_atomically(
    context: SeededRecorderContext,
) -> None:
    snakefile = context.workdir / "workflow" / "Snakefile"
    _enable_owner_write(snakefile)

    _assert_manifest_failure(context)


def test_unmanifested_workdir_root_entry_is_rejected_atomically(
    context: SeededRecorderContext,
) -> None:
    (context.workdir / "mutable-runtime-config.yaml").write_text(
        "mode: attacker-controlled\n",
        encoding="utf-8",
    )

    _assert_manifest_failure(context)


def test_stale_manifest_is_rejected_after_bundle_is_changed_and_resealed(
    context: SeededRecorderContext,
) -> None:
    snakefile = context.workdir / "workflow" / "Snakefile"
    _enable_owner_write(snakefile)
    snakefile.write_text(
        'include: "rules/qc.smk"\n# changed after the original seal\n',
        encoding="utf-8",
    )
    current = seal_agent_generation_bundle(context.workdir)
    assert current.manifest_hash != context.manifest.manifest_hash

    _assert_manifest_failure(context)


def test_directly_forged_manifest_is_rejected_against_observed_bundle(
    context: SeededRecorderContext,
) -> None:
    entries = (
        AgentWorkspaceManifestEntryV1(
            relativePath="workflow/Snakefile",
            size=0,
            sha256=hashlib.sha256(b"").hexdigest(),
        ),
    )
    forged = AgentGenerationBundleManifest(
        entries=entries,
        manifest_hash=agent_workspace_manifest_hash(entries),
    )

    _assert_manifest_failure(context, manifest=forged)


def test_invalid_workdir_is_path_free_and_rolls_back_atomically(
    context: SeededRecorderContext,
    tmp_path: Path,
) -> None:
    private_path = (tmp_path / "private-sensitive-workdir").resolve()

    error = _assert_manifest_failure(context, workdir=private_path)

    assert error.__suppress_context__ is True
    assert str(private_path) not in str(error)


def test_caller_workdir_must_match_attempt_bound_managed_workdir(
    context: SeededRecorderContext,
) -> None:
    other = context.workdir.parent / "other-attempt"
    other.mkdir()

    _assert_manifest_failure(context, workdir=other)


def test_attempt_workdir_outside_managed_root_is_rejected_atomically(
    context: SeededRecorderContext,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-managed-root"
    outside.mkdir()
    connection = get_connection(context.cfg)
    try:
        connection.execute(
            "UPDATE run_attempts SET work_dir = ? WHERE attempt_id = ?",
            (str(outside.resolve()), ATTEMPT_ID),
        )
        connection.commit()
    finally:
        connection.close()

    _assert_manifest_failure(context, workdir=outside.resolve())


def test_invalid_manifest_launch_command_and_real_run_are_rejected_before_writes(
    context: SeededRecorderContext,
) -> None:
    bad_manifest = AgentGenerationBundleManifest(
        context.manifest.entries,
        "0" * 64,
    )
    cases = [
        (
            bad_manifest,
            build_recorder_launch_command(context.workdir),
            "manifest",
        ),
        (context.manifest, object(), "launch_command"),
        (
            context.manifest,
            build_recorder_launch_command(context.workdir, process_kind="run"),
            "process_kind",
        ),
    ]
    for manifest, launch_command, component in cases:
        with pytest.raises(
            AgentProcessLaunchPreparationError,
            match=rf"AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: {component}",
        ):
            prepare_agent_process_launch(
                context.cfg,
                expected_authorization=context.authorization,
                run_id=RUN_ID,
                attempt_id=ATTEMPT_ID,
                lease_generation=LEASE_GENERATION,
                launch_command=launch_command,  # type: ignore[arg-type]
                managed_workdir=context.workdir,
                sealed_manifest=manifest,
            )
    assert _table_counts(context) == {
        "proofs": 0,
        "processes": 0,
        "spawn_events": 0,
    }


def test_gate_token_hash_requires_exact_256_bit_bytes() -> None:
    with pytest.raises(ValueError, match="AGENT_PROCESS_GATE_TOKEN_INVALID"):
        agent_process_gate_token_hash(b"short")
    with pytest.raises(ValueError, match="AGENT_PROCESS_GATE_TOKEN_INVALID"):
        agent_process_gate_token_hash(bytearray(32))  # type: ignore[arg-type]


def test_database_open_failure_is_mapped_to_stable_path_free_error(
    context: SeededRecorderContext,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing" / "runner.sqlite3"
    cfg = dataclasses.replace(context.cfg, db_path=str(missing))

    with pytest.raises(AgentProcessLaunchPreparationError) as raised:
        prepare_agent_process_launch(
            cfg,
            expected_authorization=context.authorization,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
            lease_generation=LEASE_GENERATION,
            launch_command=build_recorder_launch_command(context.workdir),
            managed_workdir=context.workdir,
            sealed_manifest=context.manifest,
        )

    assert str(raised.value) == ("AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: storage")
    assert raised.value.__suppress_context__ is True
    assert str(tmp_path) not in str(raised.value)


def test_writer_lock_revalidates_schema_after_connection_readiness(
    context: SeededRecorderContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_get_connection = recorder.get_connection

    def connection_with_late_trigger(cfg):
        connection = real_get_connection(cfg)
        connection.execute(
            "CREATE TRIGGER forged_workspace_side_effect "
            "AFTER INSERT ON agent_workspace_proofs BEGIN "
            "UPDATE runs SET status = 'canceling' WHERE run_id = NEW.run_id; END"
        )
        connection.commit()
        return connection

    monkeypatch.setattr(recorder, "get_connection", connection_with_late_trigger)
    with pytest.raises(
        AgentProcessLaunchPreparationError,
        match=r"^AGENT_PROCESS_LAUNCH_PREPARATION_FAILED: storage$",
    ):
        _prepare(context)

    with sqlite3.connect(context.cfg.db_path) as connection:
        assert connection.execute(
            "SELECT status FROM runs WHERE run_id = ?", (RUN_ID,)
        ).fetchone() == ("running",)
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_workspace_proofs"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM agent_process_instances"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM run_events "
            "WHERE event_type = 'agent_process_spawn_intent_recorded'"
        ).fetchone() == (0,)
