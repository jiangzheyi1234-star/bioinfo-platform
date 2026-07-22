"""Strict UTC comparisons for execution lease authority boundaries."""

from __future__ import annotations

import re
from datetime import datetime, timezone


_UTC_SECOND = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def execution_lease_expiry_is_future(
    expires_at: object,
    *,
    observed_at: object | None = None,
) -> bool:
    """Return true only for a strict UTC expiry later than the observation."""

    expiry = _parse_utc_second(expires_at)
    if expiry is None:
        return False
    if observed_at is None:
        observed = datetime.now(timezone.utc)
    else:
        observed = _parse_utc_second(observed_at)
        if observed is None:
            return False
    return expiry > observed


def require_execution_utc_timestamp(value: object) -> str:
    """Normalize one persisted execution timestamp or reject it before mutation."""

    if _parse_utc_second(value) is None:
        raise ValueError("EXECUTION_TIMESTAMP_INVALID")
    return str(value)


def execution_timestamp_at_or_after(
    *,
    requested_at: str | None,
    current_at: object,
) -> str:
    """Observe time after a lock without accepting an older caller timestamp."""

    current = require_execution_utc_timestamp(current_at)
    if requested_at is None:
        return current
    requested = require_execution_utc_timestamp(requested_at)
    return max(requested, current)


def _parse_utc_second(value: object) -> datetime | None:
    if type(value) is not str or _UTC_SECOND.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


__all__ = [
    "execution_lease_expiry_is_future",
    "execution_timestamp_at_or_after",
    "require_execution_utc_timestamp",
]
