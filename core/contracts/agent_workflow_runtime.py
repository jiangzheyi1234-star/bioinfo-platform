"""Bound launcher-runtime proof contracts for Agent-authorized workflows."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .agent_contract_hash import agent_contract_hash
from .agent_session import AgentSessionModel, assert_agent_session_json_safe


AGENT_WORKFLOW_RUNTIME_PROOF_SCHEMA = "agent-workflow-runtime-proof.v1"
WORKFLOW_RUNTIME_LOCK_V2_SCHEMA = "workflow-runtime-lock.v2"

_HEX_SHA256 = r"^[0-9a-f]{64}$"
_DIGEST_SHA256 = r"^sha256:[0-9a-f]{64}$"


class AgentRunnerProtocolProof(AgentSessionModel):
    version: str = Field(min_length=1, max_length=200)
    fingerprint: str = Field(pattern=_DIGEST_SHA256)
    bootstrapManifestPath: str = Field(min_length=1, max_length=4096)
    bootstrapManifestFingerprint: str = Field(pattern=_DIGEST_SHA256)
    artifactArchiveSha256Path: str = Field(min_length=1, max_length=4096)
    declaredArtifactArchiveSha256: str = Field(pattern=_DIGEST_SHA256)

    @field_validator(
        "version",
        "bootstrapManifestPath",
        "artifactArchiveSha256Path",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUNTIME_RUNNER_PROOF_TEXT_REQUIRED")


class AgentWorkflowRuntimeIdentity(AgentSessionModel):
    provider: Literal["conda-pack"]
    source: Literal["artifact"]
    version: str = Field(min_length=1, max_length=200)
    platform: Literal["linux-64"]
    root: str = Field(min_length=1, max_length=4096)
    bootstrapManifestPath: str = Field(min_length=1, max_length=4096)
    bootstrapManifestFingerprint: str = Field(pattern=_DIGEST_SHA256)
    artifactArchiveSha256Path: str = Field(min_length=1, max_length=4096)
    declaredArtifactArchiveSha256: str = Field(pattern=_DIGEST_SHA256)
    snakemakePackageVersion: str = Field(min_length=1, max_length=200)
    pythonPath: str = Field(min_length=1, max_length=4096)
    pythonResolvedPath: str = Field(min_length=1, max_length=4096)
    pythonSha256: str = Field(pattern=_HEX_SHA256)

    @field_validator(
        "version",
        "root",
        "bootstrapManifestPath",
        "artifactArchiveSha256Path",
        "snakemakePackageVersion",
        "pythonPath",
        "pythonResolvedPath",
    )
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_WORKFLOW_RUNTIME_IDENTITY_REQUIRED")


class AgentRuntimeExecutableProof(AgentSessionModel):
    path: str = Field(min_length=1, max_length=4096)
    sha256: str = Field(pattern=_HEX_SHA256)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUNTIME_EXECUTABLE_PATH_REQUIRED")


class AgentSnakemakeRuntimeProof(AgentRuntimeExecutableProof):
    reportedVersion: str = Field(min_length=1, max_length=200)

    @field_validator("reportedVersion")
    @classmethod
    def validate_reported_version(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUNTIME_SNAKEMAKE_VERSION_REQUIRED")


class AgentManagedCondaRuntimeProof(AgentRuntimeExecutableProof):
    rootPrefix: str = Field(min_length=1, max_length=4096)

    @field_validator("rootPrefix")
    @classmethod
    def validate_root_prefix(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUNTIME_CONDA_ROOT_PREFIX_REQUIRED")


class AgentWorkflowProfileProof(AgentSessionModel):
    directory: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=255)
    fileSha256: str = Field(pattern=_HEX_SHA256)
    condaPrefix: str = Field(min_length=1, max_length=4096)
    wrapperPrefix: str = Field(min_length=1, max_length=8192)

    @field_validator("directory", "name", "condaPrefix", "wrapperPrefix")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUNTIME_WORKFLOW_PROFILE_TEXT_REQUIRED")


class AgentReleaseRuntimeProof(AgentSessionModel):
    directory: str = Field(min_length=1, max_length=4096)
    treeHash: str = Field(pattern=_HEX_SHA256)
    wrapperMirrorDirectory: str = Field(min_length=1, max_length=4096)
    wrapperMirrorTreeHash: str = Field(pattern=_HEX_SHA256)

    @field_validator("directory", "wrapperMirrorDirectory")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _required_text(value, "AGENT_RUNTIME_RELEASE_PATH_REQUIRED")


class AgentWorkflowRuntimeProof(AgentSessionModel):
    schemaVersion: Literal["agent-workflow-runtime-proof.v1"]
    platform: Literal["linux-64"]
    runnerProtocol: AgentRunnerProtocolProof
    workflowRuntime: AgentWorkflowRuntimeIdentity
    snakemake: AgentSnakemakeRuntimeProof
    managedConda: AgentManagedCondaRuntimeProof
    workflowProfile: AgentWorkflowProfileProof
    release: AgentReleaseRuntimeProof

    @model_validator(mode="after")
    def reject_secret_like_values(self) -> "AgentWorkflowRuntimeProof":
        assert_agent_session_json_safe(
            self.runtime_payload(),
            path="workflowRuntime.proof",
        )
        return self


class WorkflowRuntimeLockV2(AgentSessionModel):
    schemaVersion: Literal["workflow-runtime-lock.v2"]
    proof: AgentWorkflowRuntimeProof
    runtimeProofHash: str = Field(pattern=_HEX_SHA256)

    @model_validator(mode="after")
    def validate_runtime_proof_hash(self) -> "WorkflowRuntimeLockV2":
        expected = agent_workflow_runtime_proof_hash(self.proof)
        if not hmac.compare_digest(expected, self.runtimeProofHash):
            raise ValueError("AGENT_WORKFLOW_RUNTIME_PROOF_HASH_MISMATCH")
        return self


def agent_workflow_runtime_proof_hash(
    proof: AgentWorkflowRuntimeProof | Mapping[str, object],
) -> str:
    normalized = AgentWorkflowRuntimeProof.model_validate(
        proof.runtime_payload()
        if isinstance(proof, AgentWorkflowRuntimeProof)
        else proof
    )
    return agent_contract_hash(
        AGENT_WORKFLOW_RUNTIME_PROOF_SCHEMA,
        normalized.runtime_payload(),
    )


def build_workflow_runtime_lock_v2(
    proof: AgentWorkflowRuntimeProof | Mapping[str, object],
) -> WorkflowRuntimeLockV2:
    normalized = AgentWorkflowRuntimeProof.model_validate(
        proof.runtime_payload()
        if isinstance(proof, AgentWorkflowRuntimeProof)
        else proof
    )
    return WorkflowRuntimeLockV2.model_validate(
        {
            "schemaVersion": WORKFLOW_RUNTIME_LOCK_V2_SCHEMA,
            "proof": normalized.runtime_payload(),
            "runtimeProofHash": agent_workflow_runtime_proof_hash(normalized),
        }
    )


def workflow_runtime_lock_v2_hash(
    runtime_lock: WorkflowRuntimeLockV2 | Mapping[str, object],
) -> str:
    normalized = WorkflowRuntimeLockV2.model_validate(
        runtime_lock.runtime_payload()
        if isinstance(runtime_lock, WorkflowRuntimeLockV2)
        else runtime_lock
    )
    return agent_contract_hash(
        WORKFLOW_RUNTIME_LOCK_V2_SCHEMA,
        normalized.runtime_payload(),
    )


def _required_text(value: str, code: str) -> str:
    if not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError(code)
    return value


__all__ = [
    "AGENT_WORKFLOW_RUNTIME_PROOF_SCHEMA",
    "WORKFLOW_RUNTIME_LOCK_V2_SCHEMA",
    "AgentWorkflowRuntimeProof",
    "WorkflowRuntimeLockV2",
    "agent_workflow_runtime_proof_hash",
    "build_workflow_runtime_lock_v2",
    "workflow_runtime_lock_v2_hash",
]
