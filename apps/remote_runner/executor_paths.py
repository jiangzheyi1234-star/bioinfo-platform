from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .config import RemoteRunnerConfig
from .run_execution_storage import record_run_attempt_process_group


def _process_group_recorder(
    cfg: RemoteRunnerConfig,
    *,
    attempt_id: str | None,
    lease_generation: int | None,
) -> Callable[[int], None] | None:
    if not str(attempt_id or "").strip() or lease_generation is None:
        return None

    def record(process_group_id: int) -> None:
        record_run_attempt_process_group(
            cfg,
            str(attempt_id),
            lease_generation=int(lease_generation),
            process_group_id=str(process_group_id),
        )

    return record


def _resolve_execution_work_dir(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_work_dir: str | None,
) -> Path:
    has_attempt_context = any(
        value is not None and str(value).strip()
        for value in (attempt_id, lease_generation, attempt_work_dir)
    )
    if not has_attempt_context:
        return Path(cfg.work_dir) / run_id
    if not str(attempt_id or "").strip():
        raise ValueError("RUN_ATTEMPT_ID_REQUIRED")
    if lease_generation is None:
        raise ValueError("RUN_LEASE_GENERATION_REQUIRED")
    normalized_work_dir = str(attempt_work_dir or "").strip()
    if not normalized_work_dir:
        raise ValueError("RUN_ATTEMPT_WORK_DIR_REQUIRED")
    return Path(normalized_work_dir)


def _resolve_execution_result_dir(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
) -> Path:
    if attempt_id is None and lease_generation is None:
        return Path(cfg.results_dir) / run_id
    if not str(attempt_id or "").strip():
        raise ValueError("RUN_ATTEMPT_ID_REQUIRED")
    if lease_generation is None:
        raise ValueError("RUN_LEASE_GENERATION_REQUIRED")
    return Path(cfg.results_dir) / "attempts" / str(attempt_id) / f"generation-{int(lease_generation)}"
