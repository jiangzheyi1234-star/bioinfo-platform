from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner import agent_workflow_runtime as runtime_builder
from apps.remote_runner.agent_run_authorization_authority import (
    prepare_agent_run_authorization_authority,
)
from apps.remote_runner.agent_run_authorization_service import (
    authorize_agent_workflow_run,
)
from apps.remote_runner.run_worker import process_next_run_job
from apps.remote_runner.storage import create_run_record, fetch_run, update_run_state
from apps.remote_runner.storage_core import get_connection
from core.contracts.agent_control_plane_namespace import (
    AGENT_CONTROL_PLANE_SERVER_ID,
)


pytest_plugins = ("tests.test_agent_fastq_qc_execution_candidate",)


def _authorize(candidate_case: dict[str, Any]) -> dict[str, Any]:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    preview = prepare_agent_run_authorization_authority(
        cfg,
        session_id,
        actor="user-1",
    ).preview
    request = {
        "expectedStateVersion": preview["stateVersion"],
        "expectedPlanRevisionId": preview["planRevisionId"],
        "expectedPlanGeneration": preview["planGeneration"],
        "expectedPlanHash": preview["planHash"],
        "expectedWorkflowRevisionId": preview["workflowRevisionId"],
        "expectedPreviewHash": preview["previewHash"],
        "expectedInputManifestDigest": preview["inputManifestDigest"],
        "expectedRunSpecHash": preview["runSpecHash"],
        "expectedExecutionPolicyHash": preview["executionPolicyHash"],
        "expectedRuntimeProofHash": preview["runtimeProofHash"],
        "confirmation": "authorize-workflow-run",
        "requestId": "authorize-agent-launch-gate",
        "idempotencyKey": "authorize-agent-launch-gate",
    }
    return authorize_agent_workflow_run(
        cfg,
        session_id,
        request,
        actor="user-1",
    )


