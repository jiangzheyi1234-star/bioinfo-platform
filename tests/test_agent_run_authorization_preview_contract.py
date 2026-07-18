from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from pydantic import ValidationError

from core.contracts.agent_fastq_qc_execution import (
    AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
    agent_fastq_qc_execution_hash,
    build_agent_fastq_qc_execution,
)
from core.contracts.agent_run_authorization_preview import (
    AgentRunAuthorizationPreview,
    agent_run_authorization_preview_hash,
)


def _tool(
    step_id: str,
    profile_id: str,
    *,
    profile_version: int,
) -> dict[str, Any]:
    version = "0.12.1" if profile_id == "fastqc" else "1.34"
    wrapper = f"v9.8.0/bio/{profile_id}"
    return {
        "stepId": step_id,
        "capabilityId": f"agent-capability-bundle.v1:h2ometa-metagenomics-core:{profile_id}",
        "toolId": f"bioconda::{profile_id}",
        "toolRevisionId": f"toolrev_{profile_id}_1",
        "name": profile_id,
        "source": "bioconda",
        "version": version,
        "packageSpec": f"bioconda::{profile_id}={version}",
        "targetPlatform": "linux-64",
        "profileId": profile_id,
        "profileVersion": profile_version,
        "wrapperIdentifier": wrapper,
        "ruleTemplateSha256": ("1" if profile_id == "fastqc" else "2") * 64,
    }


def _runtime() -> dict[str, Any]:
    return {
        "platform": "linux-64",
        "runnerProtocol": {
            "version": "2026-07-18",
            "fingerprint": "sha256:" + "3" * 64,
        },
        "workflowRuntime": {
            "provider": "conda-pack",
            "source": "artifact",
            "version": "2026.7.18",
            "snakemakePackageVersion": "9.8.0",
            "pythonSha256": "4" * 64,
            "declaredArtifactArchiveSha256": "sha256:" + "5" * 64,
        },
        "snakemake": {
            "reportedVersion": "9.8.0",
            "sha256": "6" * 64,
        },
        "managedConda": {"sha256": "7" * 64},
        "workflowProfile": {
            "name": "default",
            "fileSha256": "8" * 64,
        },
        "release": {
            "treeHash": "9" * 64,
            "wrapperMirrorTreeHash": "a" * 64,
        },
    }


def _resources() -> dict[str, Any]:
    return {
        "bindings": {},
        "orderedSteps": [
            {
                "stepId": "fastqc",
                "threads": 1,
                "resources": {
                    "enabled": False,
                    "label": "",
                    "mem_mb": 0,
                },
                "schedulerResources": {},
            },
            {
                "stepId": "multiqc",
                "threads": 1,
                "resources": {},
                "schedulerResources": {"mem_mb": 128},
            },
        ],
    }


def _execution_policy() -> dict[str, Any]:
    return build_agent_fastq_qc_execution().runtime_payload()


def _preview_payload() -> dict[str, Any]:
    execution_policy = _execution_policy()
    payload: dict[str, Any] = {
        "contractVersion": "agent-run-authorization-preview.v1",
        "sessionId": "ags_preview_1",
        "stateVersion": 5,
        "adapterId": "h2ometa.fastq-qc.v1",
        "adapterVersion": "1.0.0",
        "plannerModel": "deterministic:capability-bundle-v1",
        "planRevisionId": "agpr_preview_1",
        "planGeneration": 1,
        "planHash": "b" * 64,
        "workflowRevisionId": "wfrev_preview_1",
        "workflowRevisionContentHash": "c" * 64,
        "inputManifestDigest": "sha256:" + "d" * 64,
        "runSpecHash": "e" * 64,
        "executionPolicyId": AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
        "executionPolicyHash": agent_fastq_qc_execution_hash(execution_policy),
        "executionPolicy": execution_policy,
        "runtimeLockHash": "0" * 64,
        "runtimeProofHash": "1" * 64,
        "effectBudgetHash": "2" * 64,
        "maxRunSubmissions": 1,
        "usedRunSubmissions": 0,
        "remainingRunSubmissions": 1,
        "tools": [
            _tool("fastqc", "fastqc", profile_version=2),
            _tool("multiqc", "multiqc", profile_version=3),
        ],
        "runtime": _runtime(),
        "resources": _resources(),
        "consequenceCode": "create-and-enqueue-one-workflow-run",
    }
    payload["previewHash"] = agent_run_authorization_preview_hash(payload)
    return payload


