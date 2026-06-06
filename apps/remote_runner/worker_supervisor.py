from __future__ import annotations

import logging
import os
import threading
from typing import Any

from .config import load_remote_runner_config
from .run_worker import process_next_run_job


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
    ) -> None:
        self._cfg = cfg
        self._worker_id = worker_id
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._error_backoff_seconds = error_backoff_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, name=f"h2ometa-run-worker-{worker_id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout_seconds)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = process_next_run_job(
                    self._cfg,
                    worker_id=self._worker_id,
                    heartbeat_interval_seconds=self._heartbeat_interval_seconds,
                )
            except Exception:  # noqa: BLE001 - supervisor must keep polling after persisting/logging failures.
                LOGGER.exception("Remote runner worker loop failed.")
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
) -> RunWorkerSupervisor:
    supervisor = RunWorkerSupervisor(
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


def _run_worker_enabled() -> bool:
    value = str(os.environ.get("H2OMETA_REMOTE_RUN_WORKER", "1") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}
