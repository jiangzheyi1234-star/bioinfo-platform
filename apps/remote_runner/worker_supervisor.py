from __future__ import annotations

import logging
import os
import socket
import threading
from typing import Any
import uuid

from .config import load_remote_runner_config
from .reconciler import run_active_reconciler_once
from .run_worker import process_next_run_job
from .run_worker_storage import (
    heartbeat_run_worker,
    heartbeat_run_worker_slot,
    mark_run_worker_stopped,
    register_run_worker_slot,
    register_run_worker,
    run_worker_is_draining,
)
from .tool_prepare_job_storage import (
    claim_next_tool_prepare_job,
    heartbeat_tool_prepare_job,
    mark_tool_prepare_job_worker_failure,
)
from .tool_prepare_jobs import run_tool_prepare_job


LOGGER = logging.getLogger(__name__)


class RunWorkerSupervisor:
    def __init__(
        self,
        cfg: Any,
        *,
        worker_id: str,
        poll_interval_seconds: float,
        heartbeat_interval_seconds: float,
        error_backoff_seconds: float,
        queue_name: str = "default",
        concurrency_limit: int = 1,
    ) -> None:
        self._cfg = cfg
        self._worker_id = worker_id
        self._session_id = f"session_{uuid.uuid4().hex[:12]}"
        self._queue_name = queue_name
        self._concurrency_limit = max(1, int(concurrency_limit))
        if self._concurrency_limit > 1 and not _multi_slot_enabled():
            raise ValueError("P0_3A_SINGLE_SLOT_ONLY")
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._error_backoff_seconds = error_backoff_seconds
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._controller_thread = threading.Thread(
            target=self._controller_loop,
            name=f"h2ometa-run-controller-{worker_id}",
            daemon=True,
        )
        for index in range(self._concurrency_limit):
            slot_id = f"slot-{index}"
            thread = threading.Thread(
                target=self._run_loop,
                args=(slot_id,),
                name=f"h2ometa-run-worker-{worker_id}-{index}",
                daemon=True,
            )
            self._threads.append(thread)

    def start(self) -> None:
        register_run_worker(
            self._cfg,
            worker_id=self._worker_id,
            session_id=self._session_id,
            pid=os.getpid(),
            hostname=socket.gethostname(),
            queue_name=self._queue_name,
            concurrency_limit=self._concurrency_limit,
        )
        for index, thread in enumerate(self._threads):
            register_run_worker_slot(
                self._cfg,
                worker_id=self._worker_id,
                session_id=self._session_id,
                slot_id=f"slot-{index}",
            )
        self._controller_thread.start()
        for thread in self._threads:
            thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        self._controller_thread.join(timeout=timeout_seconds)
        for thread in self._threads:
            thread.join(timeout=timeout_seconds)
        if not any(thread.is_alive() for thread in self._threads):
            self._heartbeat_stopped()

    def _run_loop(self, slot_id: str) -> None:
        while not self._stop_event.is_set():
            try:
                if run_worker_is_draining(self._cfg, self._worker_id):
                    self._heartbeat("draining")
                    self._stop_event.wait(self._poll_interval_seconds)
                    continue
                self._heartbeat("idle")
                result = process_next_run_job(
                    self._cfg,
                    worker_id=self._worker_id,
                    session_id=self._session_id,
                    slot_id=slot_id,
                    queue_name=self._queue_name,
                    heartbeat_interval_seconds=self._heartbeat_interval_seconds,
                    on_attempt_claimed=lambda claim: self._mark_attempt_claimed(slot_id, claim),
                    on_attempt_finished=lambda result: self._mark_attempt_finished(slot_id, result),
                )
            except Exception as exc:  # noqa: BLE001 - supervisor must keep polling after persisting/logging failures.
                self._heartbeat(
                    "error",
                    last_error={
                        "code": "RUN_WORKER_LOOP_FAILED",
                        "message": str(exc) or exc.__class__.__name__,
                    },
                )
                LOGGER.exception("Remote runner worker loop failed.")
                self._stop_event.wait(self._error_backoff_seconds)
                continue
            if not result.get("claimed"):
                self._stop_event.wait(self._poll_interval_seconds)

    def _controller_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_active_reconciler_once(self._cfg)
            except Exception as exc:  # noqa: BLE001 - controller should stay alive after transient storage/process errors.
                self._heartbeat(
                    "error",
                    last_error={
                        "code": "RUN_RECONCILER_LOOP_FAILED",
                        "message": str(exc) or exc.__class__.__name__,
                    },
                )
                LOGGER.exception("Remote runner reconciler loop failed.")
                self._stop_event.wait(self._error_backoff_seconds)
                continue
            self._stop_event.wait(self._poll_interval_seconds)

    def _mark_attempt_claimed(self, slot_id: str, claim: dict[str, Any]) -> None:
        self._heartbeat("running", current_attempt_id=str(claim.get("attemptId") or ""))
        self._slot_heartbeat(slot_id, "running", current_attempt_id=str(claim.get("attemptId") or ""))

    def _mark_attempt_finished(self, slot_id: str, result: dict[str, Any]) -> None:
        error_message = str(result.get("executionError") or "")
        self._heartbeat(
            "idle",
            last_error=(
                {
                    "code": "RUN_WORKER_EXECUTION_FAILED",
                    "message": error_message,
                }
                if error_message
                else None
            ),
        )
        self._slot_heartbeat(slot_id, "idle")

    def _heartbeat(
        self,
        state: str,
        *,
        current_attempt_id: str | None = None,
        last_error: dict[str, Any] | None = None,
    ) -> None:
        heartbeat_run_worker(
            self._cfg,
            worker_id=self._worker_id,
            session_id=self._session_id,
            state=state,
            current_attempt_id=current_attempt_id,
            last_error=last_error,
        )

    def _heartbeat_stopped(self) -> None:
        mark_run_worker_stopped(
            self._cfg,
            worker_id=self._worker_id,
            session_id=self._session_id,
        )

    def _slot_heartbeat(
        self,
        slot_id: str,
        state: str,
        *,
        current_attempt_id: str | None = None,
        last_error: dict[str, Any] | None = None,
    ) -> None:
        heartbeat_run_worker_slot(
            self._cfg,
            worker_id=self._worker_id,
            session_id=self._session_id,
            slot_id=slot_id,
            state=state,
            current_attempt_id=current_attempt_id,
            last_error=last_error,
        )


