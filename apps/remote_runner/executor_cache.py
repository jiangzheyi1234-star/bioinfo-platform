from __future__ import annotations

from typing import Any

from .artifact_cache_adoption import try_adopt_cached_outputs
from .config import RemoteRunnerConfig
from .rule_execution_projection import mark_run_rules_cached
from .storage import append_log_lines, update_run_state


def try_complete_from_artifact_cache(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    run_spec: dict[str, Any],
    execution_options: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None,
    run_outputs: dict[str, str] | None,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    result_dir: str,
) -> dict[str, Any]:
    if _run_resume_requested(execution_options):
        return _not_adopted("run_resume_cache_adoption_unavailable")
    if _rule_rerun_requested(execution_options):
        return _not_adopted("rule_rerun_cache_adoption_unavailable")
    if not str(attempt_id or "").strip() or lease_generation is None:
        return _not_adopted("attempt_context_required")
    if not str(run_spec.get("workflowRevisionId") or "").strip():
        return _not_adopted("workflow_revision_missing")
    update_run_state(
        cfg,
        run_id=run_id,
        status="running",
        stage="cache",
        message="Checking artifact cache.",
        request_id=request_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    adoption = try_adopt_cached_outputs(
        cfg,
        run_id=run_id,
        request_id=request_id,
        run_spec=run_spec,
        output_schema=output_schema,
        outputs=run_outputs,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        result_dir=result_dir,
    )
    if not adoption["adopted"]:
        return adoption
    mark_run_rules_cached(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        occurred_at=str(adoption["adoptedAt"]),
    )
    append_log_lines(
        cfg,
        run_id,
        "stdout",
        [
            (
                "Artifact cache hit: adopted "
                f"{len(adoption['artifactIds'])} cached output artifact(s)."
            )
        ],
    )
    return adoption


def _not_adopted(reason: str) -> dict[str, Any]:
    return {"adopted": False, "reason": reason}


def _rule_rerun_requested(execution_options: dict[str, Any] | None) -> bool:
    if not isinstance(execution_options, dict):
        return False
    snakemake = execution_options.get("snakemake")
    if not isinstance(snakemake, dict):
        return False
    return (
        snakemake.get("schemaVersion") == "snakemake-rule-rerun-options.v1"
        or bool(snakemake.get("forcerunRules"))
    )


def _run_resume_requested(execution_options: dict[str, Any] | None) -> bool:
    if not isinstance(execution_options, dict):
        return False
    snakemake = execution_options.get("snakemake")
    if not isinstance(snakemake, dict):
        return False
    return snakemake.get("schemaVersion") == "snakemake-run-resume-options.v1"
