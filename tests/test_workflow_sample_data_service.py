from __future__ import annotations

import asyncio
import base64
import hashlib
from typing import Any

import pytest

from apps.api.workflow_sample_data_service import (
    MOVING_PICTURES_PIPELINE_ID,
    WORKFLOW_SAMPLE_DATA_PREP_PROOF_SCHEMA,
    SampleFile,
    WorkflowSampleDataIntegrityError,
    WorkflowSampleDataPrepareRequest,
    WorkflowSampleDataSourceError,
    prepare_workflow_sample_data_uploads,
)


def test_sample_data_uploads_verify_integrity_before_upload(monkeypatch, tmp_path) -> None:
    content = b"sample_id\tbody_site\nsample-a\tgut\n"
    sample = _sample_file(content)
    runtime = FakeRuntime()
    monkeypatch.setenv("H2OMETA_SAMPLE_DATA_CACHE_DIR", str(tmp_path / "sample-cache"))
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
    assert item["prepProof"]["schemaVersion"] == WORKFLOW_SAMPLE_DATA_PREP_PROOF_SCHEMA
    assert item["prepProof"]["cacheStatus"] == "stored"
    assert item["prepProof"]["downloadStatus"] == "downloaded"
    assert item["prepProof"]["downloadAttempts"] == 1
    assert response["data"]["prepProof"]["schemaVersion"] == WORKFLOW_SAMPLE_DATA_PREP_PROOF_SCHEMA
    assert response["data"]["prepProof"]["cachePolicy"] == "verified-sha256-local-cache"


def test_sample_data_uploads_fail_closed_on_integrity_mismatch(monkeypatch, tmp_path) -> None:
    content = b"changed sample data\n"
    runtime = FakeRuntime()
    monkeypatch.setenv("H2OMETA_SAMPLE_DATA_CACHE_DIR", str(tmp_path / "sample-cache"))
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


def test_sample_data_uploads_reuse_verified_local_cache(monkeypatch, tmp_path) -> None:
    content = b"sample_id\tbody_site\nsample-a\tgut\n"
    sample = _sample_file(content)
    runtime = FakeRuntime()
    downloads: list[str] = []
    monkeypatch.setenv("H2OMETA_SAMPLE_DATA_CACHE_DIR", str(tmp_path / "sample-cache"))
    monkeypatch.setattr("apps.api.workflow_sample_data_service.MOVING_PICTURES_FILES", [sample])

    def fake_download(url: str) -> bytes:
        downloads.append(url)
        return content

    monkeypatch.setattr("apps.api.workflow_sample_data_service._download_bytes", fake_download)
    monkeypatch.setattr("apps.api.workflow_sample_data_service.runtime_service", lambda: runtime)

    first = asyncio.run(
        prepare_workflow_sample_data_uploads(
            MOVING_PICTURES_PIPELINE_ID,
            WorkflowSampleDataPrepareRequest(serverId="srv_first"),
        )
    )
    second = asyncio.run(
        prepare_workflow_sample_data_uploads(
            MOVING_PICTURES_PIPELINE_ID,
            WorkflowSampleDataPrepareRequest(serverId="srv_first"),
        )
    )

    assert downloads == [sample.url]
    assert first["data"]["items"][0]["prepProof"]["cacheStatus"] == "stored"
    assert second["data"]["items"][0]["prepProof"]["cacheStatus"] == "hit"
    assert second["data"]["items"][0]["prepProof"]["downloadStatus"] == "skipped-cache-hit"
    assert second["data"]["items"][0]["prepProof"]["downloadAttempts"] == 0


def test_sample_data_uploads_report_source_failures(monkeypatch, tmp_path) -> None:
    sample = _sample_file(b"expected\n")
    runtime = FakeRuntime()
    monkeypatch.setenv("H2OMETA_SAMPLE_DATA_CACHE_DIR", str(tmp_path / "sample-cache"))
    monkeypatch.setattr("apps.api.workflow_sample_data_service.MOVING_PICTURES_FILES", [sample])

    def fail_download(_url: str) -> bytes:
        raise TimeoutError("timed out")

    monkeypatch.setattr("apps.api.workflow_sample_data_service._download_bytes", fail_download)
    monkeypatch.setattr("apps.api.workflow_sample_data_service.runtime_service", lambda: runtime)

    with pytest.raises(WorkflowSampleDataSourceError, match="WORKFLOW_SAMPLE_DATA_SOURCE_UNAVAILABLE"):
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