def test_bound_agent_run_revalidates_origin_and_runtime_before_executor(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    seen: list[dict[str, Any]] = []
    seen_inputs: list[list[dict[str, Any]]] = []

    def fail_if_process_started(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("the launch gate runtime check must remain passive")

    monkeypatch.setattr(runtime_builder.subprocess, "run", fail_if_process_started)
    monkeypatch.setattr(
        runtime_builder,
        "_probe_snakemake_version",
        fail_if_process_started,
    )

    def fake_execute(
        _cfg: Any,
        *,
        run_id: str,
        request_id: str,
        run_spec: dict[str, Any],
        attempt_id: str,
        lease_generation: int,
        verified_inputs: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        seen.append(run_spec)
        seen_inputs.append(verified_inputs)
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Agent launch gate test completed.",
            request_id=request_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )

    result = process_next_run_job(
        cfg,
        worker_id="agent-launch-worker",
        execute_run=fake_execute,
        heartbeat_interval_seconds=0,
    )

    assert result["claimed"] is True
    assert result["runId"] == run_id
    assert result["executionError"] == ""
    assert result["attemptCompletion"]["state"] == "succeeded"
    assert len(seen) == 1
    assert (
        seen[0]["workflowRevisionId"]
        == candidate_case["revision"]["workflowRevisionId"]
    )
    assert seen[0]["inputs"] == [
        {
            "role": "reads",
            "uploadId": candidate_case["upload"]["uploadId"],
            "filename": "reads.fastq",
        }
    ]
    assert len(seen_inputs) == 1
    private_input = Path(seen_inputs[0][0]["path"])
    assert (Path(cfg.work_dir) / "agent-inputs").resolve() in private_input.parents
    assert private_input != Path(candidate_case["upload"]["path"])
    assert not private_input.samefile(candidate_case["upload"]["path"])
    assert private_input.stat().st_nlink == 1
    assert private_input.stat().st_mode & stat.S_IWUSR == 0
    assert (
        private_input.read_bytes()
        == Path(candidate_case["upload"]["path"]).read_bytes()
    )
    with get_connection(cfg) as connection:
        events = connection.execute(
            "SELECT details_json FROM run_events WHERE run_id = ? AND event_type = 'agent_input_materialized'",
            (run_id,),
        ).fetchall()
    assert len(events) == 1
    event_json = str(events[0]["details_json"])
    assert str(private_input) not in event_json
    assert candidate_case["upload"]["path"] not in event_json


def test_default_executor_receives_process_boundary_authority_and_private_input(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.remote_runner import run_worker
    from apps.remote_runner.executor import _agent_process_launch_guard
    from apps.remote_runner.agent_workspace_launch_guard import (
        AgentWorkspaceLaunchGuard,
    )

    cfg = candidate_case["cfg"]
    authorization_result = _authorize(candidate_case)
    run_id = authorization_result["run"]["runId"]
    seen: list[dict[str, Any]] = []

    def fake_default_executor(
        _cfg: Any,
        *,
        request_id: str,
        attempt_id: str,
        lease_generation: int,
        attempt_work_dir: str,
        agent_launch_authorization: Any,
        verified_inputs: list[dict[str, Any]],
        should_cancel_attempt: Any,
        **_kwargs: Any,
    ) -> None:
        workspace_guard = AgentWorkspaceLaunchGuard(
            managed_work_root=cfg.work_dir,
            managed_results_root=cfg.results_dir,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            claimed_workdir=attempt_work_dir,
            result_dir=(
                Path(cfg.results_dir)
                / "attempts"
                / attempt_id
                / f"generation-{lease_generation}"
            ),
        )
        workdir = Path(attempt_work_dir)
        (workdir / "workflow").mkdir()
        (workdir / "workflow" / "Snakefile").write_text("rule all:\n    input: []\n")
        (workdir / "run-config.json").write_text("{}")
        workspace_guard.seal()
        guard = _agent_process_launch_guard(
            cfg,
            authorization=agent_launch_authorization,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            workspace_guard=workspace_guard,
        )
        assert guard is not None
        guard()
        assert should_cancel_attempt() is False
        seen.append(
            {
                "authorizationId": agent_launch_authorization.authorization_id,
                "verifiedInputs": verified_inputs,
            }
        )
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Default executor boundary proof completed.",
            request_id=request_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )

    monkeypatch.setattr(
        run_worker,
        "run_snakemake_execution",
        fake_default_executor,
    )
    result = process_next_run_job(
        cfg,
        worker_id="agent-default-executor-worker",
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == ""
    assert (
        seen[0]["authorizationId"]
        == authorization_result["authorization"]["authorizationId"]
    )
    assert seen[0]["verifiedInputs"][0]["agentInputSnapshot"] is True


def test_bound_agent_run_origin_tamper_fails_without_executor(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE run_commands SET actor = 'tampered' WHERE run_id = ?",
            (run_id,),
        )
        connection.commit()

    result = process_next_run_job(
        cfg,
        worker_id="agent-origin-tamper-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not run after origin tamper"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["claimed"] is True
    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: authority"
    _assert_launch_gate_failure(cfg, run_id)


@pytest.mark.parametrize(
    ("trigger_name", "statement", "value"),
    [
        (
            "agent_run_authorizations_no_update",
            "UPDATE agent_run_authorizations SET runtime_lock_hash = ? WHERE run_id = ?",
            "0" * 64,
        ),
        (
            "workflow_revisions_no_update",
            "UPDATE workflow_revisions SET runtime_lock_json = ? WHERE workflow_revision_id = (SELECT workflow_revision_id FROM runs WHERE run_id = ?)",
            "{}",
        ),
    ],
)
def test_bound_agent_run_rejects_binding_or_revision_tamper(
    candidate_case: dict[str, Any],
    trigger_name: str,
    statement: str,
    value: str,
) -> None:
    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    with get_connection(cfg) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
            (trigger_name,),
        ).fetchone()
        assert trigger is not None
        trigger_sql = str(trigger["sql"])
        connection.execute(f"DROP TRIGGER {trigger_name}")
        try:
            connection.execute(statement, (value, run_id))
        finally:
            connection.execute(trigger_sql)
            connection.commit()

    result = process_next_run_job(
        cfg,
        worker_id=f"agent-storage-tamper-{trigger_name}",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not run after immutable authority tamper"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: authority"
    _assert_launch_gate_failure(cfg, run_id)


def test_binding_not_server_namespace_selects_strict_launch_gate(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE runs SET server_id = 'ordinary-runner' WHERE run_id = ?",
            (run_id,),
        )
        connection.commit()

    result = process_next_run_job(
        cfg,
        worker_id="agent-binding-classifier-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "a bound run with a tampered namespace must still enter the strict gate"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: authority"
    _assert_launch_gate_failure(cfg, run_id)


def test_reserved_namespace_without_binding_remains_an_ordinary_run(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    created = create_run_record(
        cfg,
        server_id="ordinary-runner",
        request_id="ordinary-lookalike-request",
        run_spec={
            "projectId": "proj_ordinary",
            "pipelineId": "pipeline_ordinary",
            "pipelineVersion": "0.1.0",
        },
        idempotency_key="ordinary-lookalike-idempotency",
        payload_hash="ordinary-lookalike-payload",
    )
    run_id = created.run["runId"]
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE runs SET server_id = ? WHERE run_id = ?",
            (AGENT_CONTROL_PLANE_SERVER_ID, run_id),
        )
        connection.commit()

    def fake_execute(
        _cfg: Any,
        *,
        request_id: str,
        attempt_id: str,
        lease_generation: int,
        **_kwargs: Any,
    ) -> None:
        update_run_state(
            cfg,
            run_id=run_id,
            status="completed",
            stage="finalize",
            message="Ordinary look-alike completed.",
            request_id=request_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )

    result = process_next_run_job(
        cfg,
        worker_id="ordinary-lookalike-worker",
        execute_run=fake_execute,
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == ""
    assert result["attemptCompletion"]["state"] == "succeeded"


def test_bound_agent_run_runtime_drift_fails_without_process_launch(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    release_file = Path(cfg.release_dir) / "runtime-proof-fixture.py"
    release_file.write_bytes(
        release_file.read_bytes() + b"\nruntime-drift-before-launch\n"
    )

    result = process_next_run_job(
        cfg,
        worker_id="agent-runtime-drift-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not run after runtime drift"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["claimed"] is True
    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: runtime"
    _assert_launch_gate_failure(cfg, run_id)


def test_bound_agent_run_rejects_same_size_upload_byte_tamper(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    upload_path = Path(candidate_case["upload"]["path"])
    original = upload_path.read_bytes()
    upload_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])

    result = process_next_run_job(
        cfg,
        worker_id="agent-input-tamper-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not receive upload bytes changed after authorization"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: input"
    _assert_launch_gate_failure(cfg, run_id)


def test_post_gate_runtime_drift_is_rejected_before_custom_executor(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.remote_runner import run_worker

    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    original_gate = run_worker.require_agent_run_launch_authorization
    gate_calls = 0

    def gate_then_drift(*args: Any, **kwargs: Any):
        nonlocal gate_calls
        result = original_gate(*args, **kwargs)
        gate_calls += 1
        if gate_calls == 1 and result is not None:
            release_file = Path(cfg.release_dir) / "runtime-proof-fixture.py"
            release_file.write_bytes(release_file.read_bytes() + b"\npost-gate-drift\n")
        return result

    monkeypatch.setattr(
        run_worker,
        "require_agent_run_launch_authorization",
        gate_then_drift,
    )
    result = process_next_run_job(
        cfg,
        worker_id="agent-post-gate-runtime-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not run after the post-gate barrier changes"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: runtime"
    _assert_launch_gate_failure(cfg, run_id)


def test_post_gate_stale_lease_is_rejected_without_false_run_failure(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.remote_runner import run_worker

    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    original_gate = run_worker.require_agent_run_launch_authorization
    gate_calls = 0

    def gate_then_fence(*args: Any, **kwargs: Any):
        nonlocal gate_calls
        result = original_gate(*args, **kwargs)
        gate_calls += 1
        if gate_calls == 1 and result is not None:
            with get_connection(cfg) as connection:
                connection.execute(
                    "UPDATE run_leases SET state = 'expired' WHERE run_id = ?",
                    (run_id,),
                )
                connection.commit()
        return result

    monkeypatch.setattr(
        run_worker,
        "require_agent_run_launch_authorization",
        gate_then_fence,
    )
    result = process_next_run_job(
        cfg,
        worker_id="agent-post-gate-stale-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "a stale attempt must not enter the executor"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "RUN_ATTEMPT_STALE"
    assert result["attemptCompletion"]["accepted"] is False
    run = fetch_run(cfg, run_id)
    assert run is not None
    assert run["status"] == "queued"
    assert run["lastError"] is None


def test_post_gate_private_input_tamper_is_rejected_before_executor(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.remote_runner import run_worker

    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    original_gate = run_worker.require_agent_run_launch_authorization
    gate_calls = 0

    def gate_then_tamper(*args: Any, **kwargs: Any):
        nonlocal gate_calls
        result = original_gate(*args, **kwargs)
        gate_calls += 1
        if gate_calls == 1 and result is not None:
            private_path = Path(result.verified_inputs[0]["path"])
            private_path.chmod(0o600)
            original = private_path.read_bytes()
            private_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        return result

    monkeypatch.setattr(
        run_worker,
        "require_agent_run_launch_authorization",
        gate_then_tamper,
    )
    result = process_next_run_job(
        cfg,
        worker_id="agent-private-input-tamper-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not consume a changed private input"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: input"
    _assert_launch_gate_failure(cfg, run_id)


def test_post_gate_hardlinked_private_input_is_rejected_before_executor(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.remote_runner import run_worker

    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    upload_path = Path(candidate_case["upload"]["path"])
    original_gate = run_worker.require_agent_run_launch_authorization
    gate_calls = 0

    def gate_then_hardlink(*args: Any, **kwargs: Any):
        nonlocal gate_calls
        result = original_gate(*args, **kwargs)
        gate_calls += 1
        if gate_calls == 1 and result is not None:
            private_path = Path(result.verified_inputs[0]["path"])
            private_path.chmod(0o600)
            private_path.unlink()
            try:
                os.link(upload_path, private_path)
            except OSError as exc:
                pytest.skip(f"hard links unavailable on this filesystem: {exc}")
        return result

    monkeypatch.setattr(
        run_worker,
        "require_agent_run_launch_authorization",
        gate_then_hardlink,
    )
    result = process_next_run_job(
        cfg,
        worker_id="agent-private-input-hardlink-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not consume a hardlinked private input"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: input"
    _assert_launch_gate_failure(cfg, run_id)


def test_preplanted_private_input_symlink_is_rejected_before_executor(
    candidate_case: dict[str, Any],
) -> None:
    from apps.remote_runner.agent_run_input_materialization import (
        _materialization_path,
    )

    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    with get_connection(cfg) as connection:
        binding = connection.execute(
            "SELECT receipt_hash FROM agent_run_authorizations WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert binding is not None
    target = _materialization_path(
        cfg,
        run_id=run_id,
        receipt_hash=str(binding["receipt_hash"]),
        filename="reads.fastq",
    )
    shared = target.with_name("shared.fastq")
    shared.write_bytes(Path(candidate_case["upload"]["path"]).read_bytes())
    try:
        target.symlink_to(shared)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable on this filesystem: {exc}")

    result = process_next_run_job(
        cfg,
        worker_id="agent-private-input-symlink-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not consume a preplanted private-input symlink"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: input"
    _assert_launch_gate_failure(cfg, run_id)


def test_launch_gate_failure_redacts_nested_filesystem_error(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.remote_runner import agent_run_launch_gate as gate_module

    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    secret_detail = f"{cfg.release_dir}\\secret-runtime-token"

    def fail_with_private_detail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(secret_detail)

    monkeypatch.setattr(
        gate_module,
        "materialize_agent_run_input",
        fail_with_private_detail,
    )
    result = process_next_run_job(
        cfg,
        worker_id="agent-redaction-worker",
        execute_run=lambda *_args, **_kwargs: pytest.fail(
            "executor must not run after a gate failure"
        ),
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: input"
    run = fetch_run(cfg, run_id)
    assert run is not None
    assert run["lastError"]["message"] == "AGENT_RUN_LAUNCH_GATE_FAILED: input"
    assert secret_detail not in json.dumps(result)
    assert secret_detail not in json.dumps(run["lastError"])


def test_verified_private_input_io_error_is_path_free_in_persisted_failure(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.remote_runner.executor_inputs import require_verified_run_inputs

    cfg = candidate_case["cfg"]
    authorization = _authorize(candidate_case)
    run_id = authorization["run"]["runId"]
    secret_detail = str(Path(cfg.work_dir) / "agent-inputs" / "secret.fastq")

    def fake_execute(
        _cfg: Any,
        *,
        run_spec: dict[str, Any],
        verified_inputs: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        private_path = Path(verified_inputs[0]["path"])
        original_open = Path.open

        def fail_private_open(path: Path, *args: Any, **kwargs: Any):
            if path == private_path:
                raise OSError(f"private input unavailable: {secret_detail}")
            return original_open(path, *args, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "open", fail_private_open)
            require_verified_run_inputs(cfg, run_spec, verified_inputs)

    result = process_next_run_job(
        cfg,
        worker_id="agent-private-input-redaction-worker",
        execute_run=fake_execute,
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_VERIFIED_INPUT_IO_FAILED"
    run = fetch_run(cfg, run_id)
    assert run is not None
    assert run["lastError"]["message"] == "AGENT_RUN_VERIFIED_INPUT_IO_FAILED"
    with get_connection(cfg) as connection:
        event_details = [
            str(row["details_json"])
            for row in connection.execute(
                "SELECT details_json FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        ]
    assert secret_detail not in json.dumps(result)
    assert secret_detail not in json.dumps(run["lastError"])
    assert all(secret_detail not in detail for detail in event_details)


def _assert_launch_gate_failure(cfg: Any, run_id: str) -> None:
    run = fetch_run(cfg, run_id)
    assert run is not None
    assert run["status"] == "failed"
    assert run["stage"] == "agent_launch_gate"
    assert run["message"] == "Agent run launch gate failed."
    assert run["lastError"] == {
        "code": "AGENT_RUN_LAUNCH_GATE_FAILED",
        "message": run["lastError"]["message"],
        "scope": "agent_launch_gate",
        "stage": "agent_launch_gate",
    }
    assert "runtime-drift-before-launch" not in json.dumps(run["lastError"])
