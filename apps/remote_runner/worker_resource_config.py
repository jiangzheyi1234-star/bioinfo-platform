from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .resource_pool import ResourcePoolConfig, ResourceRequest


@dataclass(frozen=True)
class RunWorkerResourcePlan:
    slot_count: int
    resource_request: ResourceRequest
    resource_capacity: ResourceRequest
    resource_pool_config: ResourcePoolConfig


def apply_run_worker_env_overrides(cfg: Any) -> None:
    env_map = {
        "run_worker_slot_count": "H2OMETA_REMOTE_RUN_WORKER_SLOTS",
        "run_worker_total_cpu": "H2OMETA_REMOTE_RUN_WORKER_TOTAL_CPU",
        "run_worker_total_memory_mb": "H2OMETA_REMOTE_RUN_WORKER_TOTAL_MEMORY_MB",
        "run_worker_total_disk_mb": "H2OMETA_REMOTE_RUN_WORKER_TOTAL_DISK_MB",
        "run_worker_total_gpu": "H2OMETA_REMOTE_RUN_WORKER_TOTAL_GPU",
        "run_worker_attempt_cpu": "H2OMETA_REMOTE_RUN_WORKER_ATTEMPT_CPU",
        "run_worker_attempt_memory_mb": "H2OMETA_REMOTE_RUN_WORKER_ATTEMPT_MEMORY_MB",
        "run_worker_attempt_disk_mb": "H2OMETA_REMOTE_RUN_WORKER_ATTEMPT_DISK_MB",
        "run_worker_attempt_gpu": "H2OMETA_REMOTE_RUN_WORKER_ATTEMPT_GPU",
    }
    for field_name, env_name in env_map.items():
        raw = str(os.environ.get(env_name, "") or "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{env_name}_INVALID") from exc
        setattr(cfg, field_name, value)


def build_run_worker_resource_plan(
    cfg: Any,
    *,
    slot_count: int | None = None,
) -> RunWorkerResourcePlan:
    resolved_slots = _positive_int(
        getattr(cfg, "run_worker_slot_count", 1) if slot_count is None else slot_count,
        "RUN_WORKER_SLOT_COUNT_INVALID",
    )
    if resolved_slots > 2:
        raise ValueError("P0_3B_MAX_TWO_SLOTS")
    request = ResourceRequest(
        cpu=_positive_int(getattr(cfg, "run_worker_attempt_cpu", 1), "RUN_WORKER_ATTEMPT_CPU_INVALID"),
        memory_mb=_non_negative_int(
            getattr(cfg, "run_worker_attempt_memory_mb", 0),
            "RUN_WORKER_ATTEMPT_MEMORY_INVALID",
        ),
        disk_mb=_non_negative_int(
            getattr(cfg, "run_worker_attempt_disk_mb", 0),
            "RUN_WORKER_ATTEMPT_DISK_INVALID",
        ),
        gpu=_non_negative_int(getattr(cfg, "run_worker_attempt_gpu", 0), "RUN_WORKER_ATTEMPT_GPU_INVALID"),
    )
    capacity = ResourceRequest(
        cpu=_positive_int(getattr(cfg, "run_worker_total_cpu", 1), "RUN_WORKER_TOTAL_CPU_INVALID"),
        memory_mb=_non_negative_int(getattr(cfg, "run_worker_total_memory_mb", 0), "RUN_WORKER_TOTAL_MEMORY_INVALID"),
        disk_mb=_non_negative_int(getattr(cfg, "run_worker_total_disk_mb", 0), "RUN_WORKER_TOTAL_DISK_INVALID"),
        gpu=_non_negative_int(getattr(cfg, "run_worker_total_gpu", 0), "RUN_WORKER_TOTAL_GPU_INVALID"),
    )
    _validate_worker_capacity(capacity, request)
    return RunWorkerResourcePlan(
        slot_count=resolved_slots,
        resource_request=request,
        resource_capacity=capacity,
        resource_pool_config=ResourcePoolConfig(
            total_cpu=capacity.cpu,
            total_memory_mb=capacity.memory_mb,
            total_disk_mb=capacity.disk_mb,
            total_gpu=capacity.gpu,
            max_concurrent_tasks=resolved_slots,
        ),
    )


def _validate_worker_capacity(capacity: ResourceRequest, request: ResourceRequest) -> None:
    if capacity.cpu < request.cpu:
        raise ValueError("RUN_WORKER_CPU_CAPACITY_BELOW_ATTEMPT_REQUEST")
    if capacity.memory_mb < request.memory_mb:
        raise ValueError("RUN_WORKER_MEMORY_CAPACITY_BELOW_ATTEMPT_REQUEST")
    if capacity.disk_mb < request.disk_mb:
        raise ValueError("RUN_WORKER_DISK_CAPACITY_BELOW_ATTEMPT_REQUEST")
    if capacity.gpu < request.gpu:
        raise ValueError("RUN_WORKER_GPU_CAPACITY_BELOW_ATTEMPT_REQUEST")


def _positive_int(value: Any, code: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if parsed < 1:
        raise ValueError(code)
    return parsed


def _non_negative_int(value: Any, code: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    if parsed < 0:
        raise ValueError(code)
    return parsed
