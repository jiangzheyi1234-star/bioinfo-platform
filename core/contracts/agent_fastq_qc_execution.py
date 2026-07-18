"""Exact server-owned execution policy for deterministic FASTQ QC runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import field_validator

from .agent_contract_hash import agent_contract_hash
from .agent_session import AgentSessionModel


AGENT_FASTQ_QC_EXECUTION_POLICY_ID = "agent-fastq-qc-execution.v1"
AGENT_WORKFLOW_RUN_SPEC_HASH_DOMAIN = "agent-workflow-run-spec.v1"


class AgentFastqQcRetryPolicy(AgentSessionModel):
    schemaVersion: Literal["execution-retry-policy.v1"]
    maxAttempts: Literal[3]
    backoffSeconds: Literal[5]

    @field_validator("maxAttempts", mode="before")
    @classmethod
    def validate_max_attempts(cls, value: object) -> int:
        return _exact_int(value, expected=3, code="AGENT_FASTQ_QC_MAX_ATTEMPTS_INVALID")

    @field_validator("backoffSeconds", mode="before")
    @classmethod
    def validate_backoff_seconds(cls, value: object) -> int:
        return _exact_int(value, expected=5, code="AGENT_FASTQ_QC_BACKOFF_SECONDS_INVALID")


class AgentFastqQcTimeoutPolicy(AgentSessionModel):
    schemaVersion: Literal["execution-timeout-policy.v1"]
    queueTtlSeconds: Literal[0]
    startToCloseTimeoutSeconds: Literal[0]
    heartbeatTimeoutSeconds: Literal[60]

    @field_validator(
        "queueTtlSeconds",
        "startToCloseTimeoutSeconds",
        mode="before",
    )
    @classmethod
    def validate_disabled_deadline(cls, value: object) -> int:
        return _exact_int(value, expected=0, code="AGENT_FASTQ_QC_DISABLED_TIMEOUT_INVALID")

    @field_validator("heartbeatTimeoutSeconds", mode="before")
    @classmethod
    def validate_heartbeat_timeout(cls, value: object) -> int:
        return _exact_int(value, expected=60, code="AGENT_FASTQ_QC_HEARTBEAT_TIMEOUT_INVALID")


class AgentFastqQcExecutionPolicy(AgentSessionModel):
    queueName: Literal["default"]
    retryPolicy: AgentFastqQcRetryPolicy
    timeoutPolicy: AgentFastqQcTimeoutPolicy


def build_agent_fastq_qc_execution() -> AgentFastqQcExecutionPolicy:
    """Build the only execution policy authorized for the v1 FASTQ QC adapter."""

    return AgentFastqQcExecutionPolicy.model_validate(
        {
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
    )


def agent_fastq_qc_execution_hash(
    execution: AgentFastqQcExecutionPolicy | Mapping[str, object],
) -> str:
    """Hash a strictly validated v1 FASTQ QC execution policy."""

    normalized = AgentFastqQcExecutionPolicy.model_validate(
        execution.runtime_payload()
        if isinstance(execution, AgentFastqQcExecutionPolicy)
        else execution
    )
    return agent_contract_hash(
        AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
        normalized.runtime_payload(),
    )


def agent_workflow_run_spec_hash(run_spec: Mapping[str, object]) -> str:
    """Hash the exact effective Agent runSpec without dropping JSON values."""

    if not isinstance(run_spec, Mapping):
        raise ValueError("AGENT_WORKFLOW_RUN_SPEC_REQUIRED")
    return agent_contract_hash(
        AGENT_WORKFLOW_RUN_SPEC_HASH_DOMAIN,
        dict(run_spec),
    )


def _exact_int(value: object, *, expected: int, code: str) -> int:
    if type(value) is not int or value != expected:
        raise ValueError(code)
    return value


__all__ = [
    "AGENT_FASTQ_QC_EXECUTION_POLICY_ID",
    "AGENT_WORKFLOW_RUN_SPEC_HASH_DOMAIN",
    "AgentFastqQcExecutionPolicy",
    "AgentFastqQcRetryPolicy",
    "AgentFastqQcTimeoutPolicy",
    "agent_fastq_qc_execution_hash",
    "agent_workflow_run_spec_hash",
    "build_agent_fastq_qc_execution",
]
