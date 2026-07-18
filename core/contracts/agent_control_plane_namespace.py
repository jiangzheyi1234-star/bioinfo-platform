"""Reserved run-ledger namespace owned by the Agent control plane."""

from __future__ import annotations


AGENT_CONTROL_PLANE_NAMESPACE_PREFIX = "agent-control-plane."
AGENT_CONTROL_PLANE_NAMESPACE_RESERVED = "AGENT_CONTROL_PLANE_NAMESPACE_RESERVED"


def require_public_server_id(server_id: str) -> str:
    """Normalize public server identity and reject the internal Agent namespace."""

    value = str(server_id or "").strip()
    if value.startswith(AGENT_CONTROL_PLANE_NAMESPACE_PREFIX):
        raise ValueError(f"{AGENT_CONTROL_PLANE_NAMESPACE_RESERVED}: serverId")
    return value


__all__ = [
    "AGENT_CONTROL_PLANE_NAMESPACE_PREFIX",
    "AGENT_CONTROL_PLANE_NAMESPACE_RESERVED",
    "require_public_server_id",
]
