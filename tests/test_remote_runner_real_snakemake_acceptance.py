from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.metrics import collect_queue_metrics
from apps.remote_runner.resource_pool import ResourceRequest
from apps.remote_runner.run_execution_storage import claim_next_run_job, request_run_cancel
from apps.remote_runner.run_worker_storage import build_run_worker_health
from apps.remote_runner.storage import create_run_record, fetch_run, persist_upload
from apps.remote_runner.storage_core import get_connection
from tests.helpers.remote_runner_control_plane import _write_file_summary_pipeline


def test_real_snakemake_two_slot_supervisor_runs_two_attempts_and_leaves_third_waiting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config(tmp_path)
    barrier_dir = tmp_path / "barrier"
    release_file = barrier_dir / "release"
    barrier_dir.mkdir()
    monkeypatch.setenv("H2OMETA_REMOTE_ENABLE_MULTI_SLOT", "1")
    monkeypatch.setenv("H2OMETA_TEST_SNAKEMAKE_BARRIER_DIR", str(barrier_dir))
    run_ids = [_create_run(cfg, f"run_real_two_slot_{index}") for index in range(3)]

    from apps.remote_runner import worker_supervisor

    supervisor = worker_supervisor.start_run_worker_supervisor(
        cfg,
        worker_id="worker_real_two_slot",
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=0.1,
    )
    try:
        _wait_for_started_attempts(barrier_dir, expected_count=2)
        running = _running_attempts(cfg)
        running_ids = {row["run_id"] for row in running}
        waiting_id = next(run_id for run_id in run_ids if run_id not in running_ids)
        blocked = claim_next_run_job(
            cfg,
            worker_id="worker_probe_two_slot",
            session_id="session_probe_two_slot",
            slot_id="slot-probe",
            resource_request=ResourceRequest(cpu=1),
            resource_capacity=ResourceRequest(cpu=2),
            max_active_slots=2,
            now="2099-06-07T10:00:00Z",
            lease_seconds=30,
        )
        health = build_run_worker_health(cfg)
        metrics = collect_queue_metrics(cfg)

        assert blocked is None
        assert len(running) == 2
        assert {row["slot_id"] for row in running} == {"slot-0", "slot-1"}
        assert all(row["process_group_id"] for row in running)
        assert health["summary"]["runningSlots"] == 2
        assert metrics["runningAttempts"] == 2
        assert metrics["resourceWaitJobs"] == 1
        assert metrics["waitReasons"] == {"ADMISSION_SLOT_UNAVAILABLE": 1}
        assert _wait_reason_code(cfg, waiting_id) == "ADMISSION_SLOT_UNAVAILABLE"

        supervisor._stop_event.set()
        release_file.write_text("release\n", encoding="utf-8")
    finally:
        supervisor._stop_event.set()
        release_file.write_text("release\n", encoding="utf-8")
        supervisor.stop(timeout_seconds=5)

    for run_id in running_ids:
        _wait_for_run_status(cfg, run_id, "completed")
    with get_connection(cfg) as connection:
        waiting_job = connection.execute(
            "SELECT state, attempt_count FROM run_jobs WHERE run_id = ?",
            (waiting_id,),
        ).fetchone()
        allocations = connection.execute(
            "SELECT state, COUNT(*) AS count FROM run_resource_allocations GROUP BY state",
        ).fetchall()
        artifact_count = connection.execute("SELECT COUNT(*) AS count FROM artifacts").fetchone()["count"]

    assert dict(waiting_job) == {"state": "queued", "attempt_count": 0}
    assert {row["state"]: row["count"] for row in allocations} == {"released": 2}
    assert artifact_count == 2
    for attempt_id in {row["attempt_id"] for row in running}:
        assert (Path(cfg.results_dir) / "attempts" / attempt_id / "generation-1" / "done.txt").is_file()


