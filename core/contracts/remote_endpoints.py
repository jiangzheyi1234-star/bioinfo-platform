from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Any
from urllib.parse import quote


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
    governance_action: str
    request_schema: str | None
    response_schema: str
    cache_scope: str
    invalidates: tuple[str, ...] = ()
    response_key: str = "data"

    @property
    def path_params(self) -> tuple[str, ...]:
        names = [
            str(field_name)
            for _, field_name, _, _ in Formatter().parse(self.path_template)
            if field_name
        ]
        return tuple(dict.fromkeys(names))


RUN_EXECUTION_CONTEXT_READ = "run.execution_context.read"
RUN_RULES_READ = "run.rules.read"
RUN_FAILURE_LOCATOR_READ = "run.failure_locator.read"


REMOTE_ENDPOINTS: dict[str, RemoteEndpoint] = {
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
}


def get_remote_endpoint(endpoint_id: str) -> RemoteEndpoint:
    try:
        return REMOTE_ENDPOINTS[endpoint_id]
    except KeyError as exc:
        raise RemoteEndpointContractError("REMOTE_ENDPOINT_UNKNOWN", endpoint_id) from exc


def render_remote_endpoint_path(endpoint_id: str, values: dict[str, Any]) -> str:
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
    return endpoint.path_template.format(**rendered_values)
