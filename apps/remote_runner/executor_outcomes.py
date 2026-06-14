from __future__ import annotations

import time

from .config import RemoteRunnerConfig
from .storage import update_run_state


def _mark_failed(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    message: str,
    scope: str,
    stderr: str,
    code: str | None = None,
    result_dir: str = "",
    attempt_id: str | None = None,
    lease_generation: int | None = None,
) -> None:
    update_run_state(
        cfg,
        run_id=run_id,
        status="failed",
        stage=scope,
        message=message,
        request_id=request_id,
        result_dir=result_dir,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        last_error={
            "code": code or ("WORKFLOW_RUNTIME_MISSING" if scope == "validate" else "WORKFLOW_EXECUTION_FAILED"),
            "message": stderr.strip() or message,
            "requestId": request_id,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scope": scope,
            "stage": scope,
        },
    )


def _mark_cancelled(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    stderr: str,
    result_dir: str = "",
    attempt_id: str | None = None,
    lease_generation: int | None = None,
) -> None:
    update_run_state(
        cfg,
        run_id=run_id,
        status="canceled",
        stage="cancel",
        message="Run execution cancelled.",
        request_id=request_id,
        result_dir=result_dir,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        last_error={
            "code": "RUN_CANCELLED",
            "message": stderr.strip() or "Run execution cancelled.",
            "requestId": request_id,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scope": "workflow",
            "stage": "cancel",
        },
    )