def _rehash(payload: dict[str, Any]) -> dict[str, Any]:
    payload["previewHash"] = agent_run_authorization_preview_hash(payload)
    return payload


def test_preview_has_exact_runtime_payload_and_revalidates_hash() -> None:
    payload = _preview_payload()
    preview = AgentRunAuthorizationPreview.model_validate(payload)

    assert preview.runtime_payload() == payload
    assert re.fullmatch(r"[0-9a-f]{64}", preview.previewHash)
    assert preview.resources.orderedSteps[0].resources == {
        "enabled": False,
        "label": "",
        "mem_mb": 0,
    }
    assert preview.resources.bindings == {}
    assert agent_run_authorization_preview_hash(preview) == preview.previewHash


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("contractVersion", "agent-run-authorization-preview.v2"),
        ("sessionId", "ags_preview_2"),
        ("stateVersion", 6),
        ("adapterId", "h2ometa.fastq-qc.v2"),
        ("adapterVersion", "2.0.0"),
        ("plannerModel", "deterministic:capability-bundle-v2"),
        ("planRevisionId", "agpr_preview_2"),
        ("planGeneration", 2),
        ("planHash", "3" * 64),
        ("workflowRevisionId", "wfrev_preview_2"),
        ("workflowRevisionContentHash", "4" * 64),
        ("inputManifestDigest", "sha256:" + "5" * 64),
        ("runSpecHash", "6" * 64),
        ("executionPolicyId", "agent-fastq-qc-execution.v2"),
        ("executionPolicyHash", "7" * 64),
        ("runtimeLockHash", "8" * 64),
        ("runtimeProofHash", "9" * 64),
        ("effectBudgetHash", "a" * 64),
        ("maxRunSubmissions", 2),
        ("usedRunSubmissions", 1),
        ("remainingRunSubmissions", 0),
        ("consequenceCode", "create-only"),
    ],
)
def test_preview_hash_binds_every_scalar_field(field: str, replacement: object) -> None:
    original = _preview_payload()
    changed = copy.deepcopy(original)
    changed[field] = replacement

    assert agent_run_authorization_preview_hash(changed) != original["previewHash"]


def test_preview_hash_binds_nested_summaries_and_array_order() -> None:
    original = _preview_payload()

    tool_changed = copy.deepcopy(original)
    tool_changed["tools"][0]["capabilityId"] = "capability-changed"
    assert agent_run_authorization_preview_hash(tool_changed) != original["previewHash"]

    runtime_changed = copy.deepcopy(original)
    runtime_changed["runtime"]["workflowProfile"]["name"] = "changed"
    assert (
        agent_run_authorization_preview_hash(runtime_changed) != original["previewHash"]
    )

    execution_changed = copy.deepcopy(original)
    execution_changed["executionPolicy"]["timeoutPolicy"]["heartbeatTimeoutSeconds"] = (
        61
    )
    assert (
        agent_run_authorization_preview_hash(execution_changed)
        != original["previewHash"]
    )

    resources_changed = copy.deepcopy(original)
    resources_changed["resources"]["bindings"] = {"taxonomy": {"databaseId": "db_1"}}
    assert (
        agent_run_authorization_preview_hash(resources_changed)
        != original["previewHash"]
    )

    reordered = copy.deepcopy(original)
    reordered["tools"].reverse()
    reordered["resources"]["orderedSteps"].reverse()
    assert agent_run_authorization_preview_hash(reordered) != original["previewHash"]


