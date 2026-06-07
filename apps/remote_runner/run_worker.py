from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .config import RemoteRunnerConfig
from .executor import run_snakemake_execution
from .storage import (
    claim_next_run_job,
    complete_run_attempt,
    fetch_run,
    heartbeat_run_attempt,
    now_iso,
    run_attempt_cancel_requested,
    update_run_state,
)
from .workflow_run_storage import StaleRunAttemptError


RunExecutorWithKeywords = Callable[..., None]
NowFactory = Callable[[], str]
AttemptCallback = Callable[[dict[str, Any]], None]


def process_next_run_job(
    cfg: RemoteRunnerConfig,
    *,
    worker_id: str,
    execute_run: RunExecutorWithKeywords | None = None,
    lease_seconds: int = 60,
    heartbeat_interval_seconds: float = 15.0,
    now_factory: NowFactory = now_iso,
    on_attempt_claimed: AttemptCallback | None = None,
    on_attempt_finished: AttemptCallback | None = None,
) -> dict[str, Any]:
    claim = claim_next_run_job(
        cfg,
        worker_id=worker_id,
        now=now_factory(),
        lease_seconds=lease_seconds,
    )
    if claim is None:
        return {"claimed": False}

    attempt_id = str(claim["attemptId"])
    lease_generation = int(claim["leaseGeneration"])
    run_id = str(claim["runId"])
    run = fetch_run(cfg, run_id)
    if run is None:
        raise KeyError(run_id)
    if on_attempt_claimed is not None:
        on_attempt_claimed(claim)

    heartbeat = heartbeat_run_attempt(
        cfg,
        attempt_id,
        lease_generation=lease_generation,
        now=now_factory(),
        lease_seconds=lease_seconds,
    )
    stop_heartbeat = threading.Event()
    heartbeat_thread = _start_heartbeat_thread(
        cfg,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        lease_seconds=lease_seconds,
        interval_seconds=heartbeat_interval_seconds,
        now_factory=now_factory,
        stop_event=stop_heartbeat,
    )
    execution_error = ""
    try:
        executor = execute_run or run_snakemake_execution
        executor_kwargs: dict[str, Any] = {
            "run_id": run_id,
            "request_id": str(run["requestId"]),
            "run_spec": dict(run["runSpec"] or {}),
            "attempt_id": attempt_id,
            "lease_generation": lease_generation,
            "attempt_work_dir": str(claim["attempt"]["workDir"]),
        }
        if execute_run is None:
            def should_cancel_attempt() -> bool:
                return stop_heartbeat.is_set() or run_attempt_cancel_requested(
                    cfg,
                    attempt_id,
                    lease_generation=lease_generation,
                )

            executor_kwargs["should_cancel_attempt"] = should_cancel_attempt
        executor(
            cfg,
            **executor_kwargs,
        )
    except StaleRunAttemptError as exc:
        execution_error = str(exc) or exc.__class__.__name__
    except Exception as exc:  # noqa: BLE001 - worker must persist failure before returning.
        execution_error = str(exc) or exc.__class__.__name__
        try:
            update_run_state(
                cfg,
                run_id=run_id,
                status="failed",
                stage="worker",
                message="Run worker execution failed.",
                request_id=str(run["requestId"]),
                last_error={
                    "code": "RUN_WORKER_EXECUTION_FAILED",
                    "message": execution_error,
                    "scope": "worker",
                    "stage": "worker",
                },
                attempt_id=attempt_id,
                lease_generation=lease_generation,
            )
        except StaleRunAttemptError:
            pass
    finally:
        stop_heartbeat.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)

    final_run = fetch_run(cfg, run_id)
    final_status = str(final_run.get("status") if final_run else "")
    attempt_state = "succeeded" if final_status == "completed" else "failed"
    completion = complete_run_attempt(
        cfg,
        attempt_id,
        lease_generation=lease_generation,
        state=attempt_state,
        exit_code=0 if attempt_state == "succeeded" else 1,
        now=now_factory(),
    )
    result = {
        "claimed": True,
        "runId": run_id,
        "jobId": claim["jobId"],
        "attemptId": attempt_id,
        "leaseGeneration": lease_generation,
        "heartbeat": heartbeat,
        "attemptCompletion": completion,
        "executionError": execution_error,
    }
    if on_attempt_finished is not None:
        on_attempt_finished(result)
    return result


def _start_heartbeat_thread(
    cfg: RemoteRunnerConfig,
    *,
    attempt_id: str,
    lease_generation: int,
    lease_seconds: int,
    interval_seconds: float,
    now_factory: NowFactory,
    stop_event: threading.Event,
) -> threading.Thread | None:
    if interval_seconds <= 0:
        return None
    thread = threading.Thread(
        target=_heartbeat_until_stopped,
        kwargs={
            "cfg": cfg,
            "attempt_id": attempt_id,
            "lease_generation": lease_generation,
            "lease_seconds": lease_seconds,
            "interval_seconds": interval_seconds,
            "now_factory": now_factory,
            "stop_event": stop_event,
        },
        daemon=True,
    )
    thread.start()
    return thread


def _heartbeat_until_stopped(
    *,
    cfg: RemoteRunnerConfig,
    attempt_id: str,
    lease_generation: int,
    lease_seconds: int,
    interval_seconds: float,
    now_factory: NowFactory,
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(interval_seconds):
        result = heartbeat_run_attempt(
            cfg,
            attempt_id,
            lease_generation=lease_generation,
            now=now_factory(),
            lease_seconds=lease_seconds,
        )
        if not result.get("accepted"):
            stop_event.set()
            return
