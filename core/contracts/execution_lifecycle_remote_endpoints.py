from __future__ import annotations

from typing import Any


EXECUTION_LIFECYCLE_GUARD = "execution.lifecycle_guard"
EXECUTION_LIFECYCLE_GUARD_RELEASE = "execution.lifecycle_guard.release"


EXECUTION_LIFECYCLE_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    EXECUTION_LIFECYCLE_GUARD: {
        "method": "POST",
        "path_template": "/api/v1/execution/lifecycle-guard",
        "operation_id": "requestExecutionLifecycleGuard",
        "governance_action": "execution.lifecycle_guard",
        "request_schema": "execution-lifecycle-guard-request.v1",
        "response_schema": "execution-lifecycle-guard.v1",
        "cache_scope": "execution-lifecycle-command",
        "invalidates": ("run-read-model",),
    },
    EXECUTION_LIFECYCLE_GUARD_RELEASE: {
        "method": "POST",
        "path_template": "/api/v1/execution/lifecycle-guard/release",
        "operation_id": "releaseExecutionLifecycleGuard",
        "governance_action": "execution.lifecycle_guard.release",
        "request_schema": "execution-lifecycle-guard-release-request.v1",
        "response_schema": "execution-lifecycle-guard-release.v1",
        "cache_scope": "execution-lifecycle-command",
        "invalidates": ("run-read-model",),
    },
}
