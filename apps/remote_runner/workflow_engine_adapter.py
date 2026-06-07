from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, Protocol

from .config import RemoteRunnerConfig, build_workflow_runtime_environment, get_workflow_profile_dir
from .process_runner import ProcessStarted, ShouldCancel, run_process


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
        should_cancel: ShouldCancel | None = None,
        on_process_started: ProcessStarted | None = None,
        poll_interval_seconds: float = 0.2,
    ) -> None:
        self._cfg = cfg
        self._run_command = run_command
        self._should_cancel = should_cancel
        self._on_process_started = on_process_started
        self._poll_interval_seconds = poll_interval_seconds

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
        env = build_workflow_runtime_environment(self._cfg)
        if self._run_command is not None:
            return self._run_command(
                command,
                capture_output=True,
                text=True,
                env=env,
            )
        return run_process(
            command,
            env=env,
            should_cancel=self._should_cancel,
            on_process_started=self._on_process_started,
            poll_interval_seconds=self._poll_interval_seconds,
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
