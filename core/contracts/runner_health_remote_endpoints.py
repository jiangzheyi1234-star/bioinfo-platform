from __future__ import annotations

from typing import Any


RUNNER_HEALTH_STARTUP = "runner.health.startup"
RUNNER_HEALTH_LIVE = "runner.health.live"
RUNNER_HEALTH_READY = "runner.health.ready"
RUNNER_HEALTH_META = "runner.health.meta"
RUNNER_HEALTH_WORKERS = "runner.health.workers"
RUNNER_HEALTH_EXECUTION_DIAGNOSTICS = "runner.health.execution_diagnostics"

OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINT_IDS = (
    RUNNER_HEALTH_STARTUP,
    RUNNER_HEALTH_LIVE,
    RUNNER_HEALTH_READY,
    RUNNER_HEALTH_META,
    RUNNER_HEALTH_WORKERS,
    RUNNER_HEALTH_EXECUTION_DIAGNOSTICS,
)

RUNNER_HEALTH_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    RUNNER_HEALTH_STARTUP: {
        "method": "GET",
        "path_template": "/health/startup",
        "operation_id": "getRunnerStartupHealth",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "runner-health-startup.v1",
        "cache_scope": "runner-health-read-model",
        "response_key": None,
        "accepted_statuses": (200, 503),
    },
    RUNNER_HEALTH_LIVE: {
        "method": "GET",
        "path_template": "/health/live",
        "operation_id": "getRunnerLiveHealth",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "runner-health-live.v1",
        "cache_scope": "runner-health-read-model",
        "response_key": None,
    },
    RUNNER_HEALTH_READY: {
        "method": "GET",
        "path_template": "/health/ready",
        "operation_id": "getRunnerReadyHealth",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "runner-health-ready.v1",
        "cache_scope": "runner-health-read-model",
        "response_key": None,
        "accepted_statuses": (200, 503),
    },
    RUNNER_HEALTH_META: {
        "method": "GET",
        "path_template": "/health/meta",
        "operation_id": "getRunnerHealthMeta",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "runner-health-meta.v1",
        "cache_scope": "runner-health-read-model",
    },
    RUNNER_HEALTH_WORKERS: {
        "method": "GET",
        "path_template": "/health/workers",
        "operation_id": "getRunnerWorkersHealth",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "runner-health-workers.v1",
        "cache_scope": "runner-health-read-model",
    },
    RUNNER_HEALTH_EXECUTION_DIAGNOSTICS: {
        "method": "GET",
        "path_template": "/health/execution-diagnostics",
        "operation_id": "getRunnerExecutionDiagnostics",
        "governance_action": None,
        "request_schema": None,
        "response_schema": "execution-diagnostics.v1",
        "cache_scope": "runner-execution-diagnostics-read-model",
    },
}
