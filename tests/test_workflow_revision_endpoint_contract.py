from __future__ import annotations

from threading import RLock
from types import SimpleNamespace

from core.app_runtime.managers.execution import ExecutionManager
from core.contracts.remote_endpoints import (
    REMOTE_ENDPOINTS,
    WORKFLOW_REVISION_READ,
    RemoteEndpointContractError,
    render_remote_endpoint_path,
)
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


def test_workflow_revision_read_endpoint_is_contract_rendered() -> None:
    endpoint = REMOTE_ENDPOINTS[WORKFLOW_REVISION_READ]

    assert endpoint.method == "GET"
    assert endpoint.operation_id == "getWorkflowRevision"
    assert endpoint.governance_action == "workflow_revision.read"
    assert endpoint.query_params == ()
    assert endpoint.response_item_key is None
    assert render_remote_endpoint_path(
        WORKFLOW_REVISION_READ,
        {"workflow_revision_id": "wfrev with/slash"},
    ) == "/api/v1/workflow-revisions/wfrev%20with%2Fslash"


def test_workflow_revision_read_rejects_local_runner_selection_query() -> None:
    try:
        render_remote_endpoint_path(
            WORKFLOW_REVISION_READ,
            {"workflow_revision_id": "wfrev_1"},
            query_values={"serverId": "srv_1"},
        )
    except RemoteEndpointContractError as exc:
        assert exc.code == "REMOTE_ENDPOINT_QUERY_PARAM_UNKNOWN"
    else:  # pragma: no cover - fail loudly keeps this branch unreachable.
        raise AssertionError("workflow revision serverId must remain local-only")


def test_workflow_revision_read_uses_generic_endpoint_caller() -> None:
    client = FakeEndpointClient()

    result = call_remote_endpoint(
        client,
        WORKFLOW_REVISION_READ,
        path_values={"workflow_revision_id": "wfrev_1"},
    )

    assert result == {"path": "/api/v1/workflow-revisions/wfrev_1"}
    assert client.calls == [("GET", "/api/v1/workflow-revisions/wfrev_1")]


def test_workflow_revision_proxy_uses_registry_path() -> None:
    proxy = FakeProxy()

    result = proxy.call_remote_endpoint(
        server_id="srv_1",
        ssh_service=object(),
        server_record={"server_id": "srv_1"},
        endpoint_id=WORKFLOW_REVISION_READ,
        path_values={"workflow_revision_id": "wfrev_1"},
        query_values={},
    )

    assert result == {"path": "/api/v1/workflow-revisions/wfrev_1"}
    assert proxy.client.calls == [("GET", "/api/v1/workflow-revisions/wfrev_1")]


def test_execution_manager_reads_workflow_revision_through_endpoint_contract() -> None:
    service = FakeRuntimeService()
    manager = ExecutionManager(service)

    assert manager.get_workflow_revision("wfrev_1", server_id="srv_revision") == {
        "data": {
            "endpointId": WORKFLOW_REVISION_READ,
            "pathValues": {"workflow_revision_id": "wfrev_1"},
            "queryValues": {},
        }
    }
    assert service.remote_runner_manager.calls == [
        (WORKFLOW_REVISION_READ, {"workflow_revision_id": "wfrev_1"}, {}),
    ]


class FakeEndpointClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, object]:
        assert accepted_statuses == {200}
        self.calls.append(("GET", path))
        return {"data": {"path": path}}


class FakeProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = FakeEndpointClient()

    def _get_client(self, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        return self.client


class FakeRuntimeService:
    def __init__(self) -> None:
        self._lock = RLock()
        self.remote_runner_manager = FakeRemoteEndpointManager()
        self._service_locator = SimpleNamespace(remote_runner_manager=self.remote_runner_manager)

    def _ensure_initialized(self) -> None:
        return None

    def _require_runner_ready(self, *, preferred_server_id=None):
        assert preferred_server_id == "srv_revision"
        return "srv_1", object(), {"server_id": "srv_1"}

    def _call_remote_runner(self, method, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        return method(**kwargs)


class FakeRemoteEndpointManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def call_remote_endpoint(self, **kwargs) -> dict[str, object]:
        path_values = dict(kwargs["path_values"])
        query_values = dict(kwargs.get("query_values") or {})
        self.calls.append((str(kwargs["endpoint_id"]), path_values, query_values))
        return {"endpointId": kwargs["endpoint_id"], "pathValues": path_values, "queryValues": query_values}