class ToolPrepareWorkerSupervisor:
    def __init__(
        self,
        cfg: Any,
        *,
        worker_id: str,
        poll_interval_seconds: float,
        heartbeat_interval_seconds: float,
        error_backoff_seconds: float,
    ) -> None:
        self._cfg = cfg
        self._worker_id = worker_id
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._error_backoff_seconds = error_backoff_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, name="h2ometa-tool-prepare-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout_seconds)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = process_next_tool_prepare_job(
                    self._cfg,
                    worker_id=self._worker_id,
                    heartbeat_interval_seconds=self._heartbeat_interval_seconds,
                )
            except Exception:  # noqa: BLE001 - supervisor must keep polling after persisting/logging failures.
                LOGGER.exception("Remote runner tool prepare worker loop failed.")
                self._stop_event.wait(self._error_backoff_seconds)
                continue
            if not result.get("claimed"):
                self._stop_event.wait(self._poll_interval_seconds)


def start_run_worker_supervisor(
    cfg: Any,
    *,
    worker_id: str = "remote-runner-worker-1",
    poll_interval_seconds: float = 1.0,
    heartbeat_interval_seconds: float = 15.0,
    error_backoff_seconds: float = 5.0,
    concurrency_limit: int = 1,
) -> RunWorkerSupervisor:
    supervisor = RunWorkerSupervisor(
        cfg,
        worker_id=worker_id,
        poll_interval_seconds=poll_interval_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        error_backoff_seconds=error_backoff_seconds,
        concurrency_limit=concurrency_limit,
    )
    supervisor.start()
    return supervisor


