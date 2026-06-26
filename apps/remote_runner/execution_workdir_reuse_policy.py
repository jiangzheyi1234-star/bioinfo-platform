from __future__ import annotations

from pathlib import Path
from typing import Any


RUN_WORKDIR_REUSE_POLICY_SCHEMA_VERSION = "run-workdir-reuse-policy.v1"


def build_workdir_reuse_policy(
    *,
    attempts: list[dict[str, Any]],
    managed_work_dir: str | Path,
) -> dict[str, Any]:
    latest = _latest_attempt_raw(attempts)
    base = {
        "schemaVersion": RUN_WORKDIR_REUSE_POLICY_SCHEMA_VERSION,
        "available": False,
        "workDirReusable": False,
        "pathExposed": False,
        "managedRoot": True,
        "directoryPresent": False,
        "runConfigPresent": False,
        "snakemakeMetadataPresent": False,
        "latestAttempt": _attempt_ref(latest),
        "blockedReasonCodes": [],
    }
    if latest is None:
        return _blocked(base, "RUN_RESUME_NO_ATTEMPTS")

    managed_root = Path(managed_work_dir).resolve(strict=False)
    work_dir = _path_from(latest.get("workDir"))
    if work_dir is None:
        return _blocked(base, "WORKDIR_EVIDENCE_MISSING")

    try:
        resolved = work_dir.resolve(strict=False)
    except OSError:
        return _blocked(base, "WORKDIR_UNRESOLVABLE")
    if not _inside_root(resolved, managed_root):
        return _blocked({**base, "managedRoot": False}, "WORKDIR_OUTSIDE_MANAGED_ROOT")
    if not resolved.exists():
        return _blocked(base, "WORKDIR_NOT_FOUND")
    if not resolved.is_dir():
        return _blocked(base, "WORKDIR_NOT_DIRECTORY")

    run_config_present = (resolved / "run-config.json").is_file()
    metadata_present = (resolved / ".snakemake").exists()
    ready_base = {
        **base,
        "available": True,
        "directoryPresent": True,
        "runConfigPresent": run_config_present,
        "snakemakeMetadataPresent": metadata_present,
    }
    if not run_config_present:
        return _blocked(ready_base, "RUN_CONFIG_NOT_FOUND")
    return {
        **ready_base,
        "workDirReusable": True,
        "reasonCode": "WORKDIR_REUSABLE",
        "blockedReasonCodes": [],
    }


def _blocked(base: dict[str, Any], reason_code: str) -> dict[str, Any]:
    return {
        **base,
        "reasonCode": reason_code,
        "blockedReasonCodes": [reason_code],
    }


def _attempt_ref(attempt: dict[str, Any] | None) -> dict[str, Any] | None:
    if attempt is None:
        return None
    return {
        "attemptId": attempt.get("attemptId"),
        "attemptNumber": attempt.get("attemptNumber"),
        "leaseGeneration": attempt.get("leaseGeneration"),
        "state": attempt.get("state"),
    }


def _path_from(value: Any) -> Path | None:
    text = str(value or "").strip()
    return Path(text) if text else None


def _inside_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


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
