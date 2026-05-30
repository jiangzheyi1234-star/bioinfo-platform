from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.models import RunSubmitRequest, ToolManifestRequest, UploadSubmitRequest


def test_upload_submit_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UploadSubmitRequest.model_validate(
            {
                "serverId": "srv_demo",
                "filename": "reads.fastq",
                "contentBase64": "QEdPQgo=",
                "mimeType": "text/plain",
                "content": "@GO\n",
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_tool_manifest_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ToolManifestRequest.model_validate(
            {
                "serverId": "srv_demo",
                "name": "seqkit",
                "source": "bioconda",
                "deprecatedRuleSpec": {"inputs": []},
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_run_submit_request_rejects_top_level_pipeline_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunSubmitRequest.model_validate(
            {
                "serverId": "srv_demo",
                "pipelineId": "file-summary-v1",
                "runSpec": {"inputs": []},
            }
        )

    assert "UNSUPPORTED_LEGACY_PAYLOAD" in str(exc_info.value)


def test_run_submit_request_rejects_legacy_run_spec_server_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunSubmitRequest.model_validate(
            {
                "serverId": "srv_demo",
                "runSpec": {"serverId": "srv_legacy", "pipelineId": "file-summary-v1"},
            }
        )

    assert "UNSUPPORTED_LEGACY_PAYLOAD" in str(exc_info.value)


def test_run_submit_request_accepts_pipeline_id_inside_run_spec() -> None:
    request = RunSubmitRequest.model_validate(
        {
            "serverId": "srv_demo",
            "runSpec": {"pipelineId": "file-summary-v1", "inputs": []},
        }
    )

    assert request.serverId == "srv_demo"
    assert request.runSpec["pipelineId"] == "file-summary-v1"
