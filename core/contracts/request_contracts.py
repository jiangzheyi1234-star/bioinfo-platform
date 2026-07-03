from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunSpecRequest(ContractModel):
    pipelineId: str = Field(min_length=1)
    projectId: str | None = None
    pipelineVersion: str | None = None
    runId: str | None = None
    runSpecVersion: str | None = None
    workflowRevisionId: str | None = None
    inputs: list[dict[str, Any]] | None = None
    params: dict[str, Any] | None = None
    resourceBindings: dict[str, Any] | None = None
    sampleDataPrepProof: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    workflowDesign: dict[str, Any] | None = None
    workflow: dict[str, Any] | None = None
