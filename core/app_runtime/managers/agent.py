"""Local runtime manager for the remote AgentSession control plane."""

from __future__ import annotations

from typing import Any

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.base import BaseRuntimeManager
from core.contracts.agent_remote_endpoints import (
    AGENT_SESSION_APPROVAL,
    AGENT_SESSION_APPROVALS_READ,
    AGENT_SESSION_CANCEL,
    AGENT_SESSION_CREATE,
    AGENT_SESSION_EVENTS_READ,
    AGENT_SESSION_LIST,
    AGENT_SESSION_PLAN,
    AGENT_SESSION_PLANS_READ,
    AGENT_SESSION_READ,
    AGENT_SESSION_REPLAN,
)
from core.contracts.agent_session import (
    AgentApprovalRequest,
    AgentCancelRequest,
    AgentPlanRequest,
    AgentReplanRequest,
    AgentSessionCreateRequest,
)


class AgentManager(BaseRuntimeManager):
    def list_agent_sessions(self, server_id: str | None = None) -> dict[str, Any]:
        return {
            "data": {
                "items": self.call_existing_remote_endpoint(
                    AGENT_SESSION_LIST,
                    preferred_server_id=server_id,
                )
            }
        }

    def create_agent_session(
        self,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        preferred_server_id, body = _validated_remote_payload(
            AgentSessionCreateRequest,
            payload,
            server_id=server_id,
        )
        return self.read_remote_endpoint(
            AGENT_SESSION_CREATE,
            payload=body,
            preferred_server_id=preferred_server_id,
            require_existing_runner=True,
        )

    def get_agent_session(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.read_existing_remote_endpoint(
            AGENT_SESSION_READ,
            path_values={"session_id": session_id},
            preferred_server_id=server_id,
        )

    def list_agent_session_events(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._list_session_child(
            AGENT_SESSION_EVENTS_READ,
            session_id=session_id,
            server_id=server_id,
        )

    def list_agent_session_plans(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._list_session_child(
            AGENT_SESSION_PLANS_READ,
            session_id=session_id,
            server_id=server_id,
        )

    def list_agent_session_approvals(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._list_session_child(
            AGENT_SESSION_APPROVALS_READ,
            session_id=session_id,
            server_id=server_id,
        )

    def plan_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._command(
            AGENT_SESSION_PLAN,
            AgentPlanRequest,
            session_id=session_id,
            payload=payload,
            server_id=server_id,
            timeout=120,
        )

    def approve_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._command(
            AGENT_SESSION_APPROVAL,
            AgentApprovalRequest,
            session_id=session_id,
            payload=payload,
            server_id=server_id,
            timeout=120,
        )

    def replan_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._command(
            AGENT_SESSION_REPLAN,
            AgentReplanRequest,
            session_id=session_id,
            payload=payload,
            server_id=server_id,
            timeout=120,
        )

    def cancel_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self._command(
            AGENT_SESSION_CANCEL,
            AgentCancelRequest,
            session_id=session_id,
            payload=payload,
            server_id=server_id,
        )

    def _list_session_child(
        self,
        endpoint_id: str,
        *,
        session_id: str,
        server_id: str | None,
    ) -> dict[str, Any]:
        return {
            "data": {
                "items": self.call_existing_remote_endpoint(
                    endpoint_id,
                    path_values={"session_id": session_id},
                    preferred_server_id=server_id,
                )
            }
        }

    def _command(
        self,
        endpoint_id: str,
        contract_type: type[Any],
        *,
        session_id: str,
        payload: dict[str, Any] | None,
        server_id: str | None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        preferred_server_id, body = _validated_remote_payload(
            contract_type,
            payload,
            server_id=server_id,
        )
        return self.read_remote_endpoint(
            endpoint_id,
            path_values={"session_id": session_id},
            payload=body,
            preferred_server_id=preferred_server_id,
            require_existing_runner=True,
            timeout=timeout,
        )


def _validated_remote_payload(
    contract_type: type[Any],
    payload: dict[str, Any] | None,
    *,
    server_id: str | None,
) -> tuple[str | None, dict[str, Any]]:
    body = dict(payload or {})
    embedded_server_id = _optional_text(body.pop("serverId", None))
    preferred_server_id = _optional_text(server_id)
    if embedded_server_id and preferred_server_id and embedded_server_id != preferred_server_id:
        raise RuntimeServiceError("AGENT_SESSION_SERVER_ID_CONFLICT")
    validated = contract_type.model_validate(body)
    return preferred_server_id or embedded_server_id, validated.runtime_payload()


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
