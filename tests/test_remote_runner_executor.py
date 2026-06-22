from __future__ import annotations

import json
import os
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.run_worker import process_next_run_job
from tests.helpers.remote_runner_control_plane import (
    _write_file_summary_pipeline,
)


def test_executor_invokes_snakemake_cli_with_use_conda(tmp_path: Path, monkeypatch) -> None:
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(snakemake_command),
    )
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))
    ensure_runtime_layout(cfg)

    calls: list[list[str]] = []

    class Result:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    from apps.remote_runner.storage import persist_upload

    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )

    run_snakemake_execution(
        cfg,
        run_id="run_phase2",
        request_id="req_phase2",
        run_spec={
            "pipelineId": "file-summary-v1",
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "reads"}],
        },
    )

    assert len(calls) == 2
    assert calls[0][0] == str(snakemake_command)
    assert "--workflow-profile" in calls[0]
    assert str(Path(cfg.workflow_profile_dir)) in calls[0]
    assert "-n" in calls[0]
    assert "--workflow-profile" in calls[1]
    run_config = json.loads((Path(cfg.work_dir) / "run_phase2" / "run-config.json").read_text(encoding="utf-8"))
    assert run_config["pipeline_id"] == "file-summary-v1"
    assert run_config["inputs"][0]["path"] == upload["path"]
    assert run_config["inputs"][0]["sha256"] == upload["sha256"]

def test_executor_fails_when_upload_input_is_missing(tmp_path: Path, monkeypatch) -> None:
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(tmp_path / "snakemake"),
    )
    _write_file_summary_pipeline(Path(cfg.release_dir))
    ensure_runtime_layout(cfg)
    from apps.remote_runner.storage import create_run_record, fetch_run

    create_run_record(
        cfg,
        server_id="srv_demo",
        request_id="req_missing_input",
        run_spec={
            "runId": "run_missing_input",
            "projectId": "proj_demo",
            "pipelineId": "file-summary-v1",
            "inputs": [{"uploadId": "upl_missing", "filename": "missing.fastq", "role": "reads"}],
        },
        idempotency_key="idem_missing_input",
        payload_hash="h" * 64,
    )

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *args, **kwargs: None)
    run_snakemake_execution(
        cfg,
        run_id="run_missing_input",
        request_id="req_missing_input",
        run_spec={
            "projectId": "proj_demo",
            "pipelineId": "file-summary-v1",
            "inputs": [{"uploadId": "upl_missing", "filename": "missing.fastq", "role": "reads"}],
        },
    )

    run = fetch_run(cfg, "run_missing_input")
    assert run["status"] == "failed"
    assert run["stage"] == "validate"
    assert run["lastError"]["code"] == "INPUT_NOT_FOUND"

def test_executor_marks_cancelled_when_dry_run_is_cancelled(tmp_path: Path, monkeypatch) -> None:
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(snakemake_command),
    )
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))
    ensure_runtime_layout(cfg)

    from apps.remote_runner.storage import create_run_record, fetch_run, persist_upload

    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )
    run_spec = {
        "pipelineId": "file-summary-v1",
        "projectId": "proj_demo",
        "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "reads"}],
    }
    created = create_run_record(
        cfg,
        server_id="srv_demo",
        request_id="req_cancel_dry_run",
        run_spec=run_spec,
        idempotency_key="idem_cancel_dry_run",
        payload_hash="c" * 64,
    )

    class Result:
        returncode = -15
        stdout = ""
        stderr = "Snakemake process terminated after cancel."

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *args, **kwargs: Result())

    run_snakemake_execution(
        cfg,
        run_id=created.run["runId"],
        request_id="req_cancel_dry_run",
        run_spec=run_spec,
        should_cancel_attempt=lambda: True,
    )

    run = fetch_run(cfg, created.run["runId"])
    assert run["status"] == "canceled"
    assert run["stage"] == "cancel"
    assert run["lastError"]["code"] == "RUN_CANCELLED"

