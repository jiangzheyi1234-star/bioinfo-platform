from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.contracts.problem_details import ensure_request_id


LOCAL_CONTROL_CONTEXT_KEYS = frozenset({"serverId", "requestId", "actor"})


@dataclass(frozen=True)
class RemoteCommandContext:
    server_id: str
    request_id: str
    actor: str = ""

    @property
    def headers(self) -> dict[str, str]:
        headers = {
            "X-Request-Id": self.request_id,
            "X-H2OMeta-Server-Id": self.server_id,
        }
        if self.actor:
            headers["X-H2OMeta-Actor"] = self.actor
        return headers


def remote_command_context_from_payload(
    payload: dict[str, Any] | None,
    *,
    require_server_id: bool = True,
    default_actor: str = "",
) -> tuple[RemoteCommandContext, dict[str, Any]]:
    body = dict(payload or {})
    server_id = str(body.pop("serverId", "") or "").strip()
    if require_server_id and not server_id:
        raise ValueError("REMOTE_COMMAND_CONTEXT_SERVER_ID_REQUIRED")
    request_id = ensure_request_id(str(body.pop("requestId", "") or ""))
    actor = str(body.pop("actor", "") or default_actor or "").strip()
    return RemoteCommandContext(server_id=server_id, request_id=request_id, actor=actor), body


def strip_local_control_context(payload: dict[str, Any] | None) -> dict[str, Any]:
    body = dict(payload or {})
    for key in LOCAL_CONTROL_CONTEXT_KEYS:
        body.pop(key, None)
    return body
