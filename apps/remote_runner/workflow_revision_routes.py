"""WorkflowRevision read routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .route_headers import AuthorizationHeader
from .workflow_revision_read_service import get_workflow_revision_from_request


router = APIRouter()


@router.get("/api/v1/workflow-revisions/{workflow_revision_id}")
async def get_workflow_revision(
    workflow_revision_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    return await get_workflow_revision_from_request(workflow_revision_id, authorization)
