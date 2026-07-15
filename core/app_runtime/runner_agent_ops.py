from __future__ import annotations

from typing import Any


class RunnerAgentOperationsMixin:
    def list_agent_sessions(self, server_id: str | None = None) -> dict[str, Any]:
        return self.agents.list_agent_sessions(server_id)

    def create_agent_session(
        self,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.agents.create_agent_session(payload, server_id=server_id)

    def get_agent_session(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.agents.get_agent_session(session_id, server_id=server_id)

    def list_agent_session_events(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.agents.list_agent_session_events(session_id, server_id=server_id)

    def list_agent_session_plans(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.agents.list_agent_session_plans(session_id, server_id=server_id)

    def list_agent_session_approvals(
        self,
        session_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.agents.list_agent_session_approvals(session_id, server_id=server_id)

    def plan_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.agents.plan_agent_session(session_id, payload, server_id=server_id)

    def approve_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.agents.approve_agent_session(session_id, payload, server_id=server_id)

    def replan_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.agents.replan_agent_session(session_id, payload, server_id=server_id)

    def cancel_agent_session(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        return self.agents.cancel_agent_session(session_id, payload, server_id=server_id)