def test_real_snakemake_two_slot_cancel_isolation(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path)
    barrier_dir = tmp_path / "barrier"
    release_file = barrier_dir / "release"
    barrier_dir.mkdir()
    monkeypatch.setenv("H2OMETA_REMOTE_ENABLE_MULTI_SLOT", "1")
    monkeypatch.setenv("H2OMETA_TEST_SNAKEMAKE_BARRIER_DIR", str(barrier_dir))
    run_ids = [_create_run(cfg, f"run_real_cancel_isolation_{index}") for index in range(2)]

    from apps.remote_runner import worker_supervisor

    supervisor = worker_supervisor.start_run_worker_supervisor(
        cfg,
        worker_id="worker_real_cancel_isolation",
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=0.1,
    )
    try:
        _wait_for_started_attempts(barrier_dir, expected_count=2)
        running = _running_attempts(cfg)
        target = running[0]
        sibling = next(row for row in running if row["run_id"] != target["run_id"])
        cancel = request_run_cancel(
            cfg,
            target["run_id"],
            actor="real-snakemake-acceptance",
            command_id="cmd_real_cancel_isolation",
            now="2099-06-07T10:00:05Z",
        )

        _wait_for_run_status(cfg, target["run_id"], "canceled")
        assert cancel["attemptId"] == target["attempt_id"]
        release_file.write_text("release\n", encoding="utf-8")
        supervisor._stop_event.set()
    finally:
        release_file.write_text("release\n", encoding="utf-8")
        supervisor._stop_event.set()
        supervisor.stop(timeout_seconds=5)

    _wait_for_run_status(cfg, sibling["run_id"], "completed")
    with get_connection(cfg) as connection:
        attempts = {
            row["run_id"]: dict(row)
            for row in connection.execute(
                """
                SELECT run_id, state, exit_code, cancel_requested_at
                FROM run_attempts
                WHERE run_id IN (?, ?)
                """,
                tuple(run_ids),
            ).fetchall()
        }
        leases = {
            row["run_id"]: row["state"]
            for row in connection.execute(
                "SELECT run_id, state FROM run_leases WHERE run_id IN (?, ?)",
                tuple(run_ids),
            ).fetchall()
        }
        active_allocations = connection.execute(
            "SELECT COUNT(*) AS count FROM run_resource_allocations WHERE state = 'allocated'",
        ).fetchone()["count"]
        artifact_count = connection.execute("SELECT COUNT(*) AS count FROM artifacts").fetchone()["count"]

    assert attempts[target["run_id"]]["state"] == "cancelled"
    assert attempts[target["run_id"]]["exit_code"] == 130
    assert attempts[target["run_id"]]["cancel_requested_at"] == "2099-06-07T10:00:05Z"
    assert attempts[sibling["run_id"]]["state"] == "succeeded"
    assert attempts[sibling["run_id"]]["cancel_requested_at"] is None
    assert leases[target["run_id"]] == "cancelled"
    assert leases[sibling["run_id"]] == "completed"
    assert fetch_run(cfg, target["run_id"])["status"] == "canceled"
    assert fetch_run(cfg, sibling["run_id"])["status"] == "completed"
    assert active_allocations == 0
    assert artifact_count == 1


