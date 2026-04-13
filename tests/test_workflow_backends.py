from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.workflow.backends import SlurmSSHBackend


@pytest.fixture
def launch() -> SimpleNamespace:
    profile = SimpleNamespace(work_dir="", output_dir="")
    return SimpleNamespace(profile=profile, resume=True)


def test_slurm_submit_run_success(monkeypatch, tmp_path: Path, launch: SimpleNamespace) -> None:
    backend = SlurmSSHBackend()
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    monkeypatch.setattr(
        "core.workflow.backends.materialize_bundle",
        lambda project_dir, run_id, compiled_bundle: {
            "bundle_dir": str(bundle_dir),
            "run_dir": str(tmp_path / run_id),
            "record_path": str(tmp_path / f"{run_id}.json"),
        },
    )
    ensured: list[tuple[list[str], int]] = []
    monkeypatch.setattr("core.workflow.backends.ensure_remote_dirs", lambda fn, dirs, timeout: ensured.append((dirs, timeout)))
    uploads: list[tuple[str, str]] = []
    monkeypatch.setattr("core.workflow.backends.recursive_upload_directory", lambda ssh, local, remote: uploads.append((str(local), remote)))
    monkeypatch.setattr("core.workflow.backends.write_remote_script", lambda fn, path, content, timeout, label: path)

    calls: list[tuple[str, int]] = []

    def ssh_run_fn(cmd: str, timeout: int) -> tuple[int, str, str]:
        calls.append((cmd, timeout))
        if cmd.startswith("sbatch --parsable"):
            return 0, "12345;cluster\n", ""
        if "scheduler_job_id.txt" in cmd:
            return 0, "", ""
        raise AssertionError(f"unexpected command: {cmd}")

    result = backend.submit_run(
        ssh_service=object(),
        ssh_run_fn=ssh_run_fn,
        project_dir=tmp_path,
        remote_base="/remote/base",
        run_id="run-1",
        compiled_bundle={"files": {}},
        launch=launch,
    )

    assert result["scheduler_job_id"] == "12345"
    assert result["remote_task_dir"] == "/remote/base/workflow_runs/run-1"
    assert ensured == [([
        "/remote/base/workflow_runs/run-1",
        "/remote/base/workflow_runs/run-1/bundle",
        "/remote/base/workflow_runs/run-1/work",
        "/remote/base/workflow_runs/run-1/output",
    ], 20)]
    assert uploads == [(str(bundle_dir), "/remote/base/workflow_runs/run-1/bundle")]
    assert any(cmd.startswith("sbatch --parsable") for cmd, _ in calls)


def test_slurm_submit_run_raises_when_job_id_missing(monkeypatch, tmp_path: Path, launch: SimpleNamespace) -> None:
    backend = SlurmSSHBackend()
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    monkeypatch.setattr(
        "core.workflow.backends.materialize_bundle",
        lambda project_dir, run_id, compiled_bundle: {
            "bundle_dir": str(bundle_dir),
            "run_dir": str(tmp_path / run_id),
            "record_path": str(tmp_path / f"{run_id}.json"),
        },
    )
    monkeypatch.setattr("core.workflow.backends.ensure_remote_dirs", lambda fn, dirs, timeout: None)
    monkeypatch.setattr("core.workflow.backends.recursive_upload_directory", lambda ssh, local, remote: None)
    monkeypatch.setattr("core.workflow.backends.write_remote_script", lambda fn, path, content, timeout, label: path)

    def ssh_run_fn(cmd: str, timeout: int) -> tuple[int, str, str]:
        if cmd.startswith("sbatch --parsable"):
            return 0, "\n", ""
        return 0, "", ""

    with pytest.raises(RuntimeError, match="未返回 job id"):
        backend.submit_run(
            ssh_service=object(),
            ssh_run_fn=ssh_run_fn,
            project_dir=tmp_path,
            remote_base="/remote/base",
            run_id="run-2",
            compiled_bundle={"files": {}},
            launch=launch,
        )


def test_slurm_query_run_uses_scheduler_status_and_log_tail() -> None:
    backend = SlurmSSHBackend()
    commands: list[str] = []

    def ssh_run_fn(cmd: str, timeout: int) -> tuple[int, str, str]:
        commands.append(cmd)
        if cmd.startswith("squeue -h -j '12345'"):
            return 0, "RUNNING|00:01:00|compute-1\n", ""
        if cmd.startswith("tail -n 80"):
            return 0, "line-a\nline-b", ""
        if cmd.startswith("sacct"):
            return 0, "", ""
        raise AssertionError(f"unexpected command: {cmd}")

    result = backend.query_run(
        ssh_run_fn=ssh_run_fn,
        row={"remote_task_dir": "/remote/base/workflow_runs/run-3", "scheduler_job_id": "12345"},
    )

    assert result["stage"] == "running"
    assert result["scheduler_job_id"] == "12345"
    assert result["log_tail"] == "line-a\nline-b"
    assert any(cmd.startswith("squeue -h -j '12345'") for cmd in commands)


def test_slurm_query_run_falls_back_to_status_files() -> None:
    backend = SlurmSSHBackend()

    def ssh_run_fn(cmd: str, timeout: int) -> tuple[int, str, str]:
        if cmd.startswith("squeue"):
            return 0, "", ""
        if cmd.startswith("sacct"):
            return 0, "", ""
        if cmd.startswith("printf '__STATUS__"):
            return 0, "__STATUS__\nDONE\n__EXIT__\n0\n__LAUNCHER__\n77\n__HEARTBEAT__\n1712345678\n__LOG__\nrecent log\n", ""
        if cmd.startswith("tail -n 80"):
            return 0, "recent log", ""
        raise AssertionError(f"unexpected command: {cmd}")

    result = backend.query_run(
        ssh_run_fn=ssh_run_fn,
        row={"remote_task_dir": "/remote/base/workflow_runs/run-4", "scheduler_job_id": "12345"},
    )

    assert result["stage"] == "completed"
    assert result["exit_code"] == "0"
    assert result["launcher_pid"] == "77"
    assert result["heartbeat"] == "1712345678"
    assert result["log_tail"] == "recent log"


def test_slurm_cancel_run_scancels_job_and_returns_cancelled() -> None:
    backend = SlurmSSHBackend()

    def ssh_run_fn(cmd: str, timeout: int) -> tuple[int, str, str]:
        if cmd == "scancel 12345":
            return 0, "", ""
        if cmd.startswith("tail -n 80 "):
            return 0, "cancelled by user", ""
        raise AssertionError(f"unexpected command: {cmd}")

    result = backend.cancel_run(
        ssh_run_fn=ssh_run_fn,
        row={"remote_task_dir": "/remote/base/workflow_runs/run-5", "scheduler_job_id": "12345"},
    )

    assert result["stage"] == "cancelled"
    assert result["slurm_state"] == "CANCELLED"
    assert result["scheduler_job_id"] == "12345"
    assert result["log_tail"] == "cancelled by user"
