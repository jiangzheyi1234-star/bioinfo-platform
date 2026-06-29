from __future__ import annotations

from pathlib import Path
from typing import Any

from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, render_remote_endpoint_path
from core.contracts.tool_remote_endpoints import (
    TOOL_CREATE,
    TOOL_DELETE,
    TOOL_PREPARE_JOB_CANCEL,
    TOOL_PREPARE_JOB_CREATE,
    TOOL_PREPARE_JOB_LATEST_READ,
    TOOL_PREPARE_JOB_QUEUE_READ,
    TOOL_PREPARE_JOB_READ,
    TOOL_PRODUCTION_ENABLE,
    TOOL_RULE_TEMPLATE_UPDATE,
)
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


ROOT = Path(__file__).resolve().parents[1]
TOOL_COMMAND_ENDPOINTS = (
    TOOL_CREATE,
    TOOL_PREPARE_JOB_CREATE,
    TOOL_PREPARE_JOB_CANCEL,
    TOOL_RULE_TEMPLATE_UPDATE,
    TOOL_DELETE,
    TOOL_PRODUCTION_ENABLE,
)
TOOL_PREPARE_READ_ENDPOINTS = (
    TOOL_PREPARE_JOB_LATEST_READ,
    TOOL_PREPARE_JOB_QUEUE_READ,
    TOOL_PREPARE_JOB_READ,
)
TOOL_LOCAL_ENDPOINTS = (
    TOOL_CREATE,
    TOOL_PREPARE_JOB_CREATE,
    TOOL_PREPARE_JOB_QUEUE_READ,
    TOOL_PREPARE_JOB_READ,
    TOOL_PREPARE_JOB_CANCEL,
    TOOL_RULE_TEMPLATE_UPDATE,
    TOOL_DELETE,
    TOOL_PRODUCTION_ENABLE,
)


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_tool_command_and_prepare_endpoints_are_registry_owned() -> None:
    assert render_remote_endpoint_path(TOOL_CREATE, {}) == "/api/v1/tools"
    assert render_remote_endpoint_path(TOOL_PREPARE_JOB_CREATE, {}) == "/api/v1/tools/prepare-jobs"
    assert (
        render_remote_endpoint_path(
            TOOL_PREPARE_JOB_LATEST_READ,
            {},
            query_values={"toolIds": "bioconda::fastqc,conda-forge::multiqc"},
        )
        == "/api/v1/tools/prepare-jobs?toolIds=bioconda%3A%3Afastqc%2Cconda-forge%3A%3Amultiqc"
    )
    assert (
        render_remote_endpoint_path(
            TOOL_PREPARE_JOB_QUEUE_READ,
            {},
            query_values={"status": "running", "limit": 10, "offset": 5},
        )
        == "/api/v1/tools/prepare-jobs/queue?status=running&limit=10&offset=5"
    )
    assert (
        render_remote_endpoint_path(TOOL_PREPARE_JOB_READ, {"job_id": "job/1"})
        == "/api/v1/tools/prepare-jobs/job%2F1"
    )
    assert (
        render_remote_endpoint_path(TOOL_RULE_TEMPLATE_UPDATE, {"tool_id": "bioconda::fastqc"})
        == "/api/v1/tools/bioconda%3A%3Afastqc/rule-template"
    )

    assert REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_CREATE].accepted_statuses == (202,)
    assert REMOTE_ENDPOINTS[TOOL_CREATE].accepted_statuses == (201,)
    assert REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_LATEST_READ].response_item_key == "byToolId"
    for endpoint_id in TOOL_COMMAND_ENDPOINTS:
        assert REMOTE_ENDPOINTS[endpoint_id].invalidates


def test_tool_command_endpoint_contracts_match_governance_policy() -> None:
    governance_by_route = {
        (policy.method, policy.route): policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }
    for endpoint_id in TOOL_COMMAND_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        policy = governance_by_route[(endpoint.method, endpoint.path_template)]
        assert policy.action == endpoint.governance_action


def test_tool_command_endpoint_contracts_match_openapi_operation_ids_and_statuses() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for endpoint_id in TOOL_LOCAL_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        operation = local_app.openapi()["paths"][endpoint.path_template][endpoint.method.lower()]
        assert operation["operationId"] == endpoint.operation_id
        for status in endpoint.accepted_statuses:
            assert str(status) in operation["responses"]

    for endpoint_id in (*TOOL_LOCAL_ENDPOINTS, TOOL_PREPARE_JOB_LATEST_READ):
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        operation = remote_app.openapi()["paths"][endpoint.path_template][endpoint.method.lower()]
        assert operation["operationId"] == endpoint.operation_id
        for status in endpoint.accepted_statuses:
            assert str(status) in operation["responses"]


