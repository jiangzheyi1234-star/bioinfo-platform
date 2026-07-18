"""Strict, domain-separated canonical hashes for Agent public contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .agent_session import assert_agent_session_json_safe


def agent_contract_canonical_json(payload: Mapping[str, object]) -> str:
    """Serialize an exact Agent hash payload without dropping JSON values."""

    normalized = dict(payload)
    assert_agent_session_json_safe(normalized, path="agent.contractHash")
    return json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def agent_contract_hash(domain: str, payload: Mapping[str, object]) -> str:
    """Return a lowercase SHA-256 hex digest bound to one versioned domain."""

    if not isinstance(domain, str) or not domain or domain != domain.strip() or "\x00" in domain:
        raise ValueError("AGENT_CONTRACT_HASH_DOMAIN_INVALID")
    canonical = agent_contract_canonical_json(payload)
    return hashlib.sha256(domain.encode("utf-8") + b"\x00" + canonical.encode("utf-8")).hexdigest()


def exact_hash_payload(
    payload: Mapping[str, object],
    fields: tuple[str, ...],
    *,
    code: str,
) -> dict[str, Any]:
    """Select an explicit hash-field allowlist and fail when any field is missing."""

    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError(f"{code}: {','.join(missing)}")
    return {field: payload[field] for field in fields}


__all__ = [
    "agent_contract_canonical_json",
    "agent_contract_hash",
    "exact_hash_payload",
]