def test_real_snakemake_resource_shortage_records_wait_reason(tmp_path: Path, monkeypatch) -> None:
    cfg = _config(tmp_path, run_worker_total_cpu=1)
    barrier_dir = tmp_path / "barrier"
    release_file = barrier_dir / "release"
    barrier_dir.mkdir()
    monkeypatch.setenv("H2OMETA_REMOTE_ENABLE_MULTI_SLOT", "1")
    monkeypatch.setenv("H2OMETA_TEST_SNAKEMAKE_BARRIER_DIR", str(barrier_dir))
    run_ids = [_create_run(cfg, f"run_real_resource_wait_{index}") for index in range(2)]

    from apps.remote_runner import worker_supervisor

    supervisor = worker_supervisor.start_run_worker_supervisor(
        cfg,
        worker_id="worker_real_resource_wait",
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=0.1,
    )
    try:
        _wait_for_started_attempts(barrier_dir, expected_count=1)
        waiting_id = _wait_for_wait_reason(cfg, "ADMISSION_RESOURCES_UNAVAILABLE", candidates=run_ids)
        health = build_run_worker_health(cfg)
        metrics = collect_queue_metrics(cfg)

        assert health["summary"]["runningSlots"] == 1
        assert metrics["runningAttempts"] == 1
        assert metrics["resourceWaitJobs"] == 1
        assert metrics["waitReasons"] == {"ADMISSION_RESOURCES_UNAVAILABLE": 1}
        with get_connection(cfg) as connection:
            waiting_job = connection.execute(
                "SELECT state, attempt_count FROM run_jobs WHERE run_id = ?",
                (waiting_id,),
            ).fetchone()
        assert dict(waiting_job) == {"state": "queued", "attempt_count": 0}
        supervisor._stop_event.set()
        release_file.write_text("release\n", encoding="utf-8")
    finally:
        release_file.write_text("release\n", encoding="utf-8")
        supervisor._stop_event.set()
        supervisor.stop(timeout_seconds=5)


def _config(tmp_path: Path, **overrides: Any) -> RemoteRunnerConfig:
    release_dir = tmp_path / "release"
    _write_file_summary_pipeline(release_dir)
    shim = _write_snakemake_shim(tmp_path)
    values: dict[str, Any] = {
        "token": "phase2-token",
        "data_root": str(tmp_path / "shared"),
        "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
        "uploads_dir": str(tmp_path / "shared" / "uploads"),
        "results_dir": str(tmp_path / "shared" / "results"),
        "work_dir": str(tmp_path / "shared" / "work"),
        "logs_dir": str(tmp_path / "shared" / "logs"),
        "release_dir": str(release_dir),
        "snakemake_command": str(shim),
        "run_worker_slot_count": 2,
        "run_worker_total_cpu": 2,
    }
    values.update(overrides)
    cfg = RemoteRunnerConfig(**values)
    ensure_runtime_layout(cfg)
    return cfg


