"""Workflow run backends."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from core.environment.detached_job import ensure_remote_dirs, write_remote_script

from .runtime_ops import (
    cancel_local_nextflow_run,
    download_run_artifacts,
    materialize_bundle,
    query_local_nextflow_run,
    recursive_upload_directory,
    submit_local_nextflow_run,
    _split_marked_sections,
)


class WorkflowBackend:
    backend_kind = "unknown"

    def submit_prepared_run(
        self,
        *,
        ssh_service: Any,
        ssh_run_fn: Any,
        layout: dict[str, str],
        launch: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def submit_run(
        self,
        *,
        ssh_service: Any,
        ssh_run_fn: Any,
        project_dir: Path,
        remote_base: str,
        run_id: str,
        compiled_bundle: dict[str, Any],
        launch: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def query_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def cancel_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def collect_artifacts(
        self,
        *,
        ssh_service: Any,
        project_dir: Path,
        run_id: str,
        row: dict[str, Any],
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class LocalSSHBackend(WorkflowBackend):
    backend_kind = "local_ssh"

    def submit_prepared_run(
        self,
        *,
        ssh_service: Any,
        ssh_run_fn: Any,
        layout: dict[str, str],
        launch: Any,
    ) -> dict[str, Any]:
        recursive_upload_directory(ssh_service, Path(layout["local_bundle_dir"]), layout["remote_bundle_dir"])
        remote_submission = submit_local_nextflow_run(
            ssh_run_fn,
            remote_task_dir=layout["remote_task_dir"],
            remote_bundle_dir=layout["remote_bundle_dir"],
            remote_work_dir=layout["remote_work_dir"],
            remote_output_dir=layout["remote_output_dir"],
            resume=bool(launch.resume),
        )
        return {
            "backend_kind": self.backend_kind,
            "launcher_pid": remote_submission["launcher_pid"],
            "scheduler_job_id": "",
        }

    def submit_run(
        self,
        *,
        ssh_service: Any,
        ssh_run_fn: Any,
        project_dir: Path,
        remote_base: str,
        run_id: str,
        compiled_bundle: dict[str, Any],
        launch: Any,
    ) -> dict[str, Any]:
        layout = prepare_workflow_run_layout(
            project_dir=project_dir,
            remote_base=remote_base,
            run_id=run_id,
            compiled_bundle=compiled_bundle,
            launch=launch,
        )
        return layout | self.submit_prepared_run(
            ssh_service=ssh_service,
            ssh_run_fn=ssh_run_fn,
            layout=layout,
            launch=launch,
        )

    def query_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        remote_task_dir = str(row.get("remote_task_dir") or "").strip()
        if not remote_task_dir:
            raise RuntimeError("workflow run 缺少 remote_task_dir")
        return query_local_nextflow_run(ssh_run_fn, remote_task_dir=remote_task_dir)

    def cancel_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        remote_task_dir = str(row.get("remote_task_dir") or "").strip()
        if not remote_task_dir:
            raise RuntimeError("workflow run 缺少 remote_task_dir")
        return cancel_local_nextflow_run(ssh_run_fn, remote_task_dir=remote_task_dir)

    def collect_artifacts(
        self,
        *,
        ssh_service: Any,
        project_dir: Path,
        run_id: str,
        row: dict[str, Any],
    ) -> list[dict[str, Any]]:
        remote_bundle_dir = str(row.get("remote_bundle_dir") or "").strip()
        remote_output_dir = str(row.get("remote_output_dir") or "").strip()
        return download_run_artifacts(
            ssh_service,
            project_dir=project_dir,
            run_id=run_id,
            remote_bundle_dir=remote_bundle_dir,
            remote_output_dir=remote_output_dir,
        )


class SlurmSSHBackend(WorkflowBackend):
    backend_kind = "slurm_ssh"

    def submit_prepared_run(
        self,
        *,
        ssh_service: Any,
        ssh_run_fn: Any,
        layout: dict[str, str],
        launch: Any,
    ) -> dict[str, Any]:
        ensure_remote_dirs(
            ssh_run_fn,
            [layout["remote_task_dir"], layout["remote_bundle_dir"], layout["remote_work_dir"], layout["remote_output_dir"]],
            timeout=20,
        )
        recursive_upload_directory(ssh_service, Path(layout["local_bundle_dir"]), layout["remote_bundle_dir"])
        script_path = write_remote_script(
            ssh_run_fn,
            f"{layout['remote_task_dir']}/launch.sbatch",
            _build_slurm_launcher(
                remote_task_dir=layout["remote_task_dir"],
                remote_bundle_dir=layout["remote_bundle_dir"],
                remote_work_dir=layout["remote_work_dir"],
                remote_output_dir=layout["remote_output_dir"],
                resume=bool(launch.resume),
            ),
            20,
            label="Slurm launcher script",
        )
        rc, stdout, stderr = ssh_run_fn(f"sbatch --parsable {script_path}", 20)
        if rc != 0:
            raise RuntimeError(f"提交 Slurm workflow 失败: {(stderr or stdout or '').strip()[:200]}")
        scheduler_job_id = _parse_slurm_job_id(stdout or stderr)
        if not scheduler_job_id:
            raise RuntimeError(f"提交 Slurm workflow 后未返回 job id: {(stdout or stderr or '').strip()[:200]}")
        ssh_run_fn(
            f"printf '%s\\n' {shlex.quote(scheduler_job_id)} > {shlex.quote(f'{layout['remote_task_dir']}/scheduler_job_id.txt')}",
            20,
        )
        return {
            "backend_kind": self.backend_kind,
            "launcher_pid": "",
            "scheduler_job_id": scheduler_job_id,
        }

    def submit_run(
        self,
        *,
        ssh_service: Any,
        ssh_run_fn: Any,
        project_dir: Path,
        remote_base: str,
        run_id: str,
        compiled_bundle: dict[str, Any],
        launch: Any,
    ) -> dict[str, Any]:
        layout = prepare_workflow_run_layout(
            project_dir=project_dir,
            remote_base=remote_base,
            run_id=run_id,
            compiled_bundle=compiled_bundle,
            launch=launch,
        )
        return layout | self.submit_prepared_run(
            ssh_service=ssh_service,
            ssh_run_fn=ssh_run_fn,
            layout=layout,
            launch=launch,
        )

    def query_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        remote_task_dir = str(row.get("remote_task_dir") or "").strip()
        if not remote_task_dir:
            raise RuntimeError("workflow run 缺少 remote_task_dir")
        scheduler_job_id = _slurm_job_id_for_row(ssh_run_fn, row)
        status = _query_slurm_job_status(ssh_run_fn, scheduler_job_id)
        if status is None:
            status = _query_slurm_status_files(ssh_run_fn, remote_task_dir)
        if status is None:
            status = {
                "raw_status": "UNKNOWN",
                "stage": "pending",
                "exit_code": "",
                "slurm_state": "",
                "slurm_reason": "",
                "launcher_pid": "",
                "nextflow_pid": "",
                "heartbeat": "",
            }
        log_tail = _query_remote_log_tail(ssh_run_fn, remote_task_dir)
        status["scheduler_job_id"] = scheduler_job_id
        status["log_tail"] = log_tail
        status.setdefault("launcher_pid", "")
        status.setdefault("nextflow_pid", "")
        status.setdefault("heartbeat", "")
        return status

    def cancel_run(self, *, ssh_run_fn: Any, row: dict[str, Any]) -> dict[str, Any]:
        remote_task_dir = str(row.get("remote_task_dir") or "").strip()
        if not remote_task_dir:
            raise RuntimeError("workflow run 缺少 remote_task_dir")
        scheduler_job_id = _slurm_job_id_for_row(ssh_run_fn, row)
        rc, stdout, stderr = ssh_run_fn(f"scancel {shlex.quote(scheduler_job_id)}", 20)
        if rc != 0:
            raise RuntimeError(f"取消 Slurm workflow 失败: {(stderr or stdout or '').strip()[:200]}")
        log_tail = _query_remote_log_tail(ssh_run_fn, remote_task_dir)
        return {
            "raw_status": "CANCELLED",
            "stage": "cancelled",
            "exit_code": "130",
            "slurm_state": "CANCELLED",
            "slurm_reason": "user_request",
            "scheduler_job_id": scheduler_job_id,
            "launcher_pid": "",
            "nextflow_pid": "",
            "log_tail": log_tail,
        }

    def collect_artifacts(
        self,
        *,
        ssh_service: Any,
        project_dir: Path,
        run_id: str,
        row: dict[str, Any],
    ) -> list[dict[str, Any]]:
        remote_bundle_dir = str(row.get("remote_bundle_dir") or "").strip()
        remote_output_dir = str(row.get("remote_output_dir") or "").strip()
        return download_run_artifacts(
            ssh_service,
            project_dir=project_dir,
            run_id=run_id,
            remote_bundle_dir=remote_bundle_dir,
            remote_output_dir=remote_output_dir,
        )


def create_workflow_backend(profile: Any) -> WorkflowBackend:
    executor = str(getattr(profile, "executor", "") or "").strip()
    if executor == "local":
        return LocalSSHBackend()
    if executor == "slurm":
        return SlurmSSHBackend()
    raise RuntimeError(f"不支持的 workflow executor: {executor or '<empty>'}")


def prepare_workflow_run_layout(
    *,
    project_dir: Path,
    remote_base: str,
    run_id: str,
    compiled_bundle: dict[str, Any],
    launch: Any,
) -> dict[str, str]:
    local_layout = materialize_bundle(project_dir, run_id, compiled_bundle)
    remote_task_dir = f"{remote_base}/workflow_runs/{run_id}"
    remote_bundle_dir = f"{remote_task_dir}/bundle"
    remote_work_dir = launch.profile.work_dir or f"{remote_task_dir}/work"
    remote_output_dir = launch.profile.output_dir or f"{remote_task_dir}/output"
    return {
        "local_bundle_dir": local_layout["bundle_dir"],
        "local_run_dir": local_layout["run_dir"],
        "local_record_path": local_layout["record_path"],
        "resolved_config_path": str(Path(local_layout["bundle_dir"]) / "resolved.config"),
        "remote_task_dir": remote_task_dir,
        "remote_bundle_dir": remote_bundle_dir,
        "remote_work_dir": remote_work_dir,
        "remote_output_dir": remote_output_dir,
    }


def _build_slurm_launcher(
    *,
    remote_task_dir: str,
    remote_bundle_dir: str,
    remote_work_dir: str,
    remote_output_dir: str,
    resume: bool,
) -> str:
    task_dir = _shell_expr(remote_task_dir)
    bundle_dir = _shell_expr(remote_bundle_dir)
    work_dir = _shell_expr(remote_work_dir)
    output_dir = _shell_expr(remote_output_dir)
    resume_line = "  -resume \\\n" if resume else ""
    return f"""#!/bin/bash
