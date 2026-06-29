from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Any
from urllib.parse import quote, urlencode


class RemoteEndpointContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class RemoteEndpoint:
    endpoint_id: str
    method: str
    path_template: str
    operation_id: str
    governance_action: str | None
    request_schema: str | None
    response_schema: str
    cache_scope: str
    query_params: tuple[str, ...] = ()
    invalidates: tuple[str, ...] = ()
    response_key: str = "data"
    response_item_key: str | None = None

    @property
    def path_params(self) -> tuple[str, ...]:
        names = [
            str(field_name)
            for _, field_name, _, _ in Formatter().parse(self.path_template)
            if field_name
        ]
        return tuple(dict.fromkeys(names))


RUN_LIST = "run.list"
RUN_READ = "run.read"
RUN_EVENTS_READ = "run.events.read"
RUN_EXECUTION_CONTEXT_READ = "run.execution_context.read"
RUN_ATTEMPTS_READ = "run.attempts.read"
RUN_LOGS_READ = "run.logs.read"
RUN_RESULTS_READ = "run.results.read"
RUN_RULES_READ = "run.rules.read"
RUN_FAILURE_LOCATOR_READ = "run.failure_locator.read"
RESULT_LIST = "result.list"
RESULT_READ = "result.read"
RESULT_PREVIEW_READ = "result.preview.read"
RESULT_AUDIT_READ = "result.audit.read"
RESULT_PACKAGE_EXPORT_LIST = "result.package_export.list"
ARTIFACT_LIFECYCLE_USAGE_READ = "artifact.lifecycle.usage.read"
ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ = "artifact.lifecycle.controller_ticks.read"
ARTIFACT_CACHE_ENTRIES_READ = "artifact.cache.entries.read"
ARTIFACT_CACHE_PINS_READ = "artifact.cache_pins.read"


