from __future__ import annotations

from pathlib import Path
from threading import RLock
from types import SimpleNamespace

from core.app_runtime.managers.execution import ExecutionManager
from core.contracts.remote_endpoints import (
    ARTIFACT_CACHE_ENTRIES_READ,
    ARTIFACT_CACHE_PINS_READ,
    ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ,
    ARTIFACT_LIFECYCLE_USAGE_READ,
    GOVERNANCE_AUDIT_EVENTS_READ,
    REMOTE_ENDPOINTS,
    RESULT_AUDIT_READ,
    RESULT_LIST,
    RESULT_PACKAGE_EXPORT_LIST,
    RESULT_PREVIEW_READ,
    RESULT_READ,
    RUN_ATTEMPTS_READ,
    RUN_EVENTS_READ,
    RUN_EXECUTION_CONTEXT_READ,
    RUN_FAILURE_LOCATOR_READ,
    RUN_LIST,
    RUN_LOGS_READ,
    RUN_READ,
    RUN_RESULTS_READ,
    RUN_RULES_READ,
    SECRET_PROVIDER_READINESS_READ,
    WORKFLOW_BACKFILL_LAUNCH_LIST,
    WORKFLOW_BACKFILL_LAUNCH_READ,
    WORKFLOW_REVISION_READ,
    WORKFLOW_TRIGGER_EVENTS_READ,
    WORKFLOW_TRIGGER_INBOX_READ,
    WORKFLOW_TRIGGER_LIST,
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
    WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
    RemoteEndpointContractError,
    render_remote_endpoint_path,
)
from core.governance_policy import HIGH_RISK_API_POLICIES
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.endpoint_caller import call_remote_endpoint
from core.remote_runner.proxy import RemoteRunnerProxyMixin


ROOT = Path(__file__).resolve().parents[1]
RUN_READ_MODEL_ENDPOINTS = (
    RUN_LIST,
    RUN_READ,
    RUN_EVENTS_READ,
    RUN_EXECUTION_CONTEXT_READ,
    RUN_ATTEMPTS_READ,
    RUN_LOGS_READ,
    RUN_RESULTS_READ,
    RUN_RULES_READ,
    RUN_FAILURE_LOCATOR_READ,
    WORKFLOW_REVISION_READ,
)
RESULT_READ_MODEL_ENDPOINTS = (
    RESULT_LIST,
    RESULT_READ,
    RESULT_PREVIEW_READ,
    RESULT_AUDIT_READ,
    RESULT_PACKAGE_EXPORT_LIST,
)
ARTIFACT_READ_MODEL_ENDPOINTS = (
    ARTIFACT_LIFECYCLE_USAGE_READ,
    ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ,
    ARTIFACT_CACHE_ENTRIES_READ,
    ARTIFACT_CACHE_PINS_READ,
)
TRIGGER_READ_MODEL_ENDPOINTS = (
    WORKFLOW_TRIGGER_LIST,
    WORKFLOW_TRIGGER_EVENTS_READ,
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
    WORKFLOW_TRIGGER_INBOX_READ,
    WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
    WORKFLOW_BACKFILL_LAUNCH_LIST,
    WORKFLOW_BACKFILL_LAUNCH_READ,
)
GOVERNANCE_READ_MODEL_ENDPOINTS = (
    GOVERNANCE_AUDIT_EVENTS_READ,
    SECRET_PROVIDER_READINESS_READ,
)
CONTRACT_READ_MODEL_ENDPOINTS = (
    RUN_READ_MODEL_ENDPOINTS
    + RESULT_READ_MODEL_ENDPOINTS
    + ARTIFACT_READ_MODEL_ENDPOINTS
    + TRIGGER_READ_MODEL_ENDPOINTS
    + GOVERNANCE_READ_MODEL_ENDPOINTS
)


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remote_runner_execution_proxy_exposes_retry_run_path() -> None:
    proxy_source = _source("core/remote_runner/proxy.py")

    assert "def retry_run(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/retry", kwargs["payload"])["data"]' in proxy_source


def test_remote_runner_execution_proxy_exposes_rule_retry_and_resume_paths() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    proxy_source = _source("core/remote_runner/reexecution_proxy.py")

    assert "from core.remote_runner.reexecution_proxy import RemoteRunnerReexecutionProxyMixin" in manager_source
    assert "RemoteRunnerReexecutionProxyMixin" in manager_source
    assert "class RemoteRunnerReexecutionProxyMixin:" in proxy_source
    assert "def retry_run_rules(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/rules/retry", kwargs["payload"])["data"]' in proxy_source
    assert "def apply_rule_output_invalidation(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/output-invalidation/apply"' in proxy_source
    assert "def prepare_rule_cache_restore_staged_files(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/staged-files/prepare"' in proxy_source
    assert "def apply_rule_cache_restore_staged_files(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/staged-files/apply"' in proxy_source
    assert "def prepare_rule_cache_restore_final_outputs(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/final-outputs/prepare"' in proxy_source
    assert "def apply_rule_cache_restore_final_outputs(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/final-outputs/apply"' in proxy_source
    assert "def prepare_rule_cache_restore_adoption(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/adoption/prepare"' in proxy_source
    assert "def apply_rule_cache_restore_adoption(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/adoption/apply"' in proxy_source
    assert "def resume_run(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/resume", kwargs["payload"])["data"]' in proxy_source


