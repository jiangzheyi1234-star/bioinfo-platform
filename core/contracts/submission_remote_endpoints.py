from __future__ import annotations

from typing import Any


UPLOAD_CREATE = "upload.create"
RUN_CREATE = "run.create"


SUBMISSION_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    UPLOAD_CREATE: {
        "method": "POST",
        "path_template": "/api/v1/uploads",
        "operation_id": "createUpload",
        "governance_action": None,
        "request_schema": "upload-create-request.v1",
        "response_schema": "upload.v1",
        "cache_scope": "upload-command",
    },
    RUN_CREATE: {
        "method": "POST",
        "path_template": "/api/v1/runs",
        "operation_id": "createRun",
        "governance_action": "run.submit",
        "request_schema": "run-create-request.v1",
        "response_schema": "run-submission.v1",
        "cache_scope": "run-command",
        "invalidates": ("run-read-model",),
        "response_key": "",
        "accepted_statuses": (202,),
    },
}
