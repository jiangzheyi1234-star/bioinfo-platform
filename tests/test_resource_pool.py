from __future__ import annotations

import threading
import time

from apps.remote_runner.resource_pool import (
    ResourcePool,
    ResourcePoolConfig,
    ResourceRequest,
    ResourceExhaustedError,
    get_default_resource_pool,
    reset_default_resource_pool,
)


def test_resource_pool_acquire_and_release():
    pool = ResourcePool(ResourcePoolConfig(total_cpu=4, total_memory_mb=8192, max_concurrent_tasks=2))
    request = ResourceRequest(cpu=2, memory_mb=1024)

    assert pool.acquire("task_1", request)
    snapshot = pool.snapshot()
    assert snapshot["availableCpu"] == 2
    assert snapshot["availableMemoryMb"] == 7168
    assert snapshot["activeTasks"] == 1

    pool.release("task_1")
    snapshot = pool.snapshot()
    assert snapshot["availableCpu"] == 4
    assert snapshot["availableMemoryMb"] == 8192
    assert snapshot["activeTasks"] == 0


def test_resource_pool_concurrent_limit():
    pool = ResourcePool(ResourcePoolConfig(total_cpu=4, total_memory_mb=8192, max_concurrent_tasks=2))
    request = ResourceRequest(cpu=1)

    assert pool.acquire("task_1", request)
    assert pool.acquire("task_2", request)

    acquired = pool.acquire("task_3", request, timeout=0.1)
    assert not acquired

    pool.release("task_1")
    assert pool.acquire("task_3", request, timeout=0.1)


def test_resource_pool_exhausted():
    pool = ResourcePool(ResourcePoolConfig(total_cpu=2, total_memory_mb=1024, max_concurrent_tasks=4))
    request = ResourceRequest(cpu=2)

    assert pool.acquire("task_1", request)

    try:
        pool.acquire("task_2", ResourceRequest(cpu=1))
        assert False, "Should have raised ResourceExhaustedError"
    except ResourceExhaustedError:
        pass


def test_resource_pool_idempotent_acquire():
    pool = ResourcePool(ResourcePoolConfig(total_cpu=4, max_concurrent_tasks=2))
    request = ResourceRequest(cpu=2)

    assert pool.acquire("task_1", request)
    assert pool.acquire("task_1", request)

    snapshot = pool.snapshot()
    assert snapshot["activeTasks"] == 1
    assert snapshot["availableCpu"] == 2


def test_resource_pool_release_unknown_task_does_not_expand_capacity():
    pool = ResourcePool(ResourcePoolConfig(total_cpu=2, max_concurrent_tasks=1))

    pool.release("missing")
    assert pool.acquire("task_1", ResourceRequest(cpu=1))
    assert not pool.acquire("task_2", ResourceRequest(cpu=1), timeout=0.1)

    pool.release("task_1")
    assert pool.acquire("task_2", ResourceRequest(cpu=1), timeout=0.1)


def test_resource_pool_multiple_tasks():
    pool = ResourcePool(ResourcePoolConfig(total_cpu=8, total_memory_mb=16384, max_concurrent_tasks=4))

    pool.acquire("task_1", ResourceRequest(cpu=2, memory_mb=2048))
    pool.acquire("task_2", ResourceRequest(cpu=2, memory_mb=4096))
    pool.acquire("task_3", ResourceRequest(cpu=1, memory_mb=1024, gpu=0))

    snapshot = pool.snapshot()
    assert snapshot["activeTasks"] == 3
    assert snapshot["availableCpu"] == 3
    assert snapshot["availableMemoryMb"] == 9216

    pool.release("task_2")
    snapshot = pool.snapshot()
    assert snapshot["activeTasks"] == 2
    assert snapshot["availableCpu"] == 5
    assert snapshot["availableMemoryMb"] == 13312


def test_resource_pool_thread_safety():
    pool = ResourcePool(ResourcePoolConfig(total_cpu=10, max_concurrent_tasks=10))
    results = []
    errors = []

    def worker(task_id: str):
        try:
            pool.acquire(task_id, ResourceRequest(cpu=1))
            time.sleep(0.01)
            results.append(task_id)
            pool.release(task_id)
        except Exception as exc:
            errors.append((task_id, str(exc)))

    threads = [threading.Thread(target=worker, args=(f"task_{i}",)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(errors) == 0
    assert len(results) == 10
    snapshot = pool.snapshot()
    assert snapshot["activeTasks"] == 0
    assert snapshot["availableCpu"] == 10


def test_default_resource_pool():
    reset_default_resource_pool()
    pool1 = get_default_resource_pool()
    pool2 = get_default_resource_pool()
    assert pool1 is pool2

    reset_default_resource_pool()
    pool3 = get_default_resource_pool(ResourcePoolConfig(total_cpu=16))
    assert pool3 is not pool1
    assert pool3.snapshot()["totalCpu"] == 16


def test_resource_pool_gpu():
    pool = ResourcePool(ResourcePoolConfig(total_cpu=4, total_gpu=2, max_concurrent_tasks=4))

    pool.acquire("task_1", ResourceRequest(cpu=1, gpu=1))
    pool.acquire("task_2", ResourceRequest(cpu=1, gpu=1))

    snapshot = pool.snapshot()
    assert snapshot["availableGpu"] == 0

    try:
        pool.acquire("task_3", ResourceRequest(cpu=1, gpu=1))
        assert False, "Should have raised ResourceExhaustedError"
    except ResourceExhaustedError:
        pass

    pool.release("task_1")
    assert pool.acquire("task_3", ResourceRequest(cpu=1, gpu=1))