def test_run_read_model_endpoints_are_contract_rendered() -> None:
    assert set(REMOTE_ENDPOINTS) >= set(RUN_READ_MODEL_ENDPOINTS)
    assert render_remote_endpoint_path(RUN_LIST, {}) == "/api/v1/runs"
    assert REMOTE_ENDPOINTS[RUN_LIST].response_item_key == "items"
    assert render_remote_endpoint_path(RUN_READ, {"run_id": "run_1"}) == "/api/v1/runs/run_1"
    assert render_remote_endpoint_path(
        RUN_EXECUTION_CONTEXT_READ,
        {"run_id": "run with/slash"},
    ) == "/api/v1/runs/run%20with%2Fslash/execution-context"
    assert render_remote_endpoint_path(RUN_RULES_READ, {"run_id": "run_1"}) == "/api/v1/runs/run_1/rules"
    assert render_remote_endpoint_path(
        RUN_FAILURE_LOCATOR_READ,
        {"run_id": "run_1"},
    ) == "/api/v1/runs/run_1/failure-locator"
    assert render_remote_endpoint_path(
        RUN_LOGS_READ,
        {"run_id": "run_1"},
        query_values={"stream": "stderr", "cursor": "128"},
    ) == "/api/v1/runs/run_1/logs?stream=stderr&cursor=128"
    assert render_remote_endpoint_path(RESULT_LIST, {}) == "/api/v1/results"
    assert REMOTE_ENDPOINTS[RESULT_LIST].response_item_key == "items"
    assert render_remote_endpoint_path(RESULT_READ, {"result_id": "res with/slash"}) == "/api/v1/results/res%20with%2Fslash"
    assert render_remote_endpoint_path(
        RESULT_PREVIEW_READ,
        {"result_id": "res_1"},
        query_values={"artifact_id": "art with/slash"},
    ) == "/api/v1/results/res_1/preview?artifact_id=art+with%2Fslash"
    assert render_remote_endpoint_path(RESULT_AUDIT_READ, {"result_id": "res_1"}) == "/api/v1/results/res_1/audit"
    assert render_remote_endpoint_path(
        RESULT_PACKAGE_EXPORT_LIST,
        {"result_id": "res_1"},
        query_values={"lifecycleState": "retired", "limit": 25},
    ) == "/api/v1/results/res_1/exports?lifecycleState=retired&limit=25"
    assert REMOTE_ENDPOINTS[RUN_RULES_READ].operation_id == "getRunRules"
    assert REMOTE_ENDPOINTS[RUN_RULES_READ].response_schema == "run-rules.v1"
    assert REMOTE_ENDPOINTS[RUN_RULES_READ].cache_scope == "run-read-model"
    assert REMOTE_ENDPOINTS[RESULT_PACKAGE_EXPORT_LIST].response_schema == "result-package-export-list.v1"
    assert render_remote_endpoint_path(
        ARTIFACT_LIFECYCLE_USAGE_READ,
        {},
        query_values={"quotaBytes": 4096},
    ) == "/api/v1/artifacts/lifecycle/usage?quotaBytes=4096"
    assert render_remote_endpoint_path(
        ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ,
        {},
        query_values={"limit": 5},
    ) == "/api/v1/artifacts/lifecycle/controller/ticks?limit=5"
    assert render_remote_endpoint_path(
        ARTIFACT_CACHE_ENTRIES_READ,
        {},
        query_values={"workflowRevisionId": "wf rev/1", "limit": 10},
    ) == "/api/v1/artifacts/cache/entries?workflowRevisionId=wf+rev%2F1&limit=10"
    assert render_remote_endpoint_path(
        ARTIFACT_CACHE_PINS_READ,
        {},
        query_values={"cacheEntryId": "ace/1", "state": "active", "limit": 10},
    ) == "/api/v1/artifacts/cache/pins?cacheEntryId=ace%2F1&state=active&limit=10"
    assert render_remote_endpoint_path(WORKFLOW_TRIGGER_LIST, {}) == "/api/v1/workflow-triggers"
    assert REMOTE_ENDPOINTS[WORKFLOW_TRIGGER_LIST].response_item_key is None
    assert render_remote_endpoint_path(
        WORKFLOW_TRIGGER_EVENTS_READ,
        {"trigger_id": "wtr with/slash"},
    ) == "/api/v1/workflow-triggers/wtr%20with%2Fslash/events"
    assert render_remote_endpoint_path(
        WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
        {"trigger_id": "wtr_1"},
    ) == "/api/v1/workflow-triggers/wtr_1/readiness-observation"
    assert render_remote_endpoint_path(
        WORKFLOW_TRIGGER_INBOX_READ,
        {"trigger_id": "wtr_1"},
        query_values={"state": "dead_lettered", "limit": 50},
    ) == "/api/v1/workflow-triggers/wtr_1/inbox?state=dead_lettered&limit=50"
    assert render_remote_endpoint_path(
        WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
        {},
        query_values={"limit": 8},
    ) == "/api/v1/workflow-trigger-scheduler/ticks?limit=8"
    assert render_remote_endpoint_path(
        WORKFLOW_BACKFILL_LAUNCH_LIST,
        {},
        query_values={"triggerId": "wtr with/slash", "limit": 25},
    ) == "/api/v1/workflow-backfill-launches?triggerId=wtr+with%2Fslash&limit=25"
    assert render_remote_endpoint_path(
        WORKFLOW_BACKFILL_LAUNCH_READ,
        {"launch_id": "bfl with/slash"},
    ) == "/api/v1/workflow-backfill-launches/bfl%20with%2Fslash"
    assert render_remote_endpoint_path(
        GOVERNANCE_AUDIT_EVENTS_READ,
        {},
        query_values={"subjectKind": "run", "subjectId": "run/1", "action": "run.submit", "limit": 25},
    ) == "/api/v1/audit/events?subjectKind=run&subjectId=run%2F1&action=run.submit&limit=25"
    assert render_remote_endpoint_path(SECRET_PROVIDER_READINESS_READ, {}) == "/api/v1/secrets/provider-readiness"
    assert REMOTE_ENDPOINTS[GOVERNANCE_AUDIT_EVENTS_READ].response_item_key is None
    assert REMOTE_ENDPOINTS[SECRET_PROVIDER_READINESS_READ].response_item_key is None


