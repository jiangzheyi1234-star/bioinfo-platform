from __future__ import annotations

from typing import Any


ARTIFACT_LIFECYCLE_POLICY_READ = "artifact.lifecycle.policy.read"
ARTIFACT_LIFECYCLE_POLICY_SET = "artifact.lifecycle.policy.set"


ARTIFACT_LIFECYCLE_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    ARTIFACT_LIFECYCLE_POLICY_READ: {
        "method": "GET",
        "path_template": "/api/v1/artifacts/lifecycle/policy",
        "operation_id": "getArtifactLifecyclePolicy",
        "governance_action": "artifact.lifecycle.policy.read",
        "request_schema": None,
        "response_schema": "h2ometa.artifact-lifecycle-policy.v1",
        "cache_scope": "artifact-lifecycle-policy-read-model",
    },
    ARTIFACT_LIFECYCLE_POLICY_SET: {
        "method": "POST",
        "path_template": "/api/v1/artifacts/lifecycle/policy",
        "operation_id": "setArtifactLifecyclePolicy",
        "governance_action": "artifact.lifecycle.policy.set",
        "request_schema": "artifact-lifecycle-policy-set-request.v1",
        "response_schema": "h2ometa.artifact-lifecycle-policy.v1",
        "cache_scope": "artifact-lifecycle-policy-command",
        "invalidates": ("artifact-lifecycle-policy-read-model", "artifact-lifecycle-read-model"),
    },
}
