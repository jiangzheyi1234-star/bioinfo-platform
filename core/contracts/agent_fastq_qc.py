"""Strict contracts for the deterministic single-sample FASTQ QC adapter."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import Field, field_validator

from .agent_session import AgentSessionCommand, AgentSessionModel


AGENT_FASTQ_QC_GOAL_CONTEXT_VERSION = "agent-fastq-qc-goal.v1"
AGENT_FASTQ_QC_ADAPTER_ID = "h2ometa.fastq-qc.v1"
AGENT_FASTQ_QC_ADAPTER_VERSION = "1.0.0"
AGENT_FASTQ_QC_MODEL_REF = "deterministic:capability-bundle-v1"
AGENT_FASTQ_QC_TOOL_VERSIONS = {
    "fastqc": "0.12.1",
    "multiqc": "1.34",
}
AGENT_FASTQ_QC_TOOL_PROFILES = {
    "fastqc": {
        "profileVersion": 2,
        "packageSpec": "bioconda::fastqc=0.12.1",
        "wrapper": "v9.8.0/bio/fastqc",
        "ruleTemplateSha256": "f49d2d2c5168d6156e9ea7a6e5cb86d134e745dbf9d12513a3d87dd013729b32",
    },
    "multiqc": {
        "profileVersion": 3,
        "packageSpec": "bioconda::multiqc=1.34",
        "wrapper": "v9.8.0/bio/multiqc",
        "ruleTemplateSha256": "4f1ac65121cf4411ab9aa4d49aa9751796c85bad455b992b6e0fcb92a596ed1f",
    },
}

_FASTQ_SUFFIXES = (".fastq", ".fq")
_FORBIDDEN_FILENAME_CHARACTERS = frozenset('/\\:*?"<>|')


class AgentFastqQcInput(AgentSessionModel):
    uploadId: str = Field(min_length=1, max_length=500)
    filename: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sizeBytes: int = Field(ge=1, le=32 * 1024 * 1024)
    mimeType: Literal["text/plain"]

    @field_validator("uploadId")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("INPUT_FASTQ_QC_MANIFEST_TEXT_REQUIRED")
        return normalized

    @field_validator("filename")
    @classmethod
    def validate_fastq_filename(cls, value: str) -> str:
        normalized = value.strip()
        if (
            not normalized
            or normalized in {".", ".."}
            or any(character in _FORBIDDEN_FILENAME_CHARACTERS for character in normalized)
            or any(ord(character) < 32 for character in normalized)
        ):
            raise ValueError("INPUT_FASTQ_QC_FILENAME_INVALID")
        if not normalized.lower().endswith(_FASTQ_SUFFIXES):
            raise ValueError("INPUT_FASTQ_QC_FILE_TYPE_UNSUPPORTED")
        return normalized


class AgentFastqQcGoalContext(AgentSessionModel):
    schemaVersion: Literal["agent-fastq-qc-goal.v1"]
    analysis: Literal["fastq-qc"]
    inputs: list[AgentFastqQcInput] = Field(min_length=1, max_length=1)
    reportFormat: Literal["multiqc-html"] = "multiqc-html"


class AgentFastqQcPlanCommand(AgentSessionCommand):
    """Plan from immutable session goal context; callers cannot submit a graph."""


class AgentFastqQcReplanCommand(AgentSessionCommand):
    """Carry an audited reason while typed FASTQ QC adjustments remain unsupported."""

    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("AGENT_SESSION_REPLAN_REASON_REQUIRED")
        return normalized


def fastq_qc_manifest_digest(context: AgentFastqQcGoalContext | dict[str, Any]) -> str:
    normalized = AgentFastqQcGoalContext.model_validate(context)
    payload = {
        "schemaVersion": normalized.schemaVersion,
        "inputs": [item.runtime_payload() for item in normalized.inputs],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


__all__ = [
    "AGENT_FASTQ_QC_ADAPTER_ID",
    "AGENT_FASTQ_QC_ADAPTER_VERSION",
    "AGENT_FASTQ_QC_GOAL_CONTEXT_VERSION",
    "AGENT_FASTQ_QC_MODEL_REF",
    "AGENT_FASTQ_QC_TOOL_PROFILES",
    "AGENT_FASTQ_QC_TOOL_VERSIONS",
    "AgentFastqQcGoalContext",
    "AgentFastqQcInput",
    "AgentFastqQcPlanCommand",
    "AgentFastqQcReplanCommand",
    "fastq_qc_manifest_digest",
]