def test_run_read_model_endpoint_contracts_match_governance_policy() -> None:
    governance_by_action = {
        policy.action: policy
        for policy in HIGH_RISK_API_POLICIES
        if policy.surface == "remote-runner-api"
    }

    for endpoint_id in CONTRACT_READ_MODEL_ENDPOINTS:
        endpoint = REMOTE_ENDPOINTS[endpoint_id]
        if endpoint.governance_action is None:
            continue
        policy = governance_by_action[endpoint.governance_action]
        assert policy.method == endpoint.method
        assert policy.route == endpoint.path_template


def test_run_read_model_endpoint_contracts_match_openapi_operation_ids() -> None:
    from apps.api.main import app as local_app
    from apps.remote_runner.main import app as remote_app

    for app in (local_app, remote_app):
        paths = app.openapi()["paths"]
        for endpoint_id in CONTRACT_READ_MODEL_ENDPOINTS:
            endpoint = REMOTE_ENDPOINTS[endpoint_id]
            operation = paths[endpoint.path_template][endpoint.method.lower()]
            assert operation["operationId"] == endpoint.operation_id


def test_remote_endpoint_contracts_fail_loudly_on_missing_path_param() -> None:
    try:
        render_remote_endpoint_path(RUN_RULES_READ, {})
    except RemoteEndpointContractError as exc:
        assert exc.code == "REMOTE_ENDPOINT_PATH_PARAM_REQUIRED"
    else:  # pragma: no cover - fail loudly keeps this branch unreachable.
        raise AssertionError("missing run_id should fail")

    try:
        render_remote_endpoint_path(RUN_LOGS_READ, {"run_id": "run_1"}, query_values={"unknown": "x"})
    except RemoteEndpointContractError as exc:
        assert exc.code == "REMOTE_ENDPOINT_QUERY_PARAM_UNKNOWN"
    else:  # pragma: no cover - fail loudly keeps this branch unreachable.
        raise AssertionError("unknown query param should fail")

    try:
        render_remote_endpoint_path(RESULT_PREVIEW_READ, {"result_id": "res_1"}, query_values={"unknown": "x"})
    except RemoteEndpointContractError as exc:
        assert exc.code == "REMOTE_ENDPOINT_QUERY_PARAM_UNKNOWN"
    else:  # pragma: no cover - fail loudly keeps this branch unreachable.
        raise AssertionError("unknown result preview query param should fail")

    try:
        render_remote_endpoint_path(RESULT_PACKAGE_EXPORT_LIST, {"result_id": "res_1"}, query_values={"serverId": "srv_1"})
    except RemoteEndpointContractError as exc:
        assert exc.code == "REMOTE_ENDPOINT_QUERY_PARAM_UNKNOWN"
    else:  # pragma: no cover - fail loudly keeps this branch unreachable.
        raise AssertionError("serverId must remain a local runner-selection value")

    try:
        render_remote_endpoint_path(ARTIFACT_CACHE_ENTRIES_READ, {}, query_values={"serverId": "srv_1"})
    except RemoteEndpointContractError as exc:
        assert exc.code == "REMOTE_ENDPOINT_QUERY_PARAM_UNKNOWN"
    else:  # pragma: no cover - fail loudly keeps this branch unreachable.
        raise AssertionError("artifact cache serverId must remain local-only")

    try:
        render_remote_endpoint_path(WORKFLOW_TRIGGER_INBOX_READ, {"trigger_id": "wtr_1"}, query_values={"serverId": "srv_1"})
    except RemoteEndpointContractError as exc:
        assert exc.code == "REMOTE_ENDPOINT_QUERY_PARAM_UNKNOWN"
    else:  # pragma: no cover - fail loudly keeps this branch unreachable.
        raise AssertionError("workflow trigger serverId must remain local-only")


