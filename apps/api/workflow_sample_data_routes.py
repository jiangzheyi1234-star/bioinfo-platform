"""Official sample-data helpers for runnable workflow demos."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from dataclasses import dataclass
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException

from apps.api.runtime import get_runtime_service
from core.app_runtime.errors import RuntimeServiceError


router = APIRouter()


@dataclass(frozen=True)
class SampleFile:
    filename: str
    url: str
    role: str
    mime_type: str


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


@router.post("/api/v1/workflow-sample-data/{pipeline_id}/uploads")
async def upload_workflow_sample_data(pipeline_id: str) -> dict:
    if pipeline_id != "moving-pictures-16s-rulegraph-v1":
        raise HTTPException(status_code=404, detail=f"No bundled sample data for pipeline: {pipeline_id}")
    try:
        uploads = await asyncio.to_thread(_download_and_upload_moving_pictures)
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Remote runner is not ready.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "Failed to prepare sample data.") from exc
    return {
        "data": {
            "pipelineId": pipeline_id,
            "source": "QIIME 2 Moving Pictures tutorial",
            "items": uploads,
        }
    }


def _download_and_upload_moving_pictures() -> list[dict]:
    runtime = get_runtime_service()
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