set -euo pipefail

TASK_DIR={task_dir}
BUNDLE_DIR={bundle_dir}
WORK_DIR={work_dir}
OUTPUT_DIR={output_dir}
STATUS_FILE="$TASK_DIR/status.txt"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"
JOB_ID_FILE="$TASK_DIR/scheduler_job_id.txt"
LAUNCHER_PID_FILE="$TASK_DIR/launcher.pid"
LOG_FILE="$TASK_DIR/task.log"
CANCEL_FILE="$TASK_DIR/cancel_requested"

mkdir -p "$TASK_DIR" "$BUNDLE_DIR" "$WORK_DIR" "$OUTPUT_DIR"
echo "PENDING" > "$STATUS_FILE"
echo "$$" > "$LAUNCHER_PID_FILE"
echo "${{SLURM_JOB_ID:-}}" > "$JOB_ID_FILE"
exec > "$LOG_FILE" 2>&1

_heartbeat() {{
  while true; do
    date +%s > "$HEARTBEAT_FILE"
    sleep 15
  done
}}
_heartbeat &
HB_PID=$!

_forward_cancel() {{
  touch "$CANCEL_FILE"
}}
trap _forward_cancel INT TERM

_cleanup() {{
  local ec=$?
  kill "$HB_PID" 2>/dev/null || true
  if [ -f "$CANCEL_FILE" ] || [ "$ec" -eq 130 ]; then
    ec=130
  fi
  echo "$ec" > "$EXIT_CODE_FILE"
  if [ "$ec" -eq 130 ]; then
    echo "CANCELLED" > "$STATUS_FILE"
  elif [ "$ec" -eq 0 ]; then
    echo "DONE" > "$STATUS_FILE"
  else
    echo "FAILED" > "$STATUS_FILE"
  fi
}}
trap _cleanup EXIT

