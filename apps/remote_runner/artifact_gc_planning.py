from __future__ import annotations

from typing import Any


def apply_max_delete_bytes(
    candidates: list[dict[str, Any]],
    max_delete_bytes: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if max_delete_bytes is None:
        return candidates, []
    kept: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    total = 0
    for item in sorted(candidates, key=lambda value: (str(value["terminalAt"]), str(value["storageUri"]))):
        size = int(item["sizeBytes"])
        if total + size > max_delete_bytes:
            protected.append({**item, "reasons": ["max_delete_bytes"]})
            continue
        kept.append(item)
        total += size
    return kept, protected


def quota_overage_bytes(*, active_bytes: int, quota_bytes: int | None) -> int:
    if quota_bytes is None:
        return 0
    return max(0, int(active_bytes) - max(0, int(quota_bytes)))


def apply_quota_pressure(
    retention_held: list[dict[str, Any]],
    *,
    quota_overage_bytes: int,
    existing_candidate_bytes: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    remaining_pressure = max(0, int(quota_overage_bytes) - max(0, int(existing_candidate_bytes)))
    if remaining_pressure <= 0:
        return retention_held, []
    protected: list[dict[str, Any]] = []
    quota_candidates: list[dict[str, Any]] = []
    selected_bytes = 0
    for item in sorted(retention_held, key=lambda value: (str(value["terminalAt"]), str(value["storageUri"]))):
        if selected_bytes < remaining_pressure:
            quota_candidates.append(item)
            selected_bytes += int(item["sizeBytes"])
        else:
            protected.append(item)
    return protected, quota_candidates