def test_tool_endpoint_caller_supports_command_and_prepare_shapes() -> None:
    client = FakeToolCommandClient()

    created = call_remote_endpoint(client, TOOL_CREATE, path_values={}, payload={"id": "bioconda::fastqc"})
    prepare = call_remote_endpoint(client, TOOL_PREPARE_JOB_CREATE, path_values={}, payload={"id": "bioconda::fastqc"})
    latest = call_remote_endpoint(
        client,
        TOOL_PREPARE_JOB_LATEST_READ,
        path_values={},
        query_values={"toolIds": "bioconda::fastqc"},
    )
    queue = call_remote_endpoint(
        client,
        TOOL_PREPARE_JOB_QUEUE_READ,
        path_values={},
        query_values={"limit": 10, "offset": 0},
    )
    detail = call_remote_endpoint(client, TOOL_PREPARE_JOB_READ, path_values={"job_id": "job_1"})
    cancelled = call_remote_endpoint(client, TOOL_PREPARE_JOB_CANCEL, path_values={"job_id": "job_1"})
    updated = call_remote_endpoint(
        client,
        TOOL_RULE_TEMPLATE_UPDATE,
        path_values={"tool_id": "bioconda::fastqc"},
        payload={"ruleTemplate": {"commandTemplate": "fastqc {input.reads:q}"}},
    )
    deleted = call_remote_endpoint(client, TOOL_DELETE, path_values={"tool_id": "bioconda::fastqc"})
    production = call_remote_endpoint(
        client,
        TOOL_PRODUCTION_ENABLE,
        path_values={"tool_id": "bioconda::fastqc"},
        payload={"runId": "run_1"},
    )

    assert created == {"id": "bioconda::fastqc"}
    assert prepare == {"jobId": "job_1", "status": "queued"}
    assert latest == {"bioconda::fastqc": {"jobId": "job_1"}}
    assert queue == {"items": [{"jobId": "job_1"}], "total": 1}
    assert detail == {"jobId": "job_1", "status": "queued"}
    assert cancelled == {"jobId": "job_1", "status": "cancelled"}
    assert updated == {"id": "bioconda::fastqc", "ruleTemplate": {"commandTemplate": "fastqc {input.reads:q}"}}
    assert deleted == {"id": "bioconda::fastqc", "deleted": True}
    assert production == {"id": "bioconda::fastqc", "productionEnabled": True}
    assert client.calls == [
        ("POST", "/api/v1/tools", [201]),
        ("POST", "/api/v1/tools/prepare-jobs", [202]),
        ("GET", "/api/v1/tools/prepare-jobs?toolIds=bioconda%3A%3Afastqc", [200]),
        ("GET", "/api/v1/tools/prepare-jobs/queue?limit=10&offset=0", [200]),
        ("GET", "/api/v1/tools/prepare-jobs/job_1", [200]),
        ("POST", "/api/v1/tools/prepare-jobs/job_1/cancel", [200]),
        ("PATCH", "/api/v1/tools/bioconda%3A%3Afastqc/rule-template", [200]),
        ("DELETE", "/api/v1/tools/bioconda%3A%3Afastqc", [200]),
        ("POST", "/api/v1/tools/bioconda%3A%3Afastqc/production", [200]),
    ]


def test_tool_command_methods_do_not_reappear_on_transport_or_proxy() -> None:
    for method_name in (
        "add_tool",
        "create_tool_prepare_job",
        "list_latest_tool_prepare_jobs",
        "list_tool_prepare_job_queue",
        "get_tool_prepare_job",
        "cancel_tool_prepare_job",
        "update_tool_rule_template",
        "delete_tool",
        "mark_tool_production_enabled",
    ):
        assert not hasattr(RemoteRunnerHttpClient, method_name)
        assert not hasattr(RemoteRunnerProxyMixin, method_name)


def test_tool_command_manager_delegates_to_endpoint_registry() -> None:
    manager_source = _source("core/app_runtime/managers/tool.py")
    proxy_source = _source("core/remote_runner/proxy.py")
    for endpoint_name in (
        "TOOL_CREATE",
        "TOOL_PREPARE_JOB_CREATE",
        "TOOL_PREPARE_JOB_LATEST_READ",
        "TOOL_PREPARE_JOB_QUEUE_READ",
        "TOOL_PREPARE_JOB_READ",
        "TOOL_PREPARE_JOB_CANCEL",
        "TOOL_RULE_TEMPLATE_UPDATE",
        "TOOL_DELETE",
        "TOOL_PRODUCTION_ENABLE",
    ):
        assert endpoint_name in manager_source

    assert "call_remote_endpoint(" in manager_source
    for method_name in (
        "add_tool",
        "create_tool_prepare_job",
        "list_latest_tool_prepare_jobs",
        "list_tool_prepare_job_queue",
        "get_tool_prepare_job",
        "cancel_tool_prepare_job",
        "update_tool_rule_template",
        "delete_tool",
        "mark_tool_production_enabled",
    ):
        assert f'call_existing_runner("{method_name}"' not in manager_source
        assert f"def {method_name}(" not in proxy_source
    assert 'client.post_json("/api/v1/tools"' not in proxy_source
    assert 'client.get_json(f"/api/v1/tools/prepare-jobs' not in proxy_source


class FakeToolCommandClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[int]]] = []

    def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        self.calls.append(("GET", path, sorted(accepted_statuses or [])))
        if path.startswith("/api/v1/tools/prepare-jobs?"):
            return {"data": {"items": [{"jobId": "job_1"}], "byToolId": {"bioconda::fastqc": {"jobId": "job_1"}}}}
        if path.startswith("/api/v1/tools/prepare-jobs/queue?"):
            return {"data": {"items": [{"jobId": "job_1"}], "total": 1}}
        return {"data": {"jobId": "job_1", "status": "queued"}}

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("POST", path, sorted(accepted_statuses or [])))
        if path == "/api/v1/tools":
            return {"data": {"id": payload["id"]}}
        if path == "/api/v1/tools/prepare-jobs":
            return {"data": {"jobId": "job_1", "status": "queued"}}
        if path.endswith("/cancel"):
            return {"data": {"jobId": "job_1", "status": "cancelled"}}
        return {"data": {"id": "bioconda::fastqc", "productionEnabled": True}}

    def patch_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("PATCH", path, sorted(accepted_statuses or [])))
        return {"data": {"id": "bioconda::fastqc", "ruleTemplate": dict(payload["ruleTemplate"])}}

    def delete_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        self.calls.append(("DELETE", path, sorted(accepted_statuses or [])))
        return {"data": {"id": "bioconda::fastqc", "deleted": True}}
