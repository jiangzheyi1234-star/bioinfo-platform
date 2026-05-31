from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.remote_runner.api_models import (
    RunCreateRequest,
    ToolManifestRequest,
    UploadCreateRequest,
    WorkflowDesignDraftCompileRequest,
)


def test_remote_runner_upload_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UploadCreateRequest.model_validate(
            {
                "filename": "reads.fastq",
                "contentBase64": "QEdPQgo=",
                "mimeType": "text/plain",
                "content": "@GO\n",
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_remote_runner_tool_manifest_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ToolManifestRequest.model_validate(
            {
                "name": "seqkit",
                "source": "bioconda",
                "deprecatedRuleSpec": {"inputs": []},
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_remote_runner_run_request_requires_top_level_server_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunCreateRequest.model_validate(
            {
                "requestId": "req_demo",
                "runSpec": {"pipelineId": "file-summary-v1"},
            }
        )

    assert exc_info.value.errors()[0]["loc"] == ("serverId",)


def test_remote_runner_run_request_rejects_legacy_run_spec_server_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunCreateRequest.model_validate(
            {
                "serverId": "srv_demo",
                "requestId": "req_demo",
                "runSpec": {"serverId": "srv_legacy", "pipelineId": "file-summary-v1"},
            }
        )

    assert "UNSUPPORTED_LEGACY_PAYLOAD" in str(exc_info.value)


def test_remote_runner_workflow_design_compile_request_rejects_server_id() -> None:
    request = WorkflowDesignDraftCompileRequest.model_validate({})

    assert request.model_dump() == {}

    with pytest.raises(ValidationError) as exc_info:
        WorkflowDesignDraftCompileRequest.model_validate({"serverId": "srv_demo"})

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
