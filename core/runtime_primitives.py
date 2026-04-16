"""Minimal runtime primitives for headless Python services.

This module provides the tiny signal/thread/mutex subset used by the backend
without carrying any Qt naming or compatibility surface.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Callable, Optional


class Signal:
    """Simple thread-safe signal implementation."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[..., Any]] = []
        self._lock = threading.RLock()

    def connect(self, callback: Callable[..., Any]) -> None:
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def disconnect(self, callback: Optional[Callable[..., Any]] = None) -> None:
        with self._lock:
            if callback is None:
                self._callbacks.clear()
                return
            self._callbacks = [fn for fn in self._callbacks if fn is not callback]

    def emit(self, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            callbacks = list(self._callbacks)
        for callback in callbacks:
            callback(*args, **kwargs)


class _SignalDescriptor:
    def __init__(self, *_args: Any) -> None:
        self._slot_name = ""

    def __set_name__(self, _owner: type, name: str) -> None:
        self._slot_name = f"__signal_{name}"

    def __get__(self, instance: Any, _owner: type | None = None) -> Any:
        if instance is None:
            return self
        signal = instance.__dict__.get(self._slot_name)
        if signal is None:
            signal = Signal()
            instance.__dict__[self._slot_name] = signal
        return signal


def signal(*args: Any) -> _SignalDescriptor:  # noqa: ARG001
    return _SignalDescriptor(*args)


def slot(*args: Any, **kwargs: Any):  # noqa: ANN001, ARG001
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        return fn

    return decorator


class RuntimeObject:
    def __init__(self, parent: "RuntimeObject | None" = None) -> None:
        self._parent = parent
        self._thread: RuntimeThread | None = None

    def move_to_thread(self, thread: "RuntimeThread") -> None:
        self._thread = thread

    def moveToThread(self, thread: "RuntimeThread") -> None:
        self.move_to_thread(thread)


class RuntimeThread(RuntimeObject):
    started = signal()
    finished = signal()

    def __init__(self, parent: RuntimeObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._quit_requested = threading.Event()

    def start(self) -> None:
        if self.isRunning():
            return
        self._quit_requested.clear()
        self._thread = threading.Thread(target=self._bootstrap, daemon=True)
        self._thread.start()

    def _bootstrap(self) -> None:
        self._running.set()
        try:
            self.started.emit()
            self.run()
        finally:
            self._running.clear()
            self.finished.emit()

    def run(self) -> None:
        """Override in subclasses."""

    def quit(self) -> None:
        self._quit_requested.set()

    def wait(self, timeout_ms: int | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        timeout_s = None if timeout_ms is None or timeout_ms < 0 else timeout_ms / 1000.0
        thread.join(timeout_s)
        return not thread.is_alive()

    def isRunning(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive() and self._running.is_set())

    @staticmethod
    def msleep(ms: int) -> None:
        time.sleep(max(ms, 0) / 1000.0)


class RuntimeMutex:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def lock(self) -> None:
        self._lock.acquire()

    def unlock(self) -> None:
        self._lock.release()


class RuntimeMutexLocker:
    def __init__(self, mutex: RuntimeMutex) -> None:
        self._mutex = mutex
        self._locked = True
        self._mutex.lock()

    def __enter__(self) -> "RuntimeMutexLocker":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.unlock()

    def unlock(self) -> None:
        if self._locked:
            self._mutex.unlock()
            self._locked = False

    def __del__(self) -> None:
        self.unlock()


class RuntimeWaitCondition:
    def __init__(self) -> None:
        self._condition = threading.Condition()

    def wait(self, mutex: RuntimeMutex, timeout_ms: int | None = None) -> bool:
        timeout_s = None if timeout_ms is None or timeout_ms < 0 else timeout_ms / 1000.0
        with self._condition:
            mutex.unlock()
            notified = self._condition.wait(timeout=timeout_s)
            mutex.lock()
            return notified

    def wake_all(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def wakeAll(self) -> None:
        self.wake_all()


class RuntimeRunnable:
    def __init__(self) -> None:
        self._auto_delete = True

    def set_auto_delete(self, value: bool) -> None:
        self._auto_delete = bool(value)

    def setAutoDelete(self, value: bool) -> None:
        self.set_auto_delete(value)

    def run(self) -> None:
        raise NotImplementedError


class RuntimeThreadPool(RuntimeObject):
    def __init__(self, parent: RuntimeObject | None = None) -> None:
        super().__init__(parent)
        self._max_threads = 1
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_threads, thread_name_prefix="runtime_pool"
        )
        self._futures: set[Any] = set()
        self._lock = threading.RLock()

    def set_max_thread_count(self, count: int) -> None:
        target = max(1, int(count))
        if target == self._max_threads:
            return
        with self._lock:
            old_executor = self._executor
            self._executor = ThreadPoolExecutor(
                max_workers=target, thread_name_prefix="runtime_pool"
            )
            self._max_threads = target
        old_executor.shutdown(wait=False, cancel_futures=False)

    def setMaxThreadCount(self, count: int) -> None:
        self.set_max_thread_count(count)

    def start(self, runnable: RuntimeRunnable) -> None:
        with self._lock:
            future = self._executor.submit(runnable.run)
            self._futures.add(future)
            future.add_done_callback(self._futures.discard)

    def wait_for_done(self, timeout_ms: int = -1) -> bool:
        timeout_s = None if timeout_ms is None or timeout_ms < 0 else timeout_ms / 1000.0
        with self._lock:
            futures = list(self._futures)
        if not futures:
            return True
        done, pending = wait(futures, timeout=timeout_s)
        return len(pending) == 0

    def waitForDone(self, timeout_ms: int = -1) -> bool:
        return self.wait_for_done(timeout_ms)