def test_executor_exports_managed_conda_runtime_when_configured(tmp_path: Path, monkeypatch) -> None:
    managed_conda_command = tmp_path / "tooling" / "bin" / "micromamba"
    managed_conda_root_prefix = tmp_path / "tooling" / "micromamba-root"
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        managed_conda_command=str(managed_conda_command),
        managed_conda_root_prefix=str(managed_conda_root_prefix),
        snakemake_command=str(snakemake_command),
    )
    managed_conda_command.parent.mkdir(parents=True, exist_ok=True)
    managed_conda_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))
    ensure_runtime_layout(cfg)

    calls: list[dict[str, object]] = []

    class Result:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": cmd, "env": kwargs.get("env")})
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    from apps.remote_runner.storage import persist_upload

    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )

    run_snakemake_execution(
        cfg,
        run_id="run_phase2_managed_conda",
        request_id="req_phase2_managed_conda",
        run_spec={
            "pipelineId": "file-summary-v1",
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "reads"}],
        },
    )

    assert len(calls) == 2
    for call in calls:
        env = call["env"]
        assert isinstance(env, dict)
        assert env["H2OMETA_MANAGED_CONDA_COMMAND"] == str(managed_conda_command)
        assert env["MAMBA_ROOT_PREFIX"] == str(managed_conda_root_prefix)
        path_entries = env["PATH"].split(os.pathsep)
        assert path_entries[0] == str(snakemake_command.parent)
        assert path_entries[1] == str(managed_conda_command.parent)


def test_executor_records_attempt_process_group_when_process_starts(tmp_path: Path, monkeypatch) -> None:
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(snakemake_command),
    )
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))
    ensure_runtime_layout(cfg)

    from apps.remote_runner.storage import create_run_record, persist_upload
    from apps.remote_runner.run_execution_storage import claim_next_run_job
    from apps.remote_runner.storage_core import get_connection

    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )
    run_spec = {
        "runId": "run_attempt_process_group",
        "projectId": "proj_demo",
        "pipelineId": "file-summary-v1",
        "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "reads"}],
    }
    create_run_record(
        cfg,
        server_id="srv_demo",
        request_id="req_attempt_process_group",
        run_spec=run_spec,
        idempotency_key="idem_attempt_process_group",
        payload_hash="h" * 64,
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_process_group",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None

    class FakeProcess:
        pid = 4242
        returncode = 0

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return "ok", ""

    monkeypatch.setattr("apps.remote_runner.process_runner.subprocess.Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])

    run_snakemake_execution(
        cfg,
        run_id="run_attempt_process_group",
        request_id="req_attempt_process_group",
        run_spec=run_spec,
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        attempt_work_dir=claim["attempt"]["workDir"],
    )

    with get_connection(cfg) as connection:
        attempt = connection.execute(
            "SELECT process_group_id FROM run_attempts WHERE attempt_id = ?",
            (claim["attemptId"],),
        ).fetchone()
    assert attempt["process_group_id"] == "4242"


def test_executor_projects_snakemake_logger_events_into_rule_view(tmp_path: Path, monkeypatch) -> None:
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase3-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(snakemake_command),
    )
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))
    ensure_runtime_layout(cfg)

    from apps.remote_runner.rule_execution_storage import fetch_run_rules
    from apps.remote_runner.run_execution_storage import claim_next_run_job
    from apps.remote_runner.storage import create_run_record, persist_upload

    upload = persist_upload(
        cfg,
        filename="reads.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )
    run_spec = {
        "runId": "run_snakemake_logger_events",
        "projectId": "proj_demo",
        "pipelineId": "file-summary-v1",
        "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "reads"}],
    }
    create_run_record(
        cfg,
        server_id="srv_demo",
        request_id="req_snakemake_logger_events",
        run_spec=run_spec,
        idempotency_key="idem_snakemake_logger_events",
        payload_hash="h" * 64,
    )
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_snakemake_logger_events",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None

    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if "--logger-h2ometa-event-path" in cmd:
            event_path = Path(cmd[cmd.index("--logger-h2ometa-event-path") + 1])
            event_path.write_text(
                "\n".join(
                    json.dumps(record)
                    for record in [
                        {"event": "JOB_INFO", "jobId": 1, "ruleName": "all", "createdAt": "2099-06-07T10:00:01Z"},
                        {"event": "JOB_STARTED", "jobIds": [1], "createdAt": "2099-06-07T10:00:02Z"},
                        {"event": "JOB_FINISHED", "jobId": 1, "createdAt": "2099-06-07T10:00:03Z"},
                    ]
                ),
                encoding="utf-8",
            )
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])

    run_snakemake_execution(
        cfg,
        run_id="run_snakemake_logger_events",
        request_id="req_snakemake_logger_events",
        run_spec=run_spec,
        attempt_id=str(claim["attemptId"]),
        lease_generation=int(claim["leaseGeneration"]),
        attempt_number=int(claim["attempt"]["attemptNumber"]),
        attempt_work_dir=str(claim["attempt"]["workDir"]),
    )

    rules = fetch_run_rules(cfg, "run_snakemake_logger_events")["items"]
    assert len(calls) == 2
    assert "--logger-h2ometa-event-path" in calls[1]
    assert rules[0]["ruleName"] == "all"
    assert rules[0]["status"] == "succeeded"
    assert rules[0]["events"][-1]["eventType"] == "rule_finished"


