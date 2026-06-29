"""Official sample-data routes for runnable workflow demos."""

from __future__ import annotations

from fastapi import APIRouter

from apps.api.workflow_sample_data_service import (
    WorkflowSampleDataPrepareRequest,
    prepare_workflow_sample_data_uploads,
)


router = APIRouter()


@router.post("/api/v1/workflow-sample-data/{pipeline_id}/uploads")
async def upload_workflow_sample_data(pipeline_id: str, request: WorkflowSampleDataPrepareRequest) -> dict:
    return await prepare_workflow_sample_data_uploads(pipeline_id, request)
