from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Protocol

from .config import RemoteRunnerConfig, build_workflow_runtime_environment, get_workflow_profile_dir


class WorkflowRuntimeCommandError(RuntimeError):
    pass


class WorkflowEngineAdapter(Protocol):
    def dry_run(
        self,
        *,
        snakefile: Path,
        work_dir: Path,
        config_path: Path,
    ) -> Any:
        ...

    def run(
        self,
        *,
        snakefile: Path,
        work_dir: Path,
        config_path: Path,
    ) -> Any:
        ...


class SnakemakeEngineAdapter:
    def __init__(
        self,
        cfg: RemoteRunnerConfig,
        *,
        run_command: Callable[..., Any] | None = None,
    ) -> None:
        self._cfg = cfg
        self._run_command = run_command

    def dry_run(
        self,
        *,
        snakefile: Path,
        work_dir: Path,
        config_path: Path,
    ) -> Any:
        return self._execute(
            [*self._execution_args(snakefile=snakefile, work_dir=work_dir, config_path=config_path), "-n"]
        )

    def run(
        self,
        *,
        snakefile: Path,
        work_dir: Path,
        config_path: Path,
    ) -> Any:
        return self._execute(
            self._execution_args(snakefile=snakefile, work_dir=work_dir, config_path=config_path)
        )

    def _execute(self, command: list[str]) -> Any:
        run_command = self._run_command or subprocess.run
        return run_command(
            command,
            capture_output=True,
            text=True,
            env=build_workflow_runtime_environment(self._cfg),
        )

    def _execution_args(
        self,
        *,
        snakefile: Path,
        work_dir: Path,
        config_path: Path,
    ) -> list[str]:
        profile_args = self._profile_args()
        command = [
            *self._snakemake_command(),
            "--snakefile",
            str(snakefile),
            "--directory",
            str(work_dir),
        ]
        if profile_args:
            command.extend(profile_args)
        else:
            command.extend(["--cores", "1", "--use-conda"])
        command.extend(["--configfile", str(config_path)])
        return command

    def _snakemake_command(self) -> list[str]:
        snakemake_command = str(self._cfg.snakemake_command or "").strip()
        if not snakemake_command:
            raise WorkflowRuntimeCommandError("snakemake command not configured")
        return [snakemake_command]

    def _profile_args(self) -> list[str]:
        workflow_profile_dir = get_workflow_profile_dir(self._cfg)
        if workflow_profile_dir is None:
            return []
        return ["--workflow-profile", str(workflow_profile_dir)]
