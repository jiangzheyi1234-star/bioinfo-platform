from __future__ import annotations

from typing import Any

from .execution_plan_hash import attach_plan_hash
from .execution_output_audit import build_attempt_output_audit


RUN_RESUME_PLAN_SCHEMA_VERSION = "run-resume-plan.v1"
SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_VERSION = "snakemake-run-resume-options.v1"
RUN_RESUME_EXECUTION_BLOCKERS = [
    "RUN_RESUME_MUTATION_API_DISABLED",
    "WORKDIR_REUSE_POLICY_UNPROVEN",
    "INCOMPLETE_OUTPUT_AUDIT_UNPROVEN",
    "ARTIFACT_ADOPTION_UNPROVEN",
]
UNSAFE_SNAKEMAKE_RESUME_FLAGS = ["--forceall", "--touch", "--ignore-incomplete"]
RESUMABLE_RUN_STATUSES = {"failed", "canceled", "cancelled"}
TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled", "cancelled"}
TERMINAL_JOB_STATES = {"completed", "failed", "canceled", "cancelled"}
RESUMABLE_ATTEMPT_STATES = {"failed", "fenced", "canceled", "cancelled"}


def build_run_resume_plan(
    *,
    run: dict[str, Any],
    job: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
    active_lease: dict[str, Any] | None,
    managed_work_dir: str,
    managed_results_dir: str,
) -> dict[str, Any]:
    base = _base_plan(
        run,
        job=job,
        attempts=attempts,
        managed_work_dir=managed_work_dir,
        managed_results_dir=managed_results_dir,
    )
    latest_attempt = base["latestAttempt"]
    if active_lease is not None:
        return _blocked(base, "ACTIVE_LEASE")
    if job is None:
        return _blocked(base, "JOB_NOT_FOUND")
    if not str(run.get("workflowRevisionId") or "").strip():
        return _blocked(base, "WORKFLOW_REVISION_MISSING")
    if not attempts:
        return _blocked(base, "RUN_RESUME_NO_ATTEMPTS")
    if job.get("deadLetteredAt"):
        return _blocked(base, "RUN_RESUME_DEAD_LETTERED")
    run_status = str(run.get("status") or "").lower()
    job_state = str(job.get("state") or "").lower()
    latest_state = str((latest_attempt or {}).get("state") or "").lower()
    if run_status not in TERMINAL_RUN_STATUSES or job_state not in TERMINAL_JOB_STATES:
        return _blocked(base, "RUN_RESUME_REQUIRES_TERMINAL_RUN_AND_JOB")
    if run_status not in RESUMABLE_RUN_STATUSES:
        return _blocked(base, "RUN_NOT_RESUMABLE_TERMINAL")
    if latest_state not in RESUMABLE_ATTEMPT_STATES:
        return _blocked(base, "RUN_RESUME_LATEST_ATTEMPT_NOT_RESUMABLE")
    return attach_plan_hash(
        {
            **base,
            "eligible": False,
            "eligibleNow": False,
            "commandPreviewAvailable": True,
            "reasonCode": "RUN_RESUME_PREVIEW_AVAILABLE",
            "message": (
                "Snakemake resume semantics are available for planning via --rerun-incomplete, "
                "but execution remains disabled until workdir reuse and incomplete-output audit policies are proven."
            ),
            "snakemakeOptions": _snakemake_options(preview=True),
        }
    )


def _base_plan(
    run: dict[str, Any],
    *,
    job: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
    managed_work_dir: str,
    managed_results_dir: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": RUN_RESUME_PLAN_SCHEMA_VERSION,
        "runId": run.get("runId"),
        "workflowRevisionId": run.get("workflowRevisionId"),
        "strategy": "snakemake-rerun-incomplete",
        "supported": False,
        "eligible": False,
        "eligibleNow": False,
        "executionEnabled": False,
        "executionReasonCode": "RUN_RESUME_EXECUTION_DISABLED",
        "commandPreviewAvailable": False,
        "runStatus": run.get("status"),
        "jobState": job.get("state") if job else None,
        "attemptCount": len(attempts),
        "latestAttempt": _latest_attempt(attempts),
        "workdirEvidence": _workdir_evidence(attempts),
        "incompleteOutputAudit": build_attempt_output_audit(
            run=run,
            attempts=attempts,
            managed_work_dir=managed_work_dir,
            managed_results_dir=managed_results_dir,
        ),
        "artifactAdoptionBoundary": _artifact_adoption_boundary(),
        "blockedReasonCodes": list(RUN_RESUME_EXECUTION_BLOCKERS),
        "requiresBeforeExecution": list(RUN_RESUME_EXECUTION_BLOCKERS),
        "snakemakeOptions": _snakemake_options(preview=False),
    }


def _blocked(base: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return attach_plan_hash(
        {
            **base,
            "reasonCode": reason_code,
            "message": f"Run resume execution planning is blocked: {reason_code}.",
            "blockedReasonCodes": _unique_strings([reason_code, *base["blockedReasonCodes"]]),
        }
    )


def _snakemake_options(*, preview: bool) -> dict[str, Any]:
    args_preview = ["--rerun-incomplete"] if preview else []
    return {
        "schemaVersion": SNAKEMAKE_RUN_RESUME_OPTIONS_SCHEMA_VERSION,
        "rerunIncomplete": preview,
        "argsPreview": args_preview,
        "unsafeFlagsProhibited": UNSAFE_SNAKEMAKE_RESUME_FLAGS,
    }


def _latest_attempt(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not attempts:
        return None
    latest = max(
        attempts,
        key=lambda attempt: (
            _optional_int(attempt.get("attemptNumber")),
            _optional_int(attempt.get("leaseGeneration")),
            str(attempt.get("updatedAt") or ""),
        ),
    )
    return {
        "attemptId": latest.get("attemptId"),
        "attemptNumber": latest.get("attemptNumber"),
        "leaseGeneration": latest.get("leaseGeneration"),
        "state": latest.get("state"),
        "exitCode": latest.get("exitCode"),
        "finishedAt": latest.get("finishedAt"),
    }


def _workdir_evidence(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    latest = _latest_attempt_raw(attempts)
    workdir_present = bool(latest and latest.get("workDirPresent"))
    return {
        "available": workdir_present,
        "workDirReusable": False,
        "pathExposed": False,
        "reasonCode": "WORKDIR_REUSE_POLICY_UNPROVEN" if workdir_present else "WORKDIR_EVIDENCE_MISSING",
    }


def _artifact_adoption_boundary() -> dict[str, Any]:
    return {
        "enabled": False,
        "adoptedArtifacts": [],
        "adoptedCacheEntries": [],
        "reasonCode": "ARTIFACT_ADOPTION_UNPROVEN",
    }


def _latest_attempt_raw(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not attempts:
        return None
    return max(
        attempts,
        key=lambda attempt: (
            _optional_int(attempt.get("attemptNumber")),
            _optional_int(attempt.get("leaseGeneration")),
            str(attempt.get("updatedAt") or ""),
        ),
    )


def _optional_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return unique
