from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api import tool_capability_routes, tool_capability_service
from apps.api.tool_capability_server_runtime import bind_capability_graph_runtime
from core.app_runtime.managers.database import DatabaseManager
from core.app_runtime.managers.tool import ToolManager


def test_capability_graph_route_forwards_explicit_server_id(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_snapshot(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"data": {"serverId": kwargs["server_id"]}}

    monkeypatch.setattr(
        tool_capability_routes,
        "get_capability_graph_snapshot_from_request",
        fake_snapshot,
    )

    result = asyncio.run(
        tool_capability_routes.capability_graph_snapshot_api(
            q="fastqc",
            targetPlatform="linux-64",
            page=1,
            pageSize=100,
            agentSelectableOnly=True,
            serverId="srv_bound",
        )
    )

    assert captured["server_id"] == "srv_bound"
    assert result["data"]["serverId"] == "srv_bound"


@pytest.mark.parametrize("server_id", ["", "   "])
def test_capability_graph_route_rejects_blank_explicit_server_id(
    monkeypatch,
    server_id: str,
) -> None:
    called = False

    async def fake_snapshot(**_kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"data": {}}

    monkeypatch.setattr(
        tool_capability_routes,
        "get_capability_graph_snapshot_from_request",
        fake_snapshot,
    )
    app = FastAPI()
    app.include_router(tool_capability_routes.router)

    response = TestClient(app).get(
        "/api/v1/tool-capabilities/capability-graph",
        params={"serverId": server_id},
    )

    assert response.status_code == 422
    assert not called


def test_capability_graph_binds_every_remote_read_to_requested_server(
    monkeypatch,
) -> None:
    runtime = _BoundRuntime("srv_bound")
    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: runtime)
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: _empty_catalog(
            query=query,
            page=page,
            page_size=page_size,
        ),
    )

    result = asyncio.run(
        tool_capability_service.get_capability_graph_snapshot_from_request(
            q="fastqc",
            target_platform="linux-64",
            page=1,
            page_size=100,
            agent_selectable_only=True,
            server_id=" srv_bound ",
        )
    )

    assert result["data"]["serverId"] == "srv_bound"
    assert {name for name, _server_id in runtime.calls} == {
        "list_databases",
        "list_latest_tool_prepare_jobs",
        "list_tool_index",
        "list_tool_prepare_job_queue",
        "list_tools",
    }
    assert all(server_id == "srv_bound" for _name, server_id in runtime.calls)


def test_capability_graph_without_server_id_keeps_primary_runtime_calls(
    monkeypatch,
) -> None:
    runtime = _PrimaryRuntime()
    monkeypatch.setattr(tool_capability_service, "runtime_service", lambda: runtime)
    monkeypatch.setattr(
        tool_capability_service,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: _empty_catalog(
            query=query,
            page=page,
            page_size=page_size,
        ),
    )

    result = asyncio.run(
        tool_capability_service.get_capability_graph_snapshot_from_request(
            q="",
            target_platform="linux-64",
            page=1,
            page_size=100,
            agent_selectable_only=False,
        )
    )

    assert "serverId" not in result["data"]
    assert runtime.calls


def test_capability_graph_does_not_fallback_from_blank_explicit_server_id() -> None:
    with pytest.raises(ValueError, match="CAPABILITY_GRAPH_SERVER_ID_REQUIRED"):
        bind_capability_graph_runtime(_PrimaryRuntime(), "   ")


def test_tool_and_database_managers_forward_explicit_server_binding() -> None:
    service = _ManagerRuntimeService()
    tools = ToolManager(service)
    databases = DatabaseManager(service)

    tools.list_tool_index(server_id="srv_bound")
    tools.list_latest_tool_prepare_jobs(["bioconda::fastqc"], server_id="srv_bound")
    tools.list_tool_prepare_job_queue(server_id="srv_bound")
    databases.list_databases(server_id="srv_bound")

    assert service.preferred_server_ids == ["srv_bound"] * 4


class _BoundRuntime:
    def __init__(self, expected_server_id: str) -> None:
        self.expected_server_id = expected_server_id
        self.calls: list[tuple[str, str]] = []

    def _record(self, name: str, server_id: str) -> None:
        assert server_id == self.expected_server_id
        self.calls.append((name, server_id))

    def list_tools(self, *, server_id: str) -> dict[str, Any]:
        self._record("list_tools", server_id)
        return {"data": {"items": []}}

    def list_databases(self, *, server_id: str) -> dict[str, Any]:
        self._record("list_databases", server_id)
        return {"data": {"items": []}}

    def list_tool_index(self, *, server_id: str, **_kwargs: Any) -> dict[str, Any]:
        self._record("list_tool_index", server_id)
        return {"data": {"items": [], "total": 0, "hasMore": False}}

    def list_latest_tool_prepare_jobs(
        self,
        _tool_ids: list[str],
        *,
        server_id: str,
    ) -> dict[str, Any]:
        self._record("list_latest_tool_prepare_jobs", server_id)
        return {"data": {"byToolId": {}}}

    def list_tool_prepare_job_queue(
        self,
        *,
        server_id: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self._record("list_tool_prepare_job_queue", server_id)
        return {"data": _empty_prepare_queue()}


class _PrimaryRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _record(self, name: str) -> None:
        self.calls.append(name)

    def list_tools(self) -> dict[str, Any]:
        self._record("list_tools")
        return {"data": {"items": []}}

    def list_databases(self) -> dict[str, Any]:
        self._record("list_databases")
        return {"data": {"items": []}}

    def list_tool_index(self, **_kwargs: Any) -> dict[str, Any]:
        self._record("list_tool_index")
        return {"data": {"items": [], "total": 0, "hasMore": False}}

    def list_latest_tool_prepare_jobs(self, _tool_ids: list[str]) -> dict[str, Any]:
        self._record("list_latest_tool_prepare_jobs")
        return {"data": {"byToolId": {}}}

    def list_tool_prepare_job_queue(self, **_kwargs: Any) -> dict[str, Any]:
        self._record("list_tool_prepare_job_queue")
        return {"data": _empty_prepare_queue()}


class _RemoteEndpointRecorder:
    def call_remote_endpoint(self, **_kwargs: Any) -> Any:
        return []


class _ManagerRuntimeService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._service_locator = SimpleNamespace(
            remote_runner_manager=_RemoteEndpointRecorder()
        )
        self.preferred_server_ids: list[str | None] = []

    def _ensure_initialized(self) -> None:
        return None

    def _require_existing_runner_ready(
        self,
        *,
        preferred_server_id: str | None = None,
    ) -> tuple[str, object, dict[str, Any]]:
        self.preferred_server_ids.append(preferred_server_id)
        return preferred_server_id or "srv_primary", object(), {}

    @staticmethod
    def _call_remote_runner(
        method,
        *,
        server_id: str,
        ssh_service: object,
        server_record: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        del server_id, ssh_service, server_record
        return method(**kwargs)


def _empty_catalog(*, query: str, page: int, page_size: int) -> dict[str, Any]:
    return {
        "items": [],
        "query": query,
        "total": 0,
        "page": page,
        "pageSize": page_size,
        "hasMore": False,
        "sourceCounts": {},
        "addableDraftCounts": {},
        "qualityCounts": {},
    }


def _empty_prepare_queue() -> dict[str, Any]:
    return {
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
        "statusCounts": {},
    }
