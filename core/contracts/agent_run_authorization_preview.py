"""Strict server-owned preview for one Agent-authorized workflow run."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .agent_contract_hash import agent_contract_hash, exact_hash_payload
from .agent_fastq_qc_execution import (
    AGENT_FASTQ_QC_EXECUTION_POLICY_ID,
    AgentFastqQcExecutionPolicy,
    agent_fastq_qc_execution_hash,
)
from .agent_session import AgentSessionModel, assert_agent_session_json_safe


AGENT_RUN_AUTHORIZATION_PREVIEW_CONTRACT_VERSION = "agent-run-authorization-preview.v1"

_PREVIEW_HASH_DOMAIN = AGENT_RUN_AUTHORIZATION_PREVIEW_CONTRACT_VERSION
_HEX_SHA256 = r"^[0-9a-f]{64}$"
_DIGEST_SHA256 = r"^sha256:[0-9a-f]{64}$"
_PREVIEW_HASH_FIELDS = (
    "contractVersion",
    "sessionId",
    "stateVersion",
    "adapterId",
    "adapterVersion",
    "plannerModel",
    "planRevisionId",
    "planGeneration",
    "planHash",
    "workflowRevisionId",
    "workflowRevisionContentHash",
    "inputManifestDigest",
    "runSpecHash",
    "executionPolicyId",
    "executionPolicyHash",
    "executionPolicy",
    "runtimeLockHash",
    "runtimeProofHash",
    "effectBudgetHash",
    "maxRunSubmissions",
    "usedRunSubmissions",
    "remainingRunSubmissions",
    "tools",
    "runtime",
    "resources",
    "consequenceCode",
)

AgentRunAuthorizationResourceScalar = str | int | float | bool


class AgentRunAuthorizationToolSummary(AgentSessionModel):
    stepId: str = Field(min_length=1, max_length=500)
    capabilityId: str = Field(min_length=1, max_length=1_000)
    toolId: str = Field(min_length=1, max_length=500)
    toolRevisionId: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=500)
    source: Literal["bioconda"]
    version: str = Field(min_length=1, max_length=200)
    packageSpec: str = Field(min_length=1, max_length=1_000)
    targetPlatform: Literal["linux-64"]
    profileId: str = Field(min_length=1, max_length=500)
    profileVersion: int = Field(ge=1)
    wrapperIdentifier: str = Field(min_length=1, max_length=1_000)
    ruleTemplateSha256: str = Field(pattern=_HEX_SHA256)

    @field_validator(
        "stepId",
        "capabilityId",
        "toolId",
        "toolRevisionId",
        "name",
        "version",
        "packageSpec",
        "profileId",
        "wrapperIdentifier",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(
            value, "AGENT_RUN_AUTHORIZATION_TOOL_SUMMARY_TEXT_REQUIRED"
        )


class AgentRunAuthorizationRunnerProtocolSummary(AgentSessionModel):
    version: str = Field(min_length=1, max_length=200)
    fingerprint: str = Field(pattern=_DIGEST_SHA256)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUN_AUTHORIZATION_RUNTIME_VERSION_REQUIRED")


class AgentRunAuthorizationWorkflowRuntimeSummary(AgentSessionModel):
    provider: Literal["conda-pack"]
    source: Literal["artifact"]
    version: str = Field(min_length=1, max_length=200)
    snakemakePackageVersion: str = Field(min_length=1, max_length=200)
    pythonSha256: str = Field(pattern=_HEX_SHA256)
    declaredArtifactArchiveSha256: str = Field(pattern=_DIGEST_SHA256)

    @field_validator("version", "snakemakePackageVersion")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUN_AUTHORIZATION_RUNTIME_VERSION_REQUIRED")


class AgentRunAuthorizationSnakemakeSummary(AgentSessionModel):
    reportedVersion: str = Field(min_length=1, max_length=200)
    sha256: str = Field(pattern=_HEX_SHA256)

    @field_validator("reportedVersion")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _required_text(
            value, "AGENT_RUN_AUTHORIZATION_SNAKEMAKE_VERSION_REQUIRED"
        )


class AgentRunAuthorizationManagedCondaSummary(AgentSessionModel):
    sha256: str = Field(pattern=_HEX_SHA256)


class AgentRunAuthorizationWorkflowProfileSummary(AgentSessionModel):
    name: str = Field(min_length=1, max_length=255)
    fileSha256: str = Field(pattern=_HEX_SHA256)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUN_AUTHORIZATION_PROFILE_NAME_REQUIRED")


class AgentRunAuthorizationReleaseSummary(AgentSessionModel):
    treeHash: str = Field(pattern=_HEX_SHA256)
    wrapperMirrorTreeHash: str = Field(pattern=_HEX_SHA256)


class AgentRunAuthorizationRuntimeSummary(AgentSessionModel):
    platform: Literal["linux-64"]
    runnerProtocol: AgentRunAuthorizationRunnerProtocolSummary
    workflowRuntime: AgentRunAuthorizationWorkflowRuntimeSummary
    snakemake: AgentRunAuthorizationSnakemakeSummary
    managedConda: AgentRunAuthorizationManagedCondaSummary
    workflowProfile: AgentRunAuthorizationWorkflowProfileSummary
    release: AgentRunAuthorizationReleaseSummary


class AgentRunAuthorizationResourceStepSummary(AgentSessionModel):
    stepId: str = Field(min_length=1, max_length=500)
    threads: int = Field(ge=1)
    resources: dict[str, AgentRunAuthorizationResourceScalar]
    schedulerResources: dict[str, AgentRunAuthorizationResourceScalar]

    @field_validator("stepId")
    @classmethod
    def validate_step_id(cls, value: str) -> str:
        return _required_text(
            value, "AGENT_RUN_AUTHORIZATION_RESOURCE_STEP_ID_REQUIRED"
        )

    @field_validator("resources", "schedulerResources")
    @classmethod
    def validate_resource_map(
        cls,
        value: dict[str, AgentRunAuthorizationResourceScalar],
    ) -> dict[str, AgentRunAuthorizationResourceScalar]:
        for key in value:
            _required_text(key, "AGENT_RUN_AUTHORIZATION_RESOURCE_KEY_REQUIRED")
        return value


class AgentRunAuthorizationResourceSummary(AgentSessionModel):
    bindings: dict[str, dict[str, str]]
    orderedSteps: list[AgentRunAuthorizationResourceStepSummary] = Field(
        min_length=1,
        max_length=1_000,
    )

    @field_validator("bindings")
    @classmethod
    def validate_bindings(
        cls,
        value: dict[str, dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        for binding_name, binding in value.items():
            _required_text(
                binding_name,
                "AGENT_RUN_AUTHORIZATION_RESOURCE_BINDING_KEY_REQUIRED",
            )
            for key, nested in binding.items():
                _required_text(
                    key,
                    "AGENT_RUN_AUTHORIZATION_RESOURCE_BINDING_KEY_REQUIRED",
                )
                _required_text(
                    nested,
                    "AGENT_RUN_AUTHORIZATION_RESOURCE_BINDING_VALUE_REQUIRED",
                )
        return value


class AgentRunAuthorizationPreview(AgentSessionModel):
    contractVersion: Literal["agent-run-authorization-preview.v1"]
    sessionId: str = Field(min_length=1, max_length=500)
    stateVersion: int = Field(ge=1)
    adapterId: str = Field(min_length=1, max_length=200)
    adapterVersion: str = Field(min_length=1, max_length=200)
    plannerModel: str = Field(min_length=1, max_length=500)
    planRevisionId: str = Field(min_length=1, max_length=500)
    planGeneration: int = Field(ge=1)
    planHash: str = Field(pattern=_HEX_SHA256)
    workflowRevisionId: str = Field(min_length=1, max_length=500)
    workflowRevisionContentHash: str = Field(pattern=_HEX_SHA256)
    inputManifestDigest: str = Field(pattern=_DIGEST_SHA256)
    runSpecHash: str = Field(pattern=_HEX_SHA256)
    executionPolicyId: str = Field(min_length=1, max_length=500)
    executionPolicyHash: str = Field(pattern=_HEX_SHA256)
    executionPolicy: AgentFastqQcExecutionPolicy
    runtimeLockHash: str = Field(pattern=_HEX_SHA256)
    runtimeProofHash: str = Field(pattern=_HEX_SHA256)
    effectBudgetHash: str = Field(pattern=_HEX_SHA256)
    maxRunSubmissions: int = Field(ge=1, le=1)
    usedRunSubmissions: int = Field(ge=0)
    remainingRunSubmissions: int = Field(ge=0)
    tools: list[AgentRunAuthorizationToolSummary] = Field(
        min_length=1,
        max_length=1_000,
    )
    runtime: AgentRunAuthorizationRuntimeSummary
    resources: AgentRunAuthorizationResourceSummary
    consequenceCode: Literal["create-and-enqueue-one-workflow-run"]
    previewHash: str = Field(pattern=_HEX_SHA256)

    @field_validator(
        "sessionId",
        "adapterId",
        "adapterVersion",
        "plannerModel",
        "planRevisionId",
        "workflowRevisionId",
        "executionPolicyId",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUN_AUTHORIZATION_PREVIEW_TEXT_REQUIRED")

    @model_validator(mode="after")
    def validate_projection(self) -> "AgentRunAuthorizationPreview":
        if self.executionPolicyId != AGENT_FASTQ_QC_EXECUTION_POLICY_ID:
            raise ValueError(
                "AGENT_RUN_AUTHORIZATION_PREVIEW_EXECUTION_POLICY_ID_MISMATCH"
            )
        if not hmac.compare_digest(
            agent_fastq_qc_execution_hash(self.executionPolicy),
            self.executionPolicyHash,
        ):
            raise ValueError(
                "AGENT_RUN_AUTHORIZATION_PREVIEW_EXECUTION_POLICY_HASH_MISMATCH"
            )
        if (
            self.usedRunSubmissions + self.remainingRunSubmissions
            != self.maxRunSubmissions
        ):
            raise ValueError(
                "AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_INCONSISTENT"
            )
        tool_step_ids = [item.stepId for item in self.tools]
        if len(set(tool_step_ids)) != len(tool_step_ids):
            raise ValueError("AGENT_RUN_AUTHORIZATION_PREVIEW_TOOL_STEP_DUPLICATE")
        resource_step_ids = [item.stepId for item in self.resources.orderedSteps]
        if resource_step_ids != tool_step_ids:
            raise ValueError("AGENT_RUN_AUTHORIZATION_PREVIEW_STEP_ORDER_MISMATCH")

        payload = self.runtime_payload()
        assert_agent_session_json_safe(payload, path="runAuthorization.preview")
        expected_hash = agent_run_authorization_preview_hash(payload)
        if not hmac.compare_digest(expected_hash, self.previewHash):
            raise ValueError("AGENT_RUN_AUTHORIZATION_PREVIEW_HASH_MISMATCH")
        return self


def agent_run_authorization_preview_hash(
    payload: AgentRunAuthorizationPreview | Mapping[str, object],
) -> str:
    """Hash every exact authorization field while excluding only ``previewHash``."""

    source = (
        payload.runtime_payload()
        if isinstance(payload, AgentRunAuthorizationPreview)
        else dict(payload)
    )
    allowed_fields = set(_PREVIEW_HASH_FIELDS) | {"previewHash"}
    unexpected = sorted(str(key) for key in source if key not in allowed_fields)
    if unexpected:
        raise ValueError(
            "AGENT_RUN_AUTHORIZATION_PREVIEW_HASH_FIELD_UNEXPECTED: "
            + ",".join(unexpected)
        )
    return agent_contract_hash(
        _PREVIEW_HASH_DOMAIN,
        exact_hash_payload(
            source,
            _PREVIEW_HASH_FIELDS,
            code="AGENT_RUN_AUTHORIZATION_PREVIEW_HASH_FIELD_MISSING",
        ),
    )


def _required_text(value: str, code: str) -> str:
    if not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError(code)
    return value


__all__ = [
    "AGENT_RUN_AUTHORIZATION_PREVIEW_CONTRACT_VERSION",
    "AgentRunAuthorizationManagedCondaSummary",
    "AgentRunAuthorizationPreview",
    "AgentRunAuthorizationReleaseSummary",
    "AgentRunAuthorizationResourceStepSummary",
    "AgentRunAuthorizationResourceSummary",
    "AgentRunAuthorizationRunnerProtocolSummary",
    "AgentRunAuthorizationRuntimeSummary",
    "AgentRunAuthorizationSnakemakeSummary",
    "AgentRunAuthorizationToolSummary",
    "AgentRunAuthorizationWorkflowProfileSummary",
    "AgentRunAuthorizationWorkflowRuntimeSummary",
    "agent_run_authorization_preview_hash",
]
