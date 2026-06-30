from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.execution_resume_claim_preflight import build_run_resume_execution_options
from apps.remote_runner.run_execution_context_storage import fetch_run_execution_context
from apps.remote_runner.run_execution_storage import claim_next_run_job, complete_run_attempt
from apps.remote_runner.run_worker import process_next_run_job
from apps.remote_runner.storage import create_run_record
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_run_storage import update_run_state
from tests.helpers.reference_database import make_configured_remote_runner


class FakeClock:
    def __init__(self) -> None:
        self.tick = 0

    def __call__(self) -> str:
        self.tick += 1
        return f"2099-06-07T10:01:{self.tick:02d}Z"


def test_run_worker_executes_run_resume_after_claim_reuses_source_workdir(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import run_worker

    cfg, run_id = _failed_resumable_run(tmp_path)
    options = build_run_resume_execution_options(fetch_run_execution_context(cfg, run_id)["resumePlan"])
    _requeue_with_execution_options(cfg, run_id, options)
    source_attempt_id = options["resumeScope"]["sourceAttempt"]["attemptId"]
    with get_connection(cfg) as connection:
        source_work_dir = connection.execute(
            "SELECT work_dir FROM run_attempts WHERE attempt_id = ?",
            (source_attempt_id,),
        ).fetchone()["work_dir"]

    captured: dict[str, object] = {}

    def fake_executor(executor_cfg, **kwargs) -> None:
        captured.update(kwargs)
        update_run_state(
            executor_cfg,
            run_id=str(kwargs["run_id"]),
            status="completed",
            stage="finalize",
            message="Resume execution completed.",
            request_id=str(kwargs["request_id"]),
            result_dir=str(Path(executor_cfg.results_dir) / run_id),
            attempt_id=str(kwargs["attempt_id"]),
            lease_generation=int(kwargs["lease_generation"]),
        )

    monkeypatch.setattr(run_worker, "run_snakemake_execution", fake_executor)

    result = process_next_run_job(
        cfg,
        worker_id="worker_resume_unproven",
        lease_seconds=30,
        heartbeat_interval_seconds=0,
        now_factory=FakeClock(),
    )

    assert result["claimed"] is True
    assert result["executionError"] == ""
    assert result["attemptCompletion"]["accepted"] is True
    assert captured["execution_options"] == options
    assert captured["attempt_work_dir"] == source_work_dir


def test_run_worker_revalidates_persisted_run_resume_options_after_claim(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import run_worker

    cfg, run_id = _failed_resumable_run(tmp_path)
    options = build_run_resume_execution_options(fetch_run_execution_context(cfg, run_id)["resumePlan"])
    _requeue_with_execution_options(cfg, run_id, options)

    def tamper_persisted_options(_claim: dict) -> None:
        tampered = {**options, "resumeScope": {**options["resumeScope"], "outputKeys": ["other"]}}
        with get_connection(cfg) as connection:
            connection.execute(
                "UPDATE run_jobs SET execution_options_json = ? WHERE run_id = ?",
                (json.dumps(tampered, sort_keys=True, separators=(",", ":")), run_id),
            )
            connection.commit()

    def fail_executor(*_args, **_kwargs) -> None:
        raise AssertionError("executor must not run when persisted resume options changed after claim")

    monkeypatch.setattr(run_worker, "run_snakemake_execution", fail_executor)

    result = process_next_run_job(
        cfg,
        worker_id="worker_resume_tampered",
        lease_seconds=30,
        heartbeat_interval_seconds=0,
        now_factory=FakeClock(),
        on_attempt_claimed=tamper_persisted_options,
    )

    assert result["claimed"] is True
    assert result["executionError"] == "RUN_RESUME_CLAIM_EXECUTION_OPTIONS_MISMATCH"


def _failed_resumable_run(tmp_path: Path):
    cfg = make_configured_remote_runner(tmp_path)
    run_id = "run_resume_worker_preflight"
    create_run_record(
        cfg,
        server_id="srv_resume_worker",
        request_id="req_resume_worker",
        run_spec={
            "runId": run_id,
            "projectId": "proj_resume_worker",
            "pipelineId": "pipeline_resume_worker",
            "workflowRevisionId": "wfrev_resume",
            "execution": {"retryPolicy": {"maxAttempts": 3, "backoffSeconds": 0}},
        },
        idempotency_key="idem_resume_worker",
        payload_hash="h" * 64,
    )
    source_claim = claim_next_run_job(
        cfg,
        worker_id="worker_resume_source",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert source_claim is not None
    source_work_dir = Path(str(source_claim["attempt"]["workDir"]))
    result_dir = Path(cfg.results_dir) / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    present = result_dir / "present.txt"
    present.write_text("ok\n", encoding="utf-8")
    source_work_dir.mkdir(parents=True, exist_ok=True)
    (source_work_dir / "run-config.json").write_text(
        json.dumps({"outputs": {"present": str(present), "missing": str(result_dir / "missing.txt")}}),
        encoding="utf-8",
    )
    update_run_state(
        cfg,
        run_id=run_id,
        status="failed",
        stage="execute",
        message="Attempt failed.",
        request_id="req_resume_worker",
        attempt_id=source_claim["attemptId"],
        lease_generation=source_claim["leaseGeneration"],
    )
    complete_run_attempt(
        cfg,
        source_claim["attemptId"],
        lease_generation=source_claim["leaseGeneration"],
        state="failed",
        exit_code=1,
        now="2099-06-07T10:00:10Z",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE runs SET result_dir = ?, finished_at = ?, last_updated_at = ? WHERE run_id = ?",
            (str(result_dir), "2099-06-07T10:00:10Z", "2099-06-07T10:00:10Z", run_id),
        )
        connection.commit()
    return cfg, run_id


def _requeue_with_execution_options(cfg, run_id: str, options: dict) -> None:
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE run_jobs
            SET state = 'queued', execution_options_json = ?, available_at = ?, updated_at = ?
            WHERE run_id = ?
            """,
            (
                json.dumps(options, sort_keys=True, separators=(",", ":")),
                "2099-06-07T10:01:00Z",
                "2099-06-07T10:01:00Z",
                run_id,
            ),
        )
        connection.commit()