def _write_snakemake_shim(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "workflow-env" / "bin"
    bin_dir.mkdir(parents=True)
    if os.name == "nt":
        shim = bin_dir / "snakemake.cmd"
        shim.write_text(_WINDOWS_SNAKEMAKE_SHIM, encoding="utf-8", newline="\r\n")
        return shim
    shim = bin_dir / "snakemake"
    shim.write_text(_POSIX_SNAKEMAKE_SHIM, encoding="utf-8", newline="\n")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return shim


def _create_run(cfg: RemoteRunnerConfig, run_id: str) -> str:
    upload = persist_upload(
        cfg,
        filename=f"{run_id}.fastq",
        content_base64="QHJlYWQxCkFDR1QKKwohISEhCg==",
        mime_type="text/plain",
    )
    run_spec = {
        "runId": run_id,
        "projectId": "proj_real_snakemake_acceptance",
        "pipelineId": "file-summary-v1",
        "pipelineVersion": "1.0.0",
        "inputs": [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": "reads"}],
    }
    created = create_run_record(
        cfg,
        server_id="srv_real_snakemake_acceptance",
        request_id=f"req_{run_id}",
        run_spec=run_spec,
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"payload_{run_id}",
    )
    return created.run["runId"]


def _wait_for_started_attempts(barrier_dir: Path, *, expected_count: int, timeout_seconds: float = 15.0) -> None:
    _wait_until(
        lambda: len(list(barrier_dir.glob("*.started"))) >= expected_count,
        timeout_seconds=timeout_seconds,
        message=f"Expected {expected_count} started Snakemake shim attempts.",
    )


def _wait_for_run_status(
    cfg: RemoteRunnerConfig,
    run_id: str,
    status: str,
    *,
    timeout_seconds: float = 15.0,
) -> None:
    _wait_until(
        lambda: (fetch_run(cfg, run_id) or {}).get("status") == status,
        timeout_seconds=timeout_seconds,
        message=f"Expected {run_id} to reach {status}.",
    )


def _wait_for_wait_reason(
    cfg: RemoteRunnerConfig,
    code: str,
    *,
    candidates: list[str],
    timeout_seconds: float = 15.0,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for run_id in candidates:
            if _wait_reason_code(cfg, run_id) == code:
                return run_id
        time.sleep(0.02)
    raise AssertionError(f"Expected wait reason {code}.")


def _wait_until(predicate, *, timeout_seconds: float, message: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(message)


def _running_attempts(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        return [
            dict(row)
            for row in connection.execute(
                """
                SELECT run_id, attempt_id, slot_id, process_group_id
                FROM run_attempts
                WHERE state = 'running'
                ORDER BY slot_id
                """
            ).fetchall()
        ]


def _wait_reason_code(cfg: RemoteRunnerConfig, run_id: str) -> str:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT wait_reason_json FROM run_jobs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return ""
    import json

    payload = json.loads(str(row["wait_reason_json"] or "{}"))
    return str(payload.get("code") or "")


_WINDOWS_SNAKEMAKE_SHIM = r"""@echo off
setlocal EnableDelayedExpansion
if "%~1"=="--version" (
  echo 9.99.0
  exit /b 0
)
set "DRY=0"
set "WORK="
:parse
if "%~1"=="" goto parsed
if "%~1"=="-n" set "DRY=1"
if "%~1"=="--directory" (
  set "WORK=%~2"
  shift
)
shift
goto parse
:parsed
if "%DRY%"=="1" exit /b 0
if "%WORK%"=="" exit /b 2
if "%H2OMETA_TEST_SNAKEMAKE_BARRIER_DIR%"=="" exit /b 3
if not exist "%H2OMETA_TEST_SNAKEMAKE_BARRIER_DIR%" mkdir "%H2OMETA_TEST_SNAKEMAKE_BARRIER_DIR%"
for %%I in ("%WORK%") do set "ATTEMPT=%%~nxI"
echo started>"%H2OMETA_TEST_SNAKEMAKE_BARRIER_DIR%\!ATTEMPT!.started"
:wait_release
if exist "%H2OMETA_TEST_SNAKEMAKE_BARRIER_DIR%\release" goto finish
ping -n 2 127.0.0.1 >nul
goto wait_release
:finish
set "RESULT=!WORK:\work\attempts\=\results\attempts\!"
set "RESULT=!RESULT!\generation-1"
if not exist "!RESULT!" mkdir "!RESULT!"
echo summary !ATTEMPT!>"!RESULT!\done.txt"
exit /b 0
"""


_POSIX_SNAKEMAKE_SHIM = """#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--version"]:
        print("9.99.0")
        return 0
    if "-n" in args:
        return 0
    work = ""
    for index, value in enumerate(args):
        if value == "--directory" and index + 1 < len(args):
            work = args[index + 1]
            break
    barrier = os.environ.get("H2OMETA_TEST_SNAKEMAKE_BARRIER_DIR", "")
    if not work or not barrier:
        return 2
    work_path = Path(work)
    barrier_path = Path(barrier)
    barrier_path.mkdir(parents=True, exist_ok=True)
    attempt = work_path.name
    (barrier_path / f"{attempt}.started").write_text("started\\n", encoding="utf-8")
    while not (barrier_path / "release").exists():
        time.sleep(0.1)
    marker = f"{os.sep}work{os.sep}attempts{os.sep}"
    replacement = f"{os.sep}results{os.sep}attempts{os.sep}"
    result_dir = Path(str(work_path).replace(marker, replacement)) / "generation-1"
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "done.txt").write_text(f"summary {attempt}\\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
