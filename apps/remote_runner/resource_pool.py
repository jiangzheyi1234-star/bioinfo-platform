from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResourceRequest:
    cpu: int = 1
    memory_mb: int = 0
    disk_mb: int = 0
    gpu: int = 0


@dataclass(frozen=True)
class ResourcePoolConfig:
    total_cpu: int = 4
    total_memory_mb: int = 8192
    total_disk_mb: int = 0
    total_gpu: int = 0
    max_concurrent_tasks: int = 1


@dataclass
class ResourcePoolState:
    available_cpu: int
    available_memory_mb: int
    available_disk_mb: int
    available_gpu: int
    active_tasks: int = 0
    allocations: dict[str, ResourceRequest] = field(default_factory=dict)


class ResourceExhaustedError(Exception):
    pass


class ResourcePool:
    def __init__(self, config: ResourcePoolConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(config.max_concurrent_tasks)
        self._state = ResourcePoolState(
            available_cpu=config.total_cpu,
            available_memory_mb=config.total_memory_mb,
            available_disk_mb=config.total_disk_mb,
            available_gpu=config.total_gpu,
        )

    def acquire(self, task_id: str, request: ResourceRequest, *, timeout: float | None = None) -> bool:
        if not self._semaphore.acquire(timeout=timeout):
            return False
        with self._lock:
            if task_id in self._state.allocations:
                self._semaphore.release()
                return True
            if not self._can_allocate(request):
                self._semaphore.release()
                raise ResourceExhaustedError(
                    f"Insufficient resources for task {task_id}: "
                    f"requested cpu={request.cpu} mem={request.memory_mb}MB "
                    f"gpu={request.gpu}, "
                    f"available cpu={self._state.available_cpu} "
                    f"mem={self._state.available_memory_mb}MB "
                    f"gpu={self._state.available_gpu}"
                )
            self._allocate(task_id, request)
            return True

    def release(self, task_id: str) -> None:
        with self._lock:
            request = self._state.allocations.pop(task_id, None)
            if request is None:
                return
            self._state.available_cpu += request.cpu
            self._state.available_memory_mb += request.memory_mb
            self._state.available_disk_mb += request.disk_mb
            self._state.available_gpu += request.gpu
            self._state.active_tasks -= 1
        self._semaphore.release()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "totalCpu": self._config.total_cpu,
                "totalMemoryMb": self._config.total_memory_mb,
                "totalDiskMb": self._config.total_disk_mb,
                "totalGpu": self._config.total_gpu,
                "maxConcurrentTasks": self._config.max_concurrent_tasks,
                "availableCpu": self._state.available_cpu,
                "availableMemoryMb": self._state.available_memory_mb,
                "availableDiskMb": self._state.available_disk_mb,
                "availableGpu": self._state.available_gpu,
                "activeTasks": self._state.active_tasks,
                "allocations": {
                    tid: {
                        "cpu": req.cpu,
                        "memoryMb": req.memory_mb,
                        "diskMb": req.disk_mb,
                        "gpu": req.gpu,
                    }
                    for tid, req in self._state.allocations.items()
                },
            }

    def _can_allocate(self, request: ResourceRequest) -> bool:
        if request.cpu > self._state.available_cpu:
            return False
        if request.memory_mb > self._state.available_memory_mb:
            return False
        if request.disk_mb > 0 and request.disk_mb > self._state.available_disk_mb:
            return False
        if request.gpu > self._state.available_gpu:
            return False
        return True

    def _allocate(self, task_id: str, request: ResourceRequest) -> None:
        self._state.available_cpu -= request.cpu
        self._state.available_memory_mb -= request.memory_mb
        self._state.available_disk_mb -= request.disk_mb
        self._state.available_gpu -= request.gpu
        self._state.allocations[task_id] = request
        self._state.active_tasks += 1


_DEFAULT_POOL: ResourcePool | None = None
_DEFAULT_POOL_LOCK = threading.Lock()


def get_default_resource_pool(config: ResourcePoolConfig | None = None) -> ResourcePool:
    global _DEFAULT_POOL
    with _DEFAULT_POOL_LOCK:
        if _DEFAULT_POOL is None:
            _DEFAULT_POOL = ResourcePool(config or ResourcePoolConfig())
        return _DEFAULT_POOL


def reset_default_resource_pool() -> None:
    global _DEFAULT_POOL
    with _DEFAULT_POOL_LOCK:
        _DEFAULT_POOL = None
