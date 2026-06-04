from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig, build_workflow_runtime_environment, get_workflow_profile_dir
from .snakemake_execution_lock import SNAKEMAKE_EXECUTION_LOCK


def run_snakemake(
    cfg: RemoteRunnerConfig,
    *,
    snakefile: Path,
    work_dir: Path,
    config_path: Path,
    dry_run: bool,
    timeout: int,
) -> dict[str, Any]:
    command = _snakemake_execution_args(cfg, snakefile=snakefile, work_dir=work_dir, config_path=config_path)
    if dry_run:
        command.append("-n")
    try:
        with SNAKEMAKE_EXECUTION_LOCK:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=build_workflow_runtime_environment(cfg),
            )
    except (OSError, subprocess.SubprocessError) as exc:
        log_path = _write_run_log(work_dir, dry_run=dry_run, stdout="", stderr=str(exc))
        return {"returncode": 127, "message": str(exc) or "Failed to launch Snakemake.", "logPath": str(log_path)}
    log_path = _write_run_log(work_dir, dry_run=dry_run, stdout=result.stdout or "", stderr=result.stderr or "")
    return {
        "returncode": int(result.returncode),
        "message": _tail(result.stderr or result.stdout or ""),
        "logPath": str(log_path),
    }


def snakemake_event_details(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "returncode": str(result.get("returncode", "")),
        "logPath": str(result.get("logPath") or ""),
        "tail": str(result.get("message") or ""),
    }


def _snakemake_execution_args(
    cfg: RemoteRunnerConfig,
    *,
    snakefile: Path,
    work_dir: Path,
    config_path: Path,
) -> list[str]:
    snakemake_command = str(cfg.snakemake_command or "").strip()
    if not snakemake_command:
        raise RuntimeError("snakemake command not configured")
    command = [snakemake_command, "--snakefile", str(snakefile), "--directory", str(work_dir)]
    workflow_profile_dir = get_workflow_profile_dir(cfg)
    if workflow_profile_dir is not None:
        command.extend(["--workflow-profile", str(workflow_profile_dir)])
    else:
        command.extend(["--cores", "1", "--use-conda"])
    command.extend(["--configfile", str(config_path)])
    return command


def _tail(text: str) -> str:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(lines[-20:]) if lines else ""


def _write_run_log(work_dir: Path, *, dry_run: bool, stdout: str, stderr: str) -> Path:
    log_dir = work_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / ("dry-run.log" if dry_run else "smoke-run.log")
    log_path.write_text(f"[stdout]\n{stdout}\n[stderr]\n{stderr}\n", encoding="utf-8")
    return log_path
