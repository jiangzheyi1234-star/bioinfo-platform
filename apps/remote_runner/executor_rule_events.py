from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .snakemake_rule_event_projection import SnakemakeRuleEventProjector
from .storage import append_log_lines


def run_snakemake_with_rule_events(
    cfg: RemoteRunnerConfig,
    engine: Any,
    *,
    snakefile: Path,
    work_dir: Path,
    config_path: Path,
    event_log_path: Path,
    stdout_log: Path,
    stderr_log: Path,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    forcerun_rules: list[str] | None = None,
    rerun_incomplete: bool = False,
    target_paths: list[str] | None = None,
) -> tuple[Any, dict[str, Any]]:
    projector = SnakemakeRuleEventProjector(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        event_log_path=event_log_path,
    )
    result = engine.run(
        snakefile=snakefile,
        work_dir=work_dir,
        config_path=config_path,
        event_log_path=event_log_path,
        forcerun_rules=forcerun_rules,
        rerun_incomplete=rerun_incomplete,
        target_paths=target_paths,
        on_poll=projector.poll,
    )
    stdout_log.write_text(result.stdout or "", encoding="utf-8")
    stderr_log.write_text(result.stderr or "", encoding="utf-8")
    append_log_lines(cfg, run_id, "stdout", [line for line in result.stdout.splitlines() if line])
    append_log_lines(cfg, run_id, "stderr", [line for line in result.stderr.splitlines() if line])
    projection = projector.finalize(workflow_succeeded=result.returncode == 0)
    return result, projection
