from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Protocol

from .config import RemoteRunnerConfig, build_workflow_runtime_environment, get_workflow_profile_dir
from .process_runner import ProcessPoll, ProcessStarted, ShouldCancel, run_process


class WorkflowRuntimeCommandError(RuntimeError):
    pass


RULE_RERUN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class WorkflowEngineAdapter(Protocol):
    def dry_run(
        self,
        *,
        snakefile: Path,
        work_dir: Path,
        config_path: Path,
        forcerun_rules: list[str] | None = None,
        rerun_incomplete: bool = False,
        target_paths: list[str] | None = None,
    ) -> Any:
        ...

    def run(
        self,
        *,
        snakefile: Path,
        work_dir: Path,
        config_path: Path,
        event_log_path: Path | None = None,
        forcerun_rules: list[str] | None = None,
        rerun_incomplete: bool = False,
        target_paths: list[str] | None = None,
        on_poll: ProcessPoll | None = None,
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
        forcerun_rules: list[str] | None = None,
        rerun_incomplete: bool = False,
        target_paths: list[str] | None = None,
    ) -> Any:
        return self._execute(
            self._execution_args(
                snakefile=snakefile,
                work_dir=work_dir,
                config_path=config_path,
                forcerun_rules=forcerun_rules,
                rerun_incomplete=rerun_incomplete,
                dry_run=True,
                target_paths=target_paths,
            )
        )

    def run(
        self,
        *,
        snakefile: Path,
        work_dir: Path,
        config_path: Path,
        event_log_path: Path | None = None,
        forcerun_rules: list[str] | None = None,
        rerun_incomplete: bool = False,
        target_paths: list[str] | None = None,
        on_poll: ProcessPoll | None = None,
    ) -> Any:
        return self._execute(
            self._execution_args(
                snakefile=snakefile,
                work_dir=work_dir,
                config_path=config_path,
                event_log_path=event_log_path,
                forcerun_rules=forcerun_rules,
                rerun_incomplete=rerun_incomplete,
                target_paths=target_paths,
            ),
            on_poll=on_poll,
        )

    def _execute(self, command: list[str], *, on_poll: ProcessPoll | None = None) -> Any:
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
            on_poll=on_poll,
            poll_interval_seconds=self._poll_interval_seconds,
        )

    def _execution_args(
        self,
        *,
        snakefile: Path,
        work_dir: Path,
        config_path: Path,
        event_log_path: Path | None = None,
        forcerun_rules: list[str] | None = None,
        rerun_incomplete: bool = False,
        dry_run: bool = False,
        target_paths: list[str] | None = None,
    ) -> list[str]:
        profile_args = self._profile_args()
        normalized_forcerun_rules = normalize_forcerun_rules(forcerun_rules)
        normalized_target_paths = normalize_target_paths(target_paths)
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
        if rerun_incomplete:
            command.append("--rerun-incomplete")
        if normalized_forcerun_rules:
            command.extend(["--forcerun", *normalized_forcerun_rules])
        if dry_run:
            command.append("-n")
        if event_log_path is not None:
            command.extend(
                [
                    "--show-failed-logs",
                    "--logger",
                    "h2ometa",
                    "--logger-h2ometa-event-path",
                    str(event_log_path),
                ]
            )
        command.extend(normalized_target_paths)
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


def normalize_forcerun_rules(rules: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_rule in rules or []:
        rule = str(raw_rule or "").strip()
        if not rule:
            raise WorkflowRuntimeCommandError("SNAKEMAKE_FORCERUN_RULE_REQUIRED")
        if not RULE_RERUN_NAME_RE.fullmatch(rule):
            raise WorkflowRuntimeCommandError(f"SNAKEMAKE_FORCERUN_RULE_INVALID: {rule}")
        if rule not in seen:
            normalized.append(rule)
            seen.add(rule)
    return normalized


def normalize_target_paths(target_paths: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in target_paths or []:
        target_path = str(raw_path or "").strip()
        if not target_path:
            raise WorkflowRuntimeCommandError("SNAKEMAKE_TARGET_PATH_REQUIRED")
        if target_path.startswith("-"):
            raise WorkflowRuntimeCommandError("SNAKEMAKE_TARGET_PATH_INVALID")
        if target_path not in seen:
            normalized.append(target_path)
            seen.add(target_path)
    return normalized