REMOTE_ENDPOINTS: dict[str, RemoteEndpoint] = {
    RUN_LIST: RemoteEndpoint(
        endpoint_id=RUN_LIST,
        method="GET",
        path_template="/api/v1/runs",
        operation_id="listRuns",
        governance_action=None,
        request_schema=None,
        response_schema="run-list.v1",
        cache_scope="run-read-model",
        response_item_key="items",
    ),
    RUN_READ: RemoteEndpoint(
        endpoint_id=RUN_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}",
        operation_id="getRun",
        governance_action=None,
        request_schema=None,
        response_schema="run.v1",
        cache_scope="run-read-model",
    ),
    RUN_EVENTS_READ: RemoteEndpoint(
        endpoint_id=RUN_EVENTS_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/events",
        operation_id="getRunEvents",
        governance_action="run.events.read",
        request_schema=None,
        response_schema="run-events.v1",
        cache_scope="run-read-model",
    ),
    RUN_EXECUTION_CONTEXT_READ: RemoteEndpoint(
        endpoint_id=RUN_EXECUTION_CONTEXT_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/execution-context",
        operation_id="getRunExecutionContext",
        governance_action="run.execution_context.read",
        request_schema=None,
        response_schema="run-execution-context.v1",
        cache_scope="run-read-model",
    ),
    RUN_ATTEMPTS_READ: RemoteEndpoint(
        endpoint_id=RUN_ATTEMPTS_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/attempts",
        operation_id="getRunAttempts",
        governance_action="run.attempts.read",
        request_schema=None,
        response_schema="run-attempts.v1",
        cache_scope="run-read-model",
    ),
    RUN_LOGS_READ: RemoteEndpoint(
        endpoint_id=RUN_LOGS_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/logs",
        operation_id="getRunLogs",
        governance_action="run.logs.read",
        request_schema=None,
        response_schema="run-logs.v1",
        cache_scope="run-read-model",
        query_params=("stream", "cursor"),
    ),
    RUN_RESULTS_READ: RemoteEndpoint(
        endpoint_id=RUN_RESULTS_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/results",
        operation_id="getRunResults",
        governance_action="run.results.read",
        request_schema=None,
        response_schema="run-results.v1",
        cache_scope="run-read-model",
    ),
    RUN_RULES_READ: RemoteEndpoint(
        endpoint_id=RUN_RULES_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/rules",
        operation_id="getRunRules",
        governance_action="run.rules.read",
        request_schema=None,
        response_schema="run-rules.v1",
        cache_scope="run-read-model",
    ),
    RUN_FAILURE_LOCATOR_READ: RemoteEndpoint(
        endpoint_id=RUN_FAILURE_LOCATOR_READ,
        method="GET",
        path_template="/api/v1/runs/{run_id}/failure-locator",
        operation_id="getRunFailureLocator",
        governance_action="run.failure_locator.read",
        request_schema=None,
        response_schema="run-failure-locator.v1",
        cache_scope="run-read-model",
    ),
    RESULT_LIST: RemoteEndpoint(
        endpoint_id=RESULT_LIST,
        method="GET",
        path_template="/api/v1/results",
        operation_id="listResults",
        governance_action="result.list",
        request_schema=None,
        response_schema="result-list.v1",
        cache_scope="result-read-model",
        response_item_key="items",
    ),
    RESULT_READ: RemoteEndpoint(
        endpoint_id=RESULT_READ,
        method="GET",
        path_template="/api/v1/results/{result_id}",
        operation_id="getResult",
        governance_action="result.read",
        request_schema=None,
        response_schema="result.v1",
        cache_scope="result-read-model",
    ),
    RESULT_PREVIEW_READ: RemoteEndpoint(
        endpoint_id=RESULT_PREVIEW_READ,
        method="GET",
        path_template="/api/v1/results/{result_id}/preview",
        operation_id="getResultPreview",
        governance_action="result.artifact.preview",
        request_schema=None,
        response_schema="result-preview.v1",
        cache_scope="result-read-model",
        query_params=("artifact_id",),
    ),
    RESULT_AUDIT_READ: RemoteEndpoint(
        endpoint_id=RESULT_AUDIT_READ,
        method="GET",
        path_template="/api/v1/results/{result_id}/audit",
        operation_id="getResultAudit",
        governance_action="result.artifact_audit.read",
        request_schema=None,
        response_schema="result-artifact-audit.v1",
        cache_scope="result-read-model",
    ),
    RESULT_PACKAGE_EXPORT_LIST: RemoteEndpoint(
        endpoint_id=RESULT_PACKAGE_EXPORT_LIST,
        method="GET",
        path_template="/api/v1/results/{result_id}/exports",
        operation_id="listResultPackageExports",
        governance_action="result.package.list",
        request_schema=None,
        response_schema="result-package-export-list.v1",
        cache_scope="result-package-export-read-model",
        query_params=("lifecycleState", "limit"),
    ),
    ARTIFACT_LIFECYCLE_USAGE_READ: RemoteEndpoint(
        endpoint_id=ARTIFACT_LIFECYCLE_USAGE_READ,
        method="GET",
        path_template="/api/v1/artifacts/lifecycle/usage",
        operation_id="getArtifactLifecycleUsage",
        governance_action="artifact.lifecycle.usage.read",
        request_schema=None,
        response_schema="h2ometa.artifact-lifecycle-usage.v1",
        cache_scope="artifact-lifecycle-read-model",
        query_params=("quotaBytes",),
    ),
    ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ: RemoteEndpoint(
        endpoint_id=ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ,
        method="GET",
        path_template="/api/v1/artifacts/lifecycle/controller/ticks",
        operation_id="listArtifactLifecycleControllerTicks",
        governance_action="artifact.lifecycle.controller_ticks.read",
        request_schema=None,
        response_schema="h2ometa.artifact-lifecycle-controller-tick-read-model.v1",
        cache_scope="artifact-lifecycle-read-model",
        query_params=("limit",),
    ),
    ARTIFACT_CACHE_ENTRIES_READ: RemoteEndpoint(
        endpoint_id=ARTIFACT_CACHE_ENTRIES_READ,
        method="GET",
        path_template="/api/v1/artifacts/cache/entries",
        operation_id="listArtifactCacheEntries",
        governance_action="artifact.cache.entries.read",
        request_schema=None,
        response_schema="artifact-cache-entries-public.v1",
        cache_scope="artifact-cache-read-model",
        query_params=("workflowRevisionId", "limit"),
    ),
    ARTIFACT_CACHE_PINS_READ: RemoteEndpoint(
        endpoint_id=ARTIFACT_CACHE_PINS_READ,
        method="GET",
        path_template="/api/v1/artifacts/cache/pins",
        operation_id="listArtifactCachePins",
        governance_action="artifact.cache_pins.read",
        request_schema=None,
        response_schema="artifact-cache-pins-public.v1",
        cache_scope="artifact-cache-read-model",
        query_params=("cacheEntryId", "state", "limit"),
    ),
}


def get_remote_endpoint(endpoint_id: str) -> RemoteEndpoint:
    try:
        return REMOTE_ENDPOINTS[endpoint_id]
    except KeyError as exc:
        raise RemoteEndpointContractError("REMOTE_ENDPOINT_UNKNOWN", endpoint_id) from exc


def render_remote_endpoint_path(
    endpoint_id: str,
    values: dict[str, Any],
    *,
    query_values: dict[str, Any] | None = None,
) -> str:
    endpoint = get_remote_endpoint(endpoint_id)
    rendered_values: dict[str, str] = {}
    for name in endpoint.path_params:
        value = str(values.get(name) or "").strip()
        if not value:
            raise RemoteEndpointContractError(
                "REMOTE_ENDPOINT_PATH_PARAM_REQUIRED",
                f"{endpoint_id}.{name}",
            )
        rendered_values[name] = quote(value, safe="")
    path = endpoint.path_template.format(**rendered_values)
    query = _declared_query_values(endpoint, query_values or {})
    if query:
        path = f"{path}?{urlencode(query)}"
    return path


def _declared_query_values(endpoint: RemoteEndpoint, query_values: dict[str, Any]) -> list[tuple[str, str]]:
    unknown = sorted(set(query_values) - set(endpoint.query_params))
    if unknown:
        raise RemoteEndpointContractError(
            "REMOTE_ENDPOINT_QUERY_PARAM_UNKNOWN",
            f"{endpoint.endpoint_id}: {','.join(unknown)}",
        )
    query: list[tuple[str, str]] = []
    for name in endpoint.query_params:
        value = query_values.get(name)
        if value is None or str(value) == "":
            continue
        query.append((name, _query_value(value)))
    return query


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
