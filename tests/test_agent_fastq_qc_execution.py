from __future__ import annotations

import copy
import inspect
import re
from typing import Any

import pytest
from pydantic import ValidationError

from core.contracts.agent_contract_hash import agent_contract_hash
from core.contracts.agent_fastq_qc_execution import (
    AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
    AGENT_WORKFLOW_RUN_SPEC_HASH_DOMAIN,
    AgentFastqQcExecutionPolicy,
    agent_fastq_qc_execution_hash,
    agent_workflow_run_spec_hash,
    build_agent_fastq_qc_execution,
)


def _execution_payload() -> dict[str, Any]:
    return {
        "queueName": "default",
        "retryPolicy": {
            "schemaVersion": "execution-retry-policy.v1",
            "maxAttempts": 3,
            "backoffSeconds": 5,
        },
        "timeoutPolicy": {
            "schemaVersion": "execution-timeout-policy.v1",
            "queueTtlSeconds": 0,
            "startToCloseTimeoutSeconds": 0,
            "heartbeatTimeoutSeconds": 60,
        },
    }


def test_fastq_qc_execution_builder_has_no_input_and_returns_exact_policy() -> None:
    assert tuple(inspect.signature(build_agent_fastq_qc_execution).parameters) == ()

    execution = build_agent_fastq_qc_execution()

    assert execution.runtime_payload() == _execution_payload()
    assert execution.timeoutPolicy.queueTtlSeconds == 0
    assert execution.timeoutPolicy.startToCloseTimeoutSeconds == 0
    assert execution.timeoutPolicy.heartbeatTimeoutSeconds == 60


def test_fastq_qc_execution_hash_is_stable_and_domain_separated() -> None:
    execution = build_agent_fastq_qc_execution()
    first = agent_fastq_qc_execution_hash(execution)
    second = agent_fastq_qc_execution_hash(_execution_payload())

    assert first == second
    assert first == "fabfb02455916924207413caa075f5f13f4a13afa9f4a7494fe35eb87b52c7a1"
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert first == agent_contract_hash(
        AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
        _execution_payload(),
    )
    assert first != agent_contract_hash(
        AGENT_WORKFLOW_RUN_SPEC_HASH_DOMAIN,
        _execution_payload(),
    )


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("queueName",), "priority"),
        (("retryPolicy", "schemaVersion"), "execution-retry-policy.v2"),
        (("retryPolicy", "maxAttempts"), 4),
        (("retryPolicy", "backoffSeconds"), 6),
        (("timeoutPolicy", "schemaVersion"), "execution-timeout-policy.v2"),
        (("timeoutPolicy", "queueTtlSeconds"), 1),
        (("timeoutPolicy", "startToCloseTimeoutSeconds"), 1),
        (("timeoutPolicy", "heartbeatTimeoutSeconds"), 61),
    ],
)
def test_fastq_qc_execution_rejects_policy_tampering(
    path: tuple[str, ...],
    replacement: object,
) -> None:
    payload = copy.deepcopy(_execution_payload())
    target: dict[str, Any] = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(ValidationError):
        agent_fastq_qc_execution_hash(payload)


@pytest.mark.parametrize(
    "path",
    [
        ("queueName",),
        ("retryPolicy",),
        ("retryPolicy", "schemaVersion"),
        ("retryPolicy", "maxAttempts"),
        ("retryPolicy", "backoffSeconds"),
        ("timeoutPolicy",),
        ("timeoutPolicy", "schemaVersion"),
        ("timeoutPolicy", "queueTtlSeconds"),
        ("timeoutPolicy", "startToCloseTimeoutSeconds"),
        ("timeoutPolicy", "heartbeatTimeoutSeconds"),
    ],
)
def test_fastq_qc_execution_rejects_missing_fields(path: tuple[str, ...]) -> None:
    payload = copy.deepcopy(_execution_payload())
    target: dict[str, Any] = payload
    for key in path[:-1]:
        target = target[key]
    target.pop(path[-1])

    with pytest.raises(ValidationError):
        AgentFastqQcExecutionPolicy.model_validate(payload)


def test_fastq_qc_execution_hash_revalidates_mutated_model_instances() -> None:
    execution = build_agent_fastq_qc_execution()
    object.__setattr__(execution.timeoutPolicy, "heartbeatTimeoutSeconds", 61)

    with pytest.raises(ValidationError):
        agent_fastq_qc_execution_hash(execution)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("retryPolicy", "maxAttempts"), True),
        (("retryPolicy", "backoffSeconds"), True),
        (("timeoutPolicy", "queueTtlSeconds"), False),
        (("timeoutPolicy", "startToCloseTimeoutSeconds"), False),
        (("timeoutPolicy", "heartbeatTimeoutSeconds"), True),
        (("retryPolicy", "maxAttempts"), "3"),
        (("timeoutPolicy", "queueTtlSeconds"), "0"),
    ],
)
def test_fastq_qc_execution_rejects_bool_as_int_and_coercion(
    path: tuple[str, ...],
    replacement: object,
) -> None:
    payload = copy.deepcopy(_execution_payload())
    target: dict[str, Any] = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(ValidationError):
        AgentFastqQcExecutionPolicy.model_validate(payload)


@pytest.mark.parametrize("path", [(), ("retryPolicy",), ("timeoutPolicy",)])
def test_fastq_qc_execution_rejects_extra_fields(path: tuple[str, ...]) -> None:
    payload = copy.deepcopy(_execution_payload())
    target: dict[str, Any] = payload
    for key in path:
        target = target[key]
    target["callerOverride"] = False

    with pytest.raises(ValidationError) as exc_info:
        AgentFastqQcExecutionPolicy.model_validate(payload)

    assert any(error["type"] == "extra_forbidden" for error in exc_info.value.errors())


def test_agent_workflow_run_spec_hash_preserves_zero_false_and_empty_values() -> None:
    exact = {
        "pipelineId": "generated-tool-run-v1",
        "disabled": False,
        "zero": 0,
        "emptyText": "",
        "emptyList": [],
        "emptyObject": {},
        "null": None,
    }
    exact_hash = agent_workflow_run_spec_hash(exact)

    assert exact_hash == agent_contract_hash(
        AGENT_WORKFLOW_RUN_SPEC_HASH_DOMAIN,
        exact,
    )
    for field in ("disabled", "zero", "emptyText", "emptyList", "emptyObject", "null"):
        changed = dict(exact)
        changed.pop(field)
        assert agent_workflow_run_spec_hash(changed) != exact_hash


def test_agent_workflow_run_spec_hash_rejects_non_mapping_and_unsafe_json() -> None:
    with pytest.raises(ValueError, match="AGENT_WORKFLOW_RUN_SPEC_REQUIRED"):
        agent_workflow_run_spec_hash([])  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="JSON_INTEGER_OUT_OF_SAFE_RANGE"):
        agent_workflow_run_spec_hash({"unsafe": 9_007_199_254_740_993})
