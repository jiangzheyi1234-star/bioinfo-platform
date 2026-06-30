from __future__ import annotations

from pathlib import Path
from typing import Any

from core.contracts.remote_endpoints import REMOTE_ENDPOINTS, remote_endpoint_success_status, render_remote_endpoint_path
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
    assert remote_endpoint_success_status(TOOL_CREATE) == 201
    assert remote_endpoint_success_status(TOOL_PREPARE_JOB_CREATE) == 202
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
    local_route_source = _source("apps/api/tool_routes.py")
    remote_route_source = _source("apps/remote_runner/tool_routes.py")
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
    for route_source in (local_route_source, remote_route_source):
        assert "remote_endpoint_success_status(TOOL_CREATE)" in route_source
        assert "remote_endpoint_success_status(TOOL_PREPARE_JOB_CREATE)" in route_source
        assert "status_code=201" not in route_source
        assert "status_code=202" not in route_source


def test_tool_validation_plan_paths_are_registry_owned() -> None:
    from apps.api.tool_validation_plan import (
        tool_prepare_job_poll_path,
        tool_prepare_job_poll_path_template,
        tool_prepare_job_queue_method,
        tool_prepare_job_queue_path,
        tool_prepare_job_submit_path,
    )

    plan_source = _source("apps/api/tool_validation_plan.py")
    capability_source = _source("apps/api/tool_capability_service.py")

    assert tool_prepare_job_submit_path() == "/api/v1/tools/prepare-jobs"
    assert tool_prepare_job_poll_path_template() == "/api/v1/tools/prepare-jobs/{jobId}"
    assert tool_prepare_job_poll_path("job/1") == "/api/v1/tools/prepare-jobs/job%2F1"
    assert tool_prepare_job_queue_method() == "GET"
    assert tool_prepare_job_queue_path() == "/api/v1/tools/prepare-jobs/queue"
    assert "TOOL_PREPARE_JOB_CREATE" in plan_source
    assert "TOOL_PREPARE_JOB_READ" in plan_source
    assert "TOOL_PREPARE_JOB_QUEUE_READ" in plan_source
    assert "render_remote_endpoint_path(TOOL_PREPARE_JOB_READ" in plan_source
    assert '"/api/v1/tools/prepare-jobs"' not in plan_source
    assert "tool_prepare_job_queue_method()" in capability_source
    assert "tool_prepare_job_queue_path()" in capability_source
    assert "tool_prepare_job_poll_path(job_id)" in capability_source
    assert 'f"/api/v1/tools/prepare-jobs/{job_id}"' not in capability_source


def test_tool_production_plan_path_is_registry_owned(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance
    from apps.api.tool_candidate_target_acceptance import (
        tool_production_submit_method,
        tool_production_submit_path_template,
    )

    plan_source = _source("apps/api/tool_candidate_target_acceptance.py")

    production_endpoint = REMOTE_ENDPOINTS[TOOL_PRODUCTION_ENABLE]
    assert tool_production_submit_method() == production_endpoint.method
    assert tool_production_submit_path_template() == (
        production_endpoint.path_template.replace("{tool_id}", "{toolId}")
    )
    assert "TOOL_PRODUCTION_ENABLE" in plan_source
    assert "tool_production_submit_method()" in plan_source
    assert "tool_production_submit_path_template()" in plan_source
    assert '"/api/v1/tools/{toolId}/production"' not in plan_source

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {"total": 0, "items": []},
    )
    monkeypatch.setattr(tool_candidate_target_acceptance, "all_tool_profiles", list)
    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(
        registered_tools=[
            {
                "id": "bioconda::fastqc",
                "toolContract": {"state": "WorkflowReady", "workflowReady": True},
            }
        ],
        catalog={
            "total": 0,
            "sourceCounts": {},
            "addableDraftCounts": {"total": 0},
            "qualityCounts": {
                "discovered": 0,
                "draftRunnable": 0,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )

    assert report["productionQueue"]["items"][0]["productionPlan"]["submit"] == {
        "method": production_endpoint.method,
        "pathTemplate": production_endpoint.path_template.replace(
            "{tool_id}", "{toolId}"
        ),
        "payloadRef": "productionEvidence",
    }


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
