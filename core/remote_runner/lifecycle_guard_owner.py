from __future__ import annotations


def execution_lifecycle_guard_owner(*, server_id: str, action: str) -> str:
    normalized_server_id = str(server_id or "").strip()
    normalized_action = str(action or "").strip()
    return f"{normalized_server_id}:{normalized_action}:lifecycle"