def test_run_worker_adopts_artifact_cache_hit_after_dry_run(tmp_path: Path, monkeypatch) -> None:
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(snakemake_command),
    )
    snakemake_command.parent.mkdir(parents=True, exist_ok=True)
    snakemake_command.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    _write_file_summary_pipeline(Path(cfg.release_dir))
    ensure_runtime_layout(cfg)

    from apps.remote_runner.storage import create_run_record, persist_artifact, persist_upload
    from apps.remote_runner.storage_core import get_connection
    from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision

    revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id="draft_executor_cache",
        draft_revision=1,
        manifest={"files": [{"path": "workflow/Snakefile", "sha256": "executor-cache"}]},
        graph_snapshot={"nodes": [{"id": "summary", "toolRevisionId": "file-summary#1"}]},
        runtime_lock={"snakemake": "9.23.1"},
        compiler={"name": "h2ometa", "version": "executor-cache-test"},
    )
    source_upload = persist_upload(
        cfg,
        filename="source.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )
    target_upload = persist_upload(
        cfg,
        filename="target.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )
    source_spec = {
        "runId": "run_executor_cache_source",
        "projectId": "proj_demo",
        "pipelineId": "file-summary-v1",
        "workflowRevisionId": revision["workflowRevisionId"],
        "inputs": [{"uploadId": source_upload["uploadId"], "filename": "source.fastq", "role": "reads"}],
    }
    create_run_record(
        cfg,
        server_id="srv_demo",
        request_id="req_executor_cache_source",
        run_spec=source_spec,
        idempotency_key="idem_executor_cache_source",
        payload_hash="source-cache",
    )
    source_path = Path(cfg.results_dir) / "run_executor_cache_source" / "done.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("cached summary\n", encoding="utf-8")
    source_artifact = persist_artifact(
        cfg,
        run_id="run_executor_cache_source",
        kind="report",
        path=source_path,
        mime_type="text/plain",
        artifact_key="summary",
    )
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'completed',
                stage = 'complete',
                finished_at = '2099-06-07T10:00:00Z',
                last_updated_at = '2099-06-07T10:00:00Z'
            WHERE run_id = ?
            """,
            ("run_executor_cache_source",),
        )
        connection.execute(
            "UPDATE run_jobs SET state = 'completed', updated_at = '2099-06-07T10:00:00Z' WHERE run_id = ?",
            ("run_executor_cache_source",),
        )
        connection.commit()
    target_spec = {
        "runId": "run_executor_cache_target",
        "projectId": "proj_demo",
        "pipelineId": "file-summary-v1",
        "workflowRevisionId": revision["workflowRevisionId"],
        "inputs": [{"uploadId": target_upload["uploadId"], "filename": "target.fastq", "role": "reads"}],
    }
    create_run_record(
        cfg,
        server_id="srv_demo",
        request_id="req_executor_cache_target",
        run_spec=target_spec,
        idempotency_key="idem_executor_cache_target",
        payload_hash="target-cache",
    )
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "dry run ok"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", fake_run)

    worker_result = process_next_run_job(
        cfg,
        worker_id="worker_cache_hit",
        heartbeat_interval_seconds=0,
    )

    results = fetch_run_results(cfg, "run_executor_cache_target")
    with get_connection(cfg) as connection:
        run = connection.execute(
            "SELECT status, stage FROM runs WHERE run_id = ?",
            ("run_executor_cache_target",),
        ).fetchone()
        attempt = connection.execute(
            "SELECT state, output_adoption_state FROM run_attempts WHERE run_id = ?",
            ("run_executor_cache_target",),
        ).fetchone()

    assert worker_result["claimed"] is True
    assert worker_result["attemptCompletion"]["state"] == "succeeded"
    assert len(calls) == 1
    assert "-n" in calls[0]
    assert run["status"] == "completed"
    assert run["stage"] == "cache"
    assert attempt["state"] == "succeeded"
    assert attempt["output_adoption_state"] == "adopted"
    assert results["artifacts"][0]["artifactId"] != source_artifact["artifactId"]
    assert results["artifacts"][0]["sha256"] == source_artifact["sha256"]