def test_remote_endpoint_caller_unwraps_data_and_records_path() -> None:
    client = FakeEndpointClient()

    data = call_remote_endpoint(client, RUN_RULES_READ, path_values={"run_id": "run_1"})
    runs = call_remote_endpoint(client, RUN_LIST, path_values={})
    results = call_remote_endpoint(client, RESULT_LIST, path_values={})
    package_exports = call_remote_endpoint(
        client,
        RESULT_PACKAGE_EXPORT_LIST,
        path_values={"result_id": "res_1"},
        query_values={"lifecycleState": "retired", "limit": 25},
    )
    cache_entries = call_remote_endpoint(
        client,
        ARTIFACT_CACHE_ENTRIES_READ,
        path_values={},
        query_values={"workflowRevisionId": "wf_rev_1", "limit": 10},
    )
    inbox = call_remote_endpoint(
        client,
        WORKFLOW_TRIGGER_INBOX_READ,
        path_values={"trigger_id": "wtr_1"},
        query_values={"state": "dead_lettered", "limit": 50},
    )
    audit = call_remote_endpoint(
        client,
        GOVERNANCE_AUDIT_EVENTS_READ,
        path_values={},
        query_values={"subjectKind": "run", "subjectId": "run_1", "action": "run.submit", "limit": 25},
    )
    secret = call_remote_endpoint(client, SECRET_PROVIDER_READINESS_READ, path_values={})

    assert data == {"path": "/api/v1/runs/run_1/rules"}
    assert runs == [{"path": "/api/v1/runs"}]
    assert results == [{"path": "/api/v1/results"}]
    assert package_exports == {"path": "/api/v1/results/res_1/exports?lifecycleState=retired&limit=25"}
    assert cache_entries == {"path": "/api/v1/artifacts/cache/entries?workflowRevisionId=wf_rev_1&limit=10"}
    assert inbox == {"path": "/api/v1/workflow-triggers/wtr_1/inbox?state=dead_lettered&limit=50"}
    assert audit == {"path": "/api/v1/audit/events?subjectKind=run&subjectId=run_1&action=run.submit&limit=25"}
    assert secret == {"path": "/api/v1/secrets/provider-readiness"}
    assert client.calls == [
        ("GET", "/api/v1/runs/run_1/rules"),
        ("GET", "/api/v1/runs"),
        ("GET", "/api/v1/results"),
        ("GET", "/api/v1/results/res_1/exports?lifecycleState=retired&limit=25"),
        ("GET", "/api/v1/artifacts/cache/entries?workflowRevisionId=wf_rev_1&limit=10"),
        ("GET", "/api/v1/workflow-triggers/wtr_1/inbox?state=dead_lettered&limit=50"),
        ("GET", "/api/v1/audit/events?subjectKind=run&subjectId=run_1&action=run.submit&limit=25"),
        ("GET", "/api/v1/secrets/provider-readiness"),
    ]