def process_next_tool_prepare_job(
    cfg: Any,
    *,
    worker_id: str = "tool-prepare-worker-1",
    lease_seconds: int = 300,
    heartbeat_interval_seconds: float = 30.0,
    retry_delay_seconds: int = 30,
) -> dict[str, Any]:
    job = claim_next_tool_prepare_job(
        cfg,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
    )
    if job is None:
        return {"claimed": False}
    job_id = str(job["jobId"])
    stop_heartbeat = threading.Event()
    heartbeat_thread = _start_tool_prepare_heartbeat_thread(
        cfg,
        job_id=job_id,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        interval_seconds=heartbeat_interval_seconds,
        stop_event=stop_heartbeat,
    )
    try:
        run_tool_prepare_job(cfg, job_id)
    except Exception as exc:  # noqa: BLE001 - worker failures must not strand jobs in running state.
        error_message = str(exc) or exc.__class__.__name__
        retry = mark_tool_prepare_job_worker_failure(
            cfg,
            job_id,
            code="TOOL_PREPARE_WORKER_CRASHED",
            message=error_message,
            retry_delay_seconds=retry_delay_seconds,
        )
        return {
            "claimed": True,
            "jobId": job_id,
            "workerError": error_message,
            "retryStatus": str(retry.get("status") or ""),
        }
    finally:
        stop_heartbeat.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)
    return {"claimed": True, "jobId": job_id}


def _start_tool_prepare_heartbeat_thread(
    cfg: Any,
    *,
    job_id: str,
    worker_id: str,
    lease_seconds: int,
    interval_seconds: float,
    stop_event: threading.Event,
) -> threading.Thread | None:
    if interval_seconds <= 0:
        return None
    thread = threading.Thread(
        target=_heartbeat_tool_prepare_until_stopped,
        kwargs={
            "cfg": cfg,
            "job_id": job_id,
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
            "interval_seconds": interval_seconds,
            "stop_event": stop_event,
        },
        daemon=True,
    )
    thread.start()
    return thread


def _heartbeat_tool_prepare_until_stopped(
    *,
    cfg: Any,
    job_id: str,
    worker_id: str,
    lease_seconds: int,
    interval_seconds: float,
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(interval_seconds):
        result = heartbeat_tool_prepare_job(
            cfg,
            job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        if not result.get("accepted"):
            stop_event.set()
            return


def start_tool_prepare_worker_supervisor(
    cfg: Any,
    *,
    worker_id: str = "tool-prepare-worker-1",
    poll_interval_seconds: float = 1.0,
    heartbeat_interval_seconds: float = 30.0,
    error_backoff_seconds: float = 5.0,
) -> ToolPrepareWorkerSupervisor:
    supervisor = ToolPrepareWorkerSupervisor(
        cfg,
        worker_id=worker_id,
        poll_interval_seconds=poll_interval_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        error_backoff_seconds=error_backoff_seconds,
    )
    supervisor.start()
    return supervisor


def start_configured_run_worker_supervisor() -> RunWorkerSupervisor | None:
    cfg = load_remote_runner_config()
    if not cfg.token or not _run_worker_enabled():
        return None
    return start_run_worker_supervisor(cfg)


def start_configured_tool_prepare_worker_supervisor() -> ToolPrepareWorkerSupervisor | None:
    cfg = load_remote_runner_config()
    if not cfg.token or not _run_worker_enabled():
        return None
    return start_tool_prepare_worker_supervisor(cfg)


def _run_worker_enabled() -> bool:
    value = str(os.environ.get("H2OMETA_REMOTE_RUN_WORKER", "1") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _multi_slot_enabled() -> bool:
    value = str(os.environ.get("H2OMETA_REMOTE_ENABLE_MULTI_SLOT", "0") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}
