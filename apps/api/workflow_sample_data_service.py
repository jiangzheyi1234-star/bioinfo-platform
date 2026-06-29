"""Service functions for bundled workflow sample data."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
from dataclasses import dataclass
from urllib.request import Request, urlopen

from pydantic import Field

from apps.api.route_utils import run_sync, runtime_service
from apps.api.models import ApiRequest


class WorkflowSampleDataUnavailableError(ValueError):
    status_code = 404


class WorkflowSampleDataIntegrityError(ValueError):
    status_code = 409


class WorkflowSampleDataPrepareRequest(ApiRequest):
    serverId: str = Field(min_length=1)


@dataclass(frozen=True)
class SampleFile:
    filename: str
    url: str
    role: str
    mime_type: str
    expected_sha256: str
    expected_size_bytes: int


MOVING_PICTURES_PIPELINE_ID = "moving-pictures-16s-rulegraph-v1"

MOVING_PICTURES_FILES = [
    SampleFile(
        filename="sample-metadata.tsv",
        url="https://data.qiime2.org/2024.10/tutorials/moving-pictures/sample_metadata.tsv",
        role="metadata",
        mime_type="text/tab-separated-values",
        expected_sha256="9dbfbedd90776d77c431faa914d81b0d6299fff10c364216dbcd5c6df5382cc9",
        expected_size_bytes=2094,
    ),
    SampleFile(
        filename="barcodes.fastq.gz",
        url="https://data.qiime2.org/2024.10/tutorials/moving-pictures/emp-single-end-sequences/barcodes.fastq.gz",
        role="barcodes",
        mime_type="application/gzip",
        expected_sha256="73c235c8185be1deef3038fd2b6497b7cc02acf3d7a37fda39e65a4a293e0d86",
        expected_size_bytes=3783785,
    ),
    SampleFile(
        filename="sequences.fastq.gz",
        url="https://data.qiime2.org/2024.10/tutorials/moving-pictures/emp-single-end-sequences/sequences.fastq.gz",
        role="sequences",
        mime_type="application/gzip",
        expected_sha256="7d9b2cea2aebfb46015796c073be6ba514018028cc1452d063aa0d716c059768",
        expected_size_bytes=25303756,
    ),
]


async def prepare_workflow_sample_data_uploads(
    pipeline_id: str,
    request: WorkflowSampleDataPrepareRequest,
) -> dict:
    if pipeline_id != MOVING_PICTURES_PIPELINE_ID:
        raise WorkflowSampleDataUnavailableError(
            f"No bundled sample data for pipeline: {pipeline_id}"
        )
    uploads = await run_sync(_download_and_upload_moving_pictures, request.serverId)
    return {
        "data": {
            "pipelineId": pipeline_id,
            "source": "QIIME 2 Moving Pictures tutorial",
            "items": uploads,
        }
    }


def _download_and_upload_moving_pictures(server_id: str) -> list[dict]:
    runtime = runtime_service()
    uploads = []
    for item in MOVING_PICTURES_FILES:
        content = _download_bytes(item.url)
        integrity = _verify_sample_file_integrity(item, content)
        mime_type = item.mime_type or mimetypes.guess_type(item.filename)[0] or "application/octet-stream"
        upload = runtime.upload_file(
            {
                "serverId": server_id,
                "filename": item.filename,
                "contentBase64": base64.b64encode(content).decode("ascii"),
                "mimeType": mime_type,
            }
        )
        uploads.append(
            {
                "uploadId": upload["uploadId"],
                "filename": upload["filename"],
                "sizeBytes": upload["sizeBytes"],
                "role": item.role,
                "sourceUrl": item.url,
                **integrity,
            }
        )
    return uploads


def _verify_sample_file_integrity(item: SampleFile, content: bytes) -> dict:
    actual_size = len(content)
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_size != item.expected_size_bytes or actual_sha256 != item.expected_sha256:
        raise WorkflowSampleDataIntegrityError(
            "WORKFLOW_SAMPLE_DATA_INTEGRITY_MISMATCH: "
            f"{item.filename} expected size={item.expected_size_bytes} sha256={item.expected_sha256} "
            f"got size={actual_size} sha256={actual_sha256}"
        )
    return {
        "sha256": actual_sha256,
        "expectedSha256": item.expected_sha256,
        "expectedSizeBytes": item.expected_size_bytes,
        "integrityStatus": "passed",
    }


def _download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "H2OMeta workflow sample loader"})
    with urlopen(request, timeout=60) as response:
        return response.read()