cd "$BUNDLE_DIR"
echo "RUNNING" > "$STATUS_FILE"

nextflow -C resolved.config run main.nf \\
  -params-file params/run.yaml \\
  -work-dir "$WORK_DIR" \\
{resume_line}  -with-report report.html \\
  -with-timeline timeline.html \\
  -with-trace trace.txt \\
  -with-dag dag.html
"""


def _shell_expr(path: str) -> str:
    normalized = str(path or "").strip()
    if not normalized:
        return '""'
    home_expr = normalized.replace("~", "$HOME")
    return f'"$(eval echo {home_expr})"'


def _parse_slurm_job_id(text: str) -> str:
    candidate = str(text or "").strip().splitlines()
    if not candidate:
        return ""
    first = candidate[0].strip()
    if not first:
        return ""
    return first.split(";", 1)[0].strip()


def _slurm_job_id_for_row(ssh_run_fn: Any, row: dict[str, Any], timeout: int = 15) -> str:
    scheduler_job_id = str(row.get("scheduler_job_id") or "").strip()
    if scheduler_job_id:
        return scheduler_job_id
    remote_task_dir = str(row.get("remote_task_dir") or "").strip()
    if not remote_task_dir:
        raise RuntimeError("workflow run 缺少 scheduler_job_id")
    command = f"cat {shlex.quote(f'{remote_task_dir}/scheduler_job_id.txt')} 2>/dev/null || true"
    rc, stdout, stderr = ssh_run_fn(command, timeout)
    if rc != 0:
        raise RuntimeError(f"读取 Slurm job id 失败: {(stderr or stdout or '').strip()[:200]}")
    scheduler_job_id = str(stdout or "").strip()
    if not scheduler_job_id:
        raise RuntimeError("workflow run 缺少 scheduler_job_id")
    return scheduler_job_id


def _query_slurm_job_status(ssh_run_fn: Any, scheduler_job_id: str, timeout: int = 15) -> dict[str, Any] | None:
    quoted_scheduler_job_id = _single_quoted_shell_arg(scheduler_job_id)
    squeue_cmd = (
        "squeue -h -j "
        + quoted_scheduler_job_id
        + " -o "
        + shlex.quote("%T|%M|%R")
    )
    rc, stdout, stderr = ssh_run_fn(squeue_cmd, timeout)
    if rc == 0 and str(stdout or "").strip():
        return _parse_slurm_queue_line(scheduler_job_id, str(stdout))
    sacct_cmd = (
        "sacct -n -P -X -j "
        + quoted_scheduler_job_id
        + " -o "
        + shlex.quote("JobIDRaw,State,ExitCode,Elapsed,MaxRSS,NodeList")
    )
    rc, stdout, stderr = ssh_run_fn(sacct_cmd, timeout)
    if rc != 0 or not str(stdout or "").strip():
        return None
    return _parse_slurm_accounting(scheduler_job_id, str(stdout))


def _parse_slurm_queue_line(scheduler_job_id: str, text: str) -> dict[str, Any]:
    line = next((item.strip() for item in text.splitlines() if item.strip()), "")
    if not line:
        return {}
    parts = [part.strip() for part in line.split("|")]
    state = parts[0] if parts else ""
    elapsed = parts[1] if len(parts) > 1 else ""
    reason = parts[2] if len(parts) > 2 else ""
    stage = _map_slurm_state_to_stage(state)
    payload = {
        "raw_status": state or "UNKNOWN",
        "stage": stage,
        "exit_code": "",
        "slurm_state": state or "",
        "slurm_reason": reason or "",
        "scheduler_job_id": scheduler_job_id,
        "elapsed": elapsed or "",
        "launcher_pid": "",
        "nextflow_pid": "",
        "heartbeat": "",
    }
    if stage in {"completed", "failed", "cancelled"}:
        payload["exit_code"] = "0" if stage == "completed" else "1"
    return payload


def _parse_slurm_accounting(scheduler_job_id: str, text: str) -> dict[str, Any] | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = [part.strip() for part in stripped.split("|")]
        if not parts:
            continue
        job_id = parts[0]
        state = parts[1] if len(parts) > 1 else ""
        exit_code = parts[2] if len(parts) > 2 else ""
        elapsed = parts[3] if len(parts) > 3 else ""
        if job_id != scheduler_job_id and job_id.split(".", 1)[0] != scheduler_job_id:
            continue
        stage = _map_slurm_state_to_stage(state)
        payload = {
            "raw_status": state or "UNKNOWN",
            "stage": stage,
            "exit_code": exit_code.split(":", 1)[0] if exit_code else "",
            "slurm_state": state or "",
            "slurm_reason": "",
            "scheduler_job_id": scheduler_job_id,
            "elapsed": elapsed or "",
            "launcher_pid": "",
            "nextflow_pid": "",
            "heartbeat": "",
        }
        return payload
    return None


def _query_slurm_status_files(ssh_run_fn: Any, remote_task_dir: str, timeout: int = 15) -> dict[str, Any] | None:
    command = (
        "printf '__STATUS__\\n'; cat "
        + shlex.quote(f"{remote_task_dir}/status.txt")
        + " 2>/dev/null || true; "
        "printf '__EXIT__\\n'; cat "
        + shlex.quote(f"{remote_task_dir}/exit_code.txt")
        + " 2>/dev/null || true; "
        "printf '__LAUNCHER__\\n'; cat "
        + shlex.quote(f"{remote_task_dir}/launcher.pid")
        + " 2>/dev/null || true; "
        "printf '__HEARTBEAT__\\n'; cat "
        + shlex.quote(f"{remote_task_dir}/heartbeat.txt")
        + " 2>/dev/null || true; "
        "printf '__LOG__\\n'; tail -n 60 "
        + shlex.quote(f"{remote_task_dir}/task.log")
        + " 2>/dev/null || true"
    )
    rc, stdout, stderr = ssh_run_fn(command, timeout)
    if rc != 0:
        return None
    sections = _split_marked_sections(stdout)
    raw_status = str(sections.get("__STATUS__", "")).strip().upper()
    if not raw_status:
        return None
    stage = _map_slurm_state_to_stage(raw_status)
    exit_code = str(sections.get("__EXIT__", "")).strip()
    return {
        "raw_status": raw_status,
        "stage": stage,
        "exit_code": exit_code,
        "slurm_state": raw_status,
        "slurm_reason": "",
        "scheduler_job_id": "",
        "launcher_pid": str(sections.get("__LAUNCHER__", "")).strip(),
        "nextflow_pid": "",
        "heartbeat": str(sections.get("__HEARTBEAT__", "")).strip(),
    }


def _query_remote_log_tail(ssh_run_fn: Any, remote_task_dir: str, timeout: int = 15) -> str:
    command = "tail -n 80 " + shlex.quote(f"{remote_task_dir}/task.log") + " 2>/dev/null || true"
    rc, stdout, stderr = ssh_run_fn(command, timeout)
    if rc != 0:
        return ""
    return str(stdout or "").strip()


def _single_quoted_shell_arg(value: str) -> str:
    return "'" + str(value or "").replace("'", "'\"'\"'") + "'"


def _map_slurm_state_to_stage(state: str) -> str:
    normalized = str(state or "").strip().upper()
    if not normalized:
        return "pending"
    if normalized.startswith("PENDING") or normalized in {"CONFIGURING", "REQUEUED", "REQUEUE_FED", "SUSPENDED"}:
        return "pending"
    if normalized in {"RUNNING", "COMPLETING", "STAGE_OUT"}:
        return "running"
    if normalized in {"COMPLETED", "DONE"}:
        return "completed"
    if normalized.startswith("CANCELLED") or normalized.startswith("CANCELLED+") or normalized.startswith("CANCELLED_BY"):
        return "cancelled"
    if normalized in {"FAILED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY", "BOOT_FAIL", "PREEMPTED"}:
        return "failed"
    return "running" if normalized not in {"UNKNOWN"} else "pending"
