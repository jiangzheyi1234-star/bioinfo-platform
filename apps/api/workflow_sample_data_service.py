"""Service functions for bundled workflow sample data."""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from urllib.request import Request, urlopen

from apps.api.route_utils import run_sync, runtime_service


class WorkflowSampleDataUnavailableError(ValueError):
    status_code = 404


@dataclass(frozen=True)
class SampleFile:
    filename: str
    url: str
    role: str
    mime_type: str


MOVING_PICTURES_PIPELINE_ID = "moving-pictures-16s-rulegraph-v1"

MOVING_PICTURES_FILES = [
    SampleFile(
        filename="sample-metadata.tsv",
        url="https://data.qiime2.org/2024.10/tutorials/moving-pictures/sample_metadata.tsv",
        role="metadata",
        mime_type="text/tab-separated-values",
    ),
    SampleFile(
        filename="barcodes.fastq.gz",
        url="https://data.qiime2.org/2024.10/tutorials/moving-pictures/emp-single-end-sequences/barcodes.fastq.gz",
        role="barcodes",
        mime_type="application/gzip",
    ),
    SampleFile(
        filename="sequences.fastq.gz",
        url="https://data.qiime2.org/2024.10/tutorials/moving-pictures/emp-single-end-sequences/sequences.fastq.gz",
        role="sequences",
        mime_type="application/gzip",
    ),
]


async def prepare_workflow_sample_data_uploads(pipeline_id: str) -> dict:
    if pipeline_id != MOVING_PICTURES_PIPELINE_ID:
        raise WorkflowSampleDataUnavailableError(
            f"No bundled sample data for pipeline: {pipeline_id}"
        )
    uploads = await run_sync(_download_and_upload_moving_pictures)
    return {
        "data": {
            "pipelineId": pipeline_id,
            "source": "QIIME 2 Moving Pictures tutorial",
            "items": uploads,
        }
    }


def _download_and_upload_moving_pictures() -> list[dict]:
    runtime = runtime_service()
    uploads = []
    for item in MOVING_PICTURES_FILES:
        content = _download_bytes(item.url)
        mime_type = item.mime_type or mimetypes.guess_type(item.filename)[0] or "application/octet-stream"
        upload = runtime.upload_file(
            {
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
            }
        )
    return uploads


def _download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "H2OMeta workflow sample loader"})
    with urlopen(request, timeout=60) as response:
        return response.read()
