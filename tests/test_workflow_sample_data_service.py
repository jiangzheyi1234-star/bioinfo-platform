from __future__ import annotations

import asyncio
import base64
import hashlib
from typing import Any

import pytest

from apps.api.workflow_sample_data_service import (
    MOVING_PICTURES_PIPELINE_ID,
    SampleFile,
    WorkflowSampleDataIntegrityError,
    WorkflowSampleDataPrepareRequest,
    prepare_workflow_sample_data_uploads,
)


def test_sample_data_uploads_verify_integrity_before_upload(monkeypatch) -> None:
    content = b"sample_id\tbody_site\nsample-a\tgut\n"
    sample = _sample_file(content)
    runtime = FakeRuntime()
    monkeypatch.setattr("apps.api.workflow_sample_data_service.MOVING_PICTURES_FILES", [sample])
    monkeypatch.setattr("apps.api.workflow_sample_data_service._download_bytes", lambda url: content)
    monkeypatch.setattr("apps.api.workflow_sample_data_service.runtime_service", lambda: runtime)

    response = asyncio.run(
        prepare_workflow_sample_data_uploads(
            MOVING_PICTURES_PIPELINE_ID,
            WorkflowSampleDataPrepareRequest(serverId="srv_first"),
        )
    )

    assert len(runtime.uploads) == 1
    payload = runtime.uploads[0]
    assert payload["serverId"] == "srv_first"
    assert payload["filename"] == "sample-metadata.tsv"
    assert base64.b64decode(payload["contentBase64"]) == content
    item = response["data"]["items"][0]
    assert item["role"] == "metadata"
    assert item["sha256"] == sample.expected_sha256
    assert item["expectedSha256"] == sample.expected_sha256
    assert item["expectedSizeBytes"] == sample.expected_size_bytes
    assert item["integrityStatus"] == "passed"


def test_sample_data_uploads_fail_closed_on_integrity_mismatch(monkeypatch) -> None:
    content = b"changed sample data\n"
    runtime = FakeRuntime()
    monkeypatch.setattr("apps.api.workflow_sample_data_service.MOVING_PICTURES_FILES", [_sample_file(b"expected\n")])
    monkeypatch.setattr("apps.api.workflow_sample_data_service._download_bytes", lambda url: content)
    monkeypatch.setattr("apps.api.workflow_sample_data_service.runtime_service", lambda: runtime)

    with pytest.raises(WorkflowSampleDataIntegrityError, match="WORKFLOW_SAMPLE_DATA_INTEGRITY_MISMATCH"):
        asyncio.run(
            prepare_workflow_sample_data_uploads(
                MOVING_PICTURES_PIPELINE_ID,
                WorkflowSampleDataPrepareRequest(serverId="srv_first"),
            )
        )

    assert runtime.uploads == []


class FakeRuntime:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []

    def upload_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.uploads.append(payload)
        content = base64.b64decode(payload["contentBase64"])
        return {
            "uploadId": "upl_sample",
            "filename": payload["filename"],
            "sizeBytes": len(content),
        }


def _sample_file(content: bytes) -> SampleFile:
    return SampleFile(
        filename="sample-metadata.tsv",
        url="https://example.test/sample-metadata.tsv",
        role="metadata",
        mime_type="text/tab-separated-values",
        expected_sha256=hashlib.sha256(content).hexdigest(),
        expected_size_bytes=len(content),
    )
