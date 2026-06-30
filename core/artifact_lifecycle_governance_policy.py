from __future__ import annotations


ARTIFACT_LIFECYCLE_POLICY_GOVERNANCE_SPECS = (
    (
        "GET",
        "/api/v1/artifacts/lifecycle/policy",
        "apps/remote_runner/execution_query_routes.py",
        "artifact.lifecycle.policy.read",
        "artifact_lifecycle_policy",
        "implemented",
        "artifact-curator",
        "auditor",
    ),
    (
        "POST",
        "/api/v1/artifacts/lifecycle/policy",
        "apps/remote_runner/execution_query_routes.py",
        "artifact.lifecycle.policy.set",
        "artifact_lifecycle_policy",
        "implemented",
        "artifact-curator",
        "platform-admin",
    ),
)