def test_preview_hash_canonicalizes_object_order_but_preserves_zero_false_and_empty() -> (
    None
):
    original = _preview_payload()
    reordered_map = copy.deepcopy(original)
    resource_map = reordered_map["resources"]["orderedSteps"][0]["resources"]
    reordered_map["resources"]["orderedSteps"][0]["resources"] = {
        key: resource_map[key] for key in reversed(tuple(resource_map))
    }
    assert (
        agent_run_authorization_preview_hash(reordered_map) == original["previewHash"]
    )

    without_empty = copy.deepcopy(original)
    without_empty["resources"]["orderedSteps"][0]["resources"].pop("label")
    assert (
        agent_run_authorization_preview_hash(without_empty) != original["previewHash"]
    )

    zero_changed = copy.deepcopy(original)
    zero_changed["resources"]["orderedSteps"][0]["resources"]["mem_mb"] = 1
    assert agent_run_authorization_preview_hash(zero_changed) != original["previewHash"]

    false_changed = copy.deepcopy(original)
    false_changed["resources"]["orderedSteps"][0]["resources"]["enabled"] = 0
    assert (
        agent_run_authorization_preview_hash(false_changed) != original["previewHash"]
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("sessionId", "ags_preview_changed"),
        ("stateVersion", 6),
        ("planHash", "3" * 64),
        ("workflowRevisionContentHash", "4" * 64),
        ("runSpecHash", "5" * 64),
        ("runtimeProofHash", "6" * 64),
    ],
)
def test_preview_model_rejects_stale_hash_after_valid_tamper(
    field: str,
    replacement: object,
) -> None:
    payload = _preview_payload()
    payload[field] = replacement

    with pytest.raises(
        ValidationError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_HASH_MISMATCH",
    ):
        AgentRunAuthorizationPreview.model_validate(payload)


def test_preview_model_rejects_nested_tamper_with_stale_hash() -> None:
    payload = _preview_payload()
    payload["tools"][0]["ruleTemplateSha256"] = "3" * 64
    with pytest.raises(ValidationError, match="PREVIEW_HASH_MISMATCH"):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload = _preview_payload()
    payload["runtime"]["release"]["treeHash"] = "4" * 64
    with pytest.raises(ValidationError, match="PREVIEW_HASH_MISMATCH"):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload = _preview_payload()
    payload["executionPolicy"]["retryPolicy"]["maxAttempts"] = 4
    with pytest.raises(ValidationError):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload = _preview_payload()
    payload["resources"]["orderedSteps"][0]["resources"]["mem_mb"] = 1
    with pytest.raises(ValidationError, match="PREVIEW_HASH_MISMATCH"):
        AgentRunAuthorizationPreview.model_validate(payload)


def test_preview_rejects_execution_policy_identity_or_hash_drift() -> None:
    payload = _preview_payload()
    payload["executionPolicyId"] = "agent-fastq-qc-execution.v2"
    _rehash(payload)
    with pytest.raises(ValidationError, match="EXECUTION_POLICY_ID_MISMATCH"):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload = _preview_payload()
    payload["executionPolicyHash"] = "f" * 64
    _rehash(payload)
    with pytest.raises(ValidationError, match="EXECUTION_POLICY_HASH_MISMATCH"):
        AgentRunAuthorizationPreview.model_validate(payload)


def test_preview_hash_rejects_missing_and_unexpected_fields() -> None:
    payload = _preview_payload()
    payload.pop("workflowRevisionContentHash")
    with pytest.raises(
        ValueError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_HASH_FIELD_MISSING",
    ):
        agent_run_authorization_preview_hash(payload)

    payload = _preview_payload()
    payload["createdAt"] = "2026-07-18T00:00:00Z"
    with pytest.raises(
        ValueError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_HASH_FIELD_UNEXPECTED: createdAt",
    ):
        agent_run_authorization_preview_hash(payload)