def test_remote_runner_proxy_generic_endpoint_call_uses_registry() -> None:
    proxy = FakeProxy()

    listed = proxy.call_remote_endpoint(**_runner_kwargs(RUN_LIST))
    run = proxy.call_remote_endpoint(**_runner_kwargs(RUN_READ, "run_1"))
    context = proxy.call_remote_endpoint(**_runner_kwargs(RUN_EXECUTION_CONTEXT_READ, "run_1"))
    rules = proxy.call_remote_endpoint(**_runner_kwargs(RUN_RULES_READ, "run_1"))
    locator = proxy.call_remote_endpoint(**_runner_kwargs(RUN_FAILURE_LOCATOR_READ, "run_1"))
    logs = proxy.call_remote_endpoint(
        **_runner_kwargs(RUN_LOGS_READ, "run_1", query_values={"stream": "stderr", "cursor": "128"})
    )
    results = proxy.call_remote_endpoint(**_runner_kwargs(RESULT_LIST))
    result = proxy.call_remote_endpoint(**_result_kwargs(RESULT_READ, "res_1"))
    preview = proxy.call_remote_endpoint(
        **_result_kwargs(RESULT_PREVIEW_READ, "res_1", query_values={"artifact_id": "art_1"})
    )
    package_exports = proxy.call_remote_endpoint(
        **_result_kwargs(RESULT_PACKAGE_EXPORT_LIST, "res_1", query_values={"lifecycleState": "retired", "limit": 25})
    )
    cache_pins = proxy.call_remote_endpoint(
        **_endpoint_kwargs(ARTIFACT_CACHE_PINS_READ, query_values={"cacheEntryId": "ace_1", "state": "active", "limit": 5})
    )
    trigger_list = proxy.call_remote_endpoint(**_endpoint_kwargs(WORKFLOW_TRIGGER_LIST))
    trigger_events = proxy.call_remote_endpoint(**_trigger_kwargs(WORKFLOW_TRIGGER_EVENTS_READ, "wtr_1"))
    trigger_inbox = proxy.call_remote_endpoint(
        **_trigger_kwargs(WORKFLOW_TRIGGER_INBOX_READ, "wtr_1", query_values={"state": "submitted", "limit": 5})
    )
    backfill_launches = proxy.call_remote_endpoint(
        **_endpoint_kwargs(WORKFLOW_BACKFILL_LAUNCH_LIST, query_values={"triggerId": "wtr_1", "limit": 25})
    )
    backfill_launch = proxy.call_remote_endpoint(
        **_endpoint_kwargs(WORKFLOW_BACKFILL_LAUNCH_READ, path_values={"launch_id": "bfl_1"})
    )
    audit_events = proxy.call_remote_endpoint(
        **_endpoint_kwargs(
            GOVERNANCE_AUDIT_EVENTS_READ,
            query_values={"subjectKind": "run", "subjectId": "run_1", "action": "run.submit", "limit": 25},
        )
    )
    secret_readiness = proxy.call_remote_endpoint(**_endpoint_kwargs(SECRET_PROVIDER_READINESS_READ))

    assert listed == [{"path": "/api/v1/runs"}]
    assert run == {"path": "/api/v1/runs/run_1"}
    assert context == {"path": "/api/v1/runs/run_1/execution-context"}
    assert rules == {"path": "/api/v1/runs/run_1/rules"}
    assert locator == {"path": "/api/v1/runs/run_1/failure-locator"}
    assert logs == {"path": "/api/v1/runs/run_1/logs?stream=stderr&cursor=128"}
    assert results == [{"path": "/api/v1/results"}]
    assert result == {"path": "/api/v1/results/res_1"}
    assert preview == {"path": "/api/v1/results/res_1/preview?artifact_id=art_1"}
    assert package_exports == {"path": "/api/v1/results/res_1/exports?lifecycleState=retired&limit=25"}
    assert cache_pins == {"path": "/api/v1/artifacts/cache/pins?cacheEntryId=ace_1&state=active&limit=5"}
    assert trigger_list == {"path": "/api/v1/workflow-triggers"}
    assert trigger_events == {"path": "/api/v1/workflow-triggers/wtr_1/events"}
    assert trigger_inbox == {"path": "/api/v1/workflow-triggers/wtr_1/inbox?state=submitted&limit=5"}
    assert backfill_launches == {"path": "/api/v1/workflow-backfill-launches?triggerId=wtr_1&limit=25"}
    assert backfill_launch == {"path": "/api/v1/workflow-backfill-launches/bfl_1"}
    assert audit_events == {"path": "/api/v1/audit/events?subjectKind=run&subjectId=run_1&action=run.submit&limit=25"}
    assert secret_readiness == {"path": "/api/v1/secrets/provider-readiness"}
    assert proxy.client.calls == [
        ("GET", "/api/v1/runs"),
        ("GET", "/api/v1/runs/run_1"),
        ("GET", "/api/v1/runs/run_1/execution-context"),
        ("GET", "/api/v1/runs/run_1/rules"),
        ("GET", "/api/v1/runs/run_1/failure-locator"),
        ("GET", "/api/v1/runs/run_1/logs?stream=stderr&cursor=128"),
        ("GET", "/api/v1/results"),
        ("GET", "/api/v1/results/res_1"),
        ("GET", "/api/v1/results/res_1/preview?artifact_id=art_1"),
        ("GET", "/api/v1/results/res_1/exports?lifecycleState=retired&limit=25"),
        ("GET", "/api/v1/artifacts/cache/pins?cacheEntryId=ace_1&state=active&limit=5"),
        ("GET", "/api/v1/workflow-triggers"),
        ("GET", "/api/v1/workflow-triggers/wtr_1/events"),
        ("GET", "/api/v1/workflow-triggers/wtr_1/inbox?state=submitted&limit=5"),
        ("GET", "/api/v1/workflow-backfill-launches?triggerId=wtr_1&limit=25"),
        ("GET", "/api/v1/workflow-backfill-launches/bfl_1"),
        ("GET", "/api/v1/audit/events?subjectKind=run&subjectId=run_1&action=run.submit&limit=25"),
        ("GET", "/api/v1/secrets/provider-readiness"),
    ]