def test_preview_model_rejects_top_level_nested_and_path_extras() -> None:
    payload = _preview_payload()
    payload["createdAt"] = "2026-07-18T00:00:00Z"
    with pytest.raises(ValidationError) as top_level:
        AgentRunAuthorizationPreview.model_validate(payload)
    assert any(error["type"] == "extra_forbidden" for error in top_level.value.errors())

    payload = _preview_payload()
    payload["tools"][0]["unknown"] = "value"
    with pytest.raises(ValidationError) as nested:
        AgentRunAuthorizationPreview.model_validate(payload)
    assert any(error["type"] == "extra_forbidden" for error in nested.value.errors())

    for section, field in (
        ("workflowRuntime", "root"),
        ("workflowProfile", "directory"),
    ):
        payload = _preview_payload()
        payload["runtime"][section][field] = "/private/runtime/path"
        with pytest.raises(ValidationError) as path_extra:
            AgentRunAuthorizationPreview.model_validate(payload)
        assert any(
            error["type"] == "extra_forbidden" for error in path_extra.value.errors()
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("stateVersion",), True),
        (("planGeneration",), True),
        (("maxRunSubmissions",), True),
        (("tools", 0, "profileVersion"), True),
        (("resources", "orderedSteps", 0, "threads"), True),
    ],
)
def test_preview_rejects_bool_as_integer(
    path: tuple[object, ...], value: object
) -> None:
    payload = _preview_payload()
    target: Any = payload
    for item in path[:-1]:
        target = target[item]
    target[path[-1]] = value

    with pytest.raises(ValidationError):
        AgentRunAuthorizationPreview.model_validate(payload)


def test_preview_rejects_unsafe_integer_at_top_level_and_in_resource_map() -> None:
    unsafe = 9_007_199_254_740_993
    payload = _preview_payload()
    payload["stateVersion"] = unsafe
    with pytest.raises(ValidationError, match="JSON_INTEGER_OUT_OF_SAFE_RANGE"):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload = _preview_payload()
    payload["resources"]["orderedSteps"][0]["resources"]["mem_mb"] = unsafe
    with pytest.raises(ValidationError, match="JSON_INTEGER_OUT_OF_SAFE_RANGE"):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload.pop("previewHash")
    with pytest.raises(ValueError, match="JSON_INTEGER_OUT_OF_SAFE_RANGE"):
        agent_run_authorization_preview_hash(payload)


def test_preview_rejects_secret_like_values_and_dynamic_keys() -> None:
    payload = _preview_payload()
    payload["plannerModel"] = "sk-abcdefghijklmnopqrstuvwxyz"
    with pytest.raises(
        ValidationError,
        match="AGENT_SESSION_SECRET_LIKE_VALUE_FORBIDDEN",
    ):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload = _preview_payload()
    payload["resources"]["orderedSteps"][0]["resources"]["apiKey"] = "redacted"
    with pytest.raises(
        ValidationError,
        match="AGENT_SESSION_SECRET_LIKE_KEY_FORBIDDEN",
    ):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload.pop("previewHash")
    with pytest.raises(ValueError, match="AGENT_SESSION_SECRET_LIKE_KEY_FORBIDDEN"):
        agent_run_authorization_preview_hash(payload)


def test_preview_rejects_inconsistent_budget_and_step_order() -> None:
    payload = _preview_payload()
    payload["remainingRunSubmissions"] = 0
    _rehash(payload)
    with pytest.raises(ValidationError, match="EFFECT_BUDGET_INCONSISTENT"):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload = _preview_payload()
    payload["resources"]["orderedSteps"].reverse()
    _rehash(payload)
    with pytest.raises(ValidationError, match="STEP_ORDER_MISMATCH"):
        AgentRunAuthorizationPreview.model_validate(payload)

    payload = _preview_payload()
    payload["tools"][1]["stepId"] = "fastqc"
    payload["resources"]["orderedSteps"][1]["stepId"] = "fastqc"
    _rehash(payload)
    with pytest.raises(ValidationError, match="TOOL_STEP_DUPLICATE"):
        AgentRunAuthorizationPreview.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("contractVersion", "agent-run-authorization-preview.v2"),
        ("consequenceCode", "enqueue-many-workflow-runs"),
        ("inputManifestDigest", "d" * 64),
        ("runtimeLockHash", "sha256:" + "0" * 64),
        ("previewHash", "sha256:" + "0" * 64),
    ],
)
def test_preview_rejects_fixed_or_malformed_fields(
    field: str,
    replacement: object,
) -> None:
    payload = _preview_payload()
    payload[field] = replacement
    with pytest.raises(ValidationError):
        AgentRunAuthorizationPreview.model_validate(payload)