def test_execution_manager_calls_generic_remote_endpoint_for_run_read_models() -> None:
    service = FakeRuntimeService()
    manager = ExecutionManager(service)

    assert manager.list_runs() == [{"runId": "run_1"}]
    assert manager.get_run("run_1") == {
        "data": {"endpointId": RUN_READ, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert manager.get_run_events("run_1") == {
        "data": {"endpointId": RUN_EVENTS_READ, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert manager.get_run_execution_context("run_1") == {
        "data": {"endpointId": RUN_EXECUTION_CONTEXT_READ, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert manager.get_run_attempts("run_1") == {
        "data": {"endpointId": RUN_ATTEMPTS_READ, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert manager.get_run_logs("run_1", stream="stderr", cursor="128") == {
        "data": {
            "endpointId": RUN_LOGS_READ,
            "pathValues": {"run_id": "run_1"},
            "queryValues": {"stream": "stderr", "cursor": "128"},
        }
    }
    assert manager.get_run_results("run_1") == {
        "data": {"endpointId": RUN_RESULTS_READ, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert manager.get_run_rules("run_1") == {
        "data": {"endpointId": RUN_RULES_READ, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert manager.get_run_failure_locator("run_1") == {
        "data": {"endpointId": RUN_FAILURE_LOCATOR_READ, "pathValues": {"run_id": "run_1"}, "queryValues": {}}
    }
    assert manager.list_results() == {"data": {"items": [{"resultId": "res_1"}]}}
    assert manager.get_result("res_1") == {
        "data": {"endpointId": RESULT_READ, "pathValues": {"result_id": "res_1"}, "queryValues": {}}
    }
    assert manager.get_result_preview("res_1", artifact_id="art_1") == {
        "data": {
            "endpointId": RESULT_PREVIEW_READ,
            "pathValues": {"result_id": "res_1"},
            "queryValues": {"artifact_id": "art_1"},
        }
    }
    assert manager.get_result_audit("res_1") == {
        "data": {"endpointId": RESULT_AUDIT_READ, "pathValues": {"result_id": "res_1"}, "queryValues": {}}
    }
    assert manager.list_result_package_exports(
        "res_1",
        server_id="srv_package",
        lifecycle_state="retired",
        limit=25,
    ) == {
        "data": {
            "endpointId": RESULT_PACKAGE_EXPORT_LIST,
            "pathValues": {"result_id": "res_1"},
            "queryValues": {"lifecycleState": "retired", "limit": 25},
        }
    }
    assert manager.get_artifact_lifecycle_usage(server_id="srv_artifact", quota_bytes=4096) == {
        "data": {"endpointId": ARTIFACT_LIFECYCLE_USAGE_READ, "pathValues": {}, "queryValues": {"quotaBytes": 4096}}
    }
    assert manager.list_artifact_lifecycle_controller_ticks(server_id="srv_artifact", limit=5) == {
        "data": {"endpointId": ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ, "pathValues": {}, "queryValues": {"limit": 5}}
    }
    assert manager.list_artifact_cache_entries(
        server_id="srv_artifact",
        workflow_revision_id="wf_rev_1",
        limit=10,
    ) == {
        "data": {
            "endpointId": ARTIFACT_CACHE_ENTRIES_READ,
            "pathValues": {},
            "queryValues": {"workflowRevisionId": "wf_rev_1", "limit": 10},
        }
    }
    assert manager.list_artifact_cache_pins(
        server_id="srv_artifact",
        cache_entry_id="ace_1",
        state="active",
        limit=5,
    ) == {
        "data": {
            "endpointId": ARTIFACT_CACHE_PINS_READ,
            "pathValues": {},
            "queryValues": {"cacheEntryId": "ace_1", "state": "active", "limit": 5},
        }
    }
    assert manager.list_workflow_triggers() == {
        "data": {"endpointId": WORKFLOW_TRIGGER_LIST, "pathValues": {}, "queryValues": {}}
    }
    assert manager.list_workflow_trigger_events("wtr_1") == {
        "data": {"endpointId": WORKFLOW_TRIGGER_EVENTS_READ, "pathValues": {"trigger_id": "wtr_1"}, "queryValues": {}}
    }
    assert manager.get_workflow_trigger_readiness_observation("wtr_1") == {
        "data": {
            "endpointId": WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
            "pathValues": {"trigger_id": "wtr_1"},
            "queryValues": {},
        }
    }
    assert manager.list_workflow_trigger_inbox_events("wtr_1", state="submitted", limit=5) == {
        "data": {
            "endpointId": WORKFLOW_TRIGGER_INBOX_READ,
            "pathValues": {"trigger_id": "wtr_1"},
            "queryValues": {"state": "submitted", "limit": 5},
        }
    }
    assert manager.list_workflow_trigger_scheduler_ticks(limit=8) == {
        "data": {"endpointId": WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ, "pathValues": {}, "queryValues": {"limit": 8}}
    }
    assert manager.list_workflow_backfill_launches(trigger_id="wtr_1", limit=25) == {
        "data": {
            "endpointId": WORKFLOW_BACKFILL_LAUNCH_LIST,
            "pathValues": {},
            "queryValues": {"triggerId": "wtr_1", "limit": 25},
        }
    }
    assert manager.get_workflow_backfill_launch("bfl_1") == {
        "data": {"endpointId": WORKFLOW_BACKFILL_LAUNCH_READ, "pathValues": {"launch_id": "bfl_1"}, "queryValues": {}}
    }
    assert manager.list_governance_audit_events(
        server_id="srv_audit",
        subject_kind="run",
        subject_id="run_1",
        action="run.submit",
        limit=25,
    ) == {
        "data": {
            "endpointId": GOVERNANCE_AUDIT_EVENTS_READ,
            "pathValues": {},
            "queryValues": {"subjectKind": "run", "subjectId": "run_1", "action": "run.submit", "limit": 25},
        }
    }
    assert manager.get_secret_provider_readiness(server_id="srv_secret") == {
        "data": {"endpointId": SECRET_PROVIDER_READINESS_READ, "pathValues": {}, "queryValues": {}}
    }
    assert service.remote_runner_manager.calls == [
        (RUN_LIST, {}, {}),
        (RUN_READ, {"run_id": "run_1"}, {}),
        (RUN_EVENTS_READ, {"run_id": "run_1"}, {}),
        (RUN_EXECUTION_CONTEXT_READ, {"run_id": "run_1"}, {}),
        (RUN_ATTEMPTS_READ, {"run_id": "run_1"}, {}),
        (RUN_LOGS_READ, {"run_id": "run_1"}, {"stream": "stderr", "cursor": "128"}),
        (RUN_RESULTS_READ, {"run_id": "run_1"}, {}),
        (RUN_RULES_READ, {"run_id": "run_1"}, {}),
        (RUN_FAILURE_LOCATOR_READ, {"run_id": "run_1"}, {}),
        (RESULT_LIST, {}, {}),
        (RESULT_READ, {"result_id": "res_1"}, {}),
        (RESULT_PREVIEW_READ, {"result_id": "res_1"}, {"artifact_id": "art_1"}),
        (RESULT_AUDIT_READ, {"result_id": "res_1"}, {}),
        (RESULT_PACKAGE_EXPORT_LIST, {"result_id": "res_1"}, {"lifecycleState": "retired", "limit": 25}),
        (ARTIFACT_LIFECYCLE_USAGE_READ, {}, {"quotaBytes": 4096}),
        (ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ, {}, {"limit": 5}),
        (ARTIFACT_CACHE_ENTRIES_READ, {}, {"workflowRevisionId": "wf_rev_1", "limit": 10}),
        (ARTIFACT_CACHE_PINS_READ, {}, {"cacheEntryId": "ace_1", "state": "active", "limit": 5}),
        (WORKFLOW_TRIGGER_LIST, {}, {}),
        (WORKFLOW_TRIGGER_EVENTS_READ, {"trigger_id": "wtr_1"}, {}),
        (WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ, {"trigger_id": "wtr_1"}, {}),
        (WORKFLOW_TRIGGER_INBOX_READ, {"trigger_id": "wtr_1"}, {"state": "submitted", "limit": 5}),
        (WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ, {}, {"limit": 8}),
        (WORKFLOW_BACKFILL_LAUNCH_LIST, {}, {"triggerId": "wtr_1", "limit": 25}),
        (WORKFLOW_BACKFILL_LAUNCH_READ, {"launch_id": "bfl_1"}, {}),
        (GOVERNANCE_AUDIT_EVENTS_READ, {}, {"subjectKind": "run", "subjectId": "run_1", "action": "run.submit", "limit": 25}),
        (SECRET_PROVIDER_READINESS_READ, {}, {}),
    ]


def test_remote_runner_http_client_does_not_keep_migrated_semantic_methods() -> None:
    assert not hasattr(RemoteRunnerHttpClient, "get_run")
    assert not hasattr(RemoteRunnerHttpClient, "get_run_attempts")
    assert not hasattr(RemoteRunnerHttpClient, "get_run_execution_context")
    assert not hasattr(RemoteRunnerHttpClient, "get_run_results")
    assert not hasattr(RemoteRunnerHttpClient, "get_run_rules")
    assert not hasattr(RemoteRunnerHttpClient, "get_run_failure_locator")
    assert not hasattr(RemoteRunnerHttpClient, "list_results")
    assert not hasattr(RemoteRunnerHttpClient, "get_result")
    assert not hasattr(RemoteRunnerHttpClient, "get_result_preview")
    assert not hasattr(RemoteRunnerHttpClient, "get_result_audit")
    assert not hasattr(RemoteRunnerHttpClient, "list_result_package_exports")
    assert not hasattr(RemoteRunnerHttpClient, "get_artifact_lifecycle_usage")
    assert not hasattr(RemoteRunnerHttpClient, "list_artifact_lifecycle_controller_ticks")
    assert not hasattr(RemoteRunnerHttpClient, "list_artifact_cache_entries")
    assert not hasattr(RemoteRunnerHttpClient, "list_artifact_cache_pins")
    assert not hasattr(RemoteRunnerHttpClient, "list_workflow_triggers")
    assert not hasattr(RemoteRunnerHttpClient, "list_workflow_trigger_events")
    assert not hasattr(RemoteRunnerHttpClient, "get_workflow_trigger_readiness_observation")
    assert not hasattr(RemoteRunnerHttpClient, "list_workflow_trigger_inbox_events")
    assert not hasattr(RemoteRunnerHttpClient, "list_workflow_trigger_scheduler_ticks")
    assert not hasattr(RemoteRunnerHttpClient, "list_workflow_backfill_launches")
    assert not hasattr(RemoteRunnerHttpClient, "get_workflow_backfill_launch")
    assert not hasattr(RemoteRunnerHttpClient, "list_governance_audit_events")
    assert not hasattr(RemoteRunnerHttpClient, "get_secret_provider_readiness")


class FakeEndpointClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path: str) -> dict[str, object]:
        self.calls.append(("GET", path))
        if path == "/api/v1/runs":
            return {"data": {"items": [{"path": path}]}}
        if path == "/api/v1/results":
            return {"data": {"items": [{"path": path}]}}
        if path.startswith("/api/v1/results/res_1/exports"):
            return {"data": {"path": path}}
        if path.startswith("/api/v1/artifacts/"):
            return {"data": {"path": path}}
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
        assert preferred_server_id is None
        return "srv_1", object(), {"server_id": "srv_1"}

    def _require_existing_runner_ready(self, *, preferred_server_id=None):
        assert preferred_server_id in {"srv_package", "srv_artifact", "srv_audit", "srv_secret"}
        return "srv_1", object(), {"server_id": "srv_1"}

    def _call_remote_runner(self, method, **kwargs):
        assert kwargs["server_id"] == "srv_1"
        assert "endpoint_id" in kwargs
        return method(**kwargs)


class FakeRemoteEndpointManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def call_remote_endpoint(self, **kwargs) -> dict[str, object]:
        path_values = dict(kwargs["path_values"])
        query_values = dict(kwargs.get("query_values") or {})
        endpoint_id = str(kwargs["endpoint_id"])
        self.calls.append((endpoint_id, path_values, query_values))
        if endpoint_id in {
            RUN_LIST,
            WORKFLOW_TRIGGER_LIST,
            WORKFLOW_TRIGGER_EVENTS_READ,
            WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
            WORKFLOW_TRIGGER_INBOX_READ,
            WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
            WORKFLOW_BACKFILL_LAUNCH_LIST,
            WORKFLOW_BACKFILL_LAUNCH_READ,
            GOVERNANCE_AUDIT_EVENTS_READ,
            SECRET_PROVIDER_READINESS_READ,
        }:
            assert kwargs["timeout"] == 20
        if endpoint_id == RUN_LIST:
            return [{"runId": "run_1"}]
        if endpoint_id == RESULT_LIST:
            return [{"resultId": "res_1"}]
        return {"endpointId": kwargs["endpoint_id"], "pathValues": path_values, "queryValues": query_values}


def _runner_kwargs(
    endpoint_id: str,
    run_id: str | None = None,
    *,
    query_values: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"server_id": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": {"run_id": run_id} if run_id is not None else {},
        "query_values": dict(query_values or {}),
    }


def _result_kwargs(
    endpoint_id: str,
    result_id: str | None = None,
    *,
    query_values: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"server_id": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": {"result_id": result_id} if result_id is not None else {},
        "query_values": dict(query_values or {}),
    }


def _trigger_kwargs(
    endpoint_id: str,
    trigger_id: str,
    *,
    query_values: dict[str, object] | None = None,
) -> dict[str, object]:
    return _endpoint_kwargs(
        endpoint_id,
        path_values={"trigger_id": trigger_id},
        query_values=query_values,
    )


def _endpoint_kwargs(
    endpoint_id: str,
    *,
    path_values: dict[str, object] | None = None,
    query_values: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "server_id": "srv_1",
        "ssh_service": object(),
        "server_record": {"server_id": "srv_1"},
        "endpoint_id": endpoint_id,
        "path_values": dict(path_values or {}),
        "query_values": dict(query_values or {}),
    }
