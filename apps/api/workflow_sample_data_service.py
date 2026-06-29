"""Service functions for bundled workflow sample data."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from pydantic import Field

from apps.api.route_utils import run_sync, runtime_service
from apps.api.models import ApiRequest


class WorkflowSampleDataUnavailableError(ValueError):
    status_code = 404


class WorkflowSampleDataIntegrityError(ValueError):
    status_code = 409


class WorkflowSampleDataSourceError(ValueError):
    status_code = 424


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


@dataclass(frozen=True)
class PreparedSampleFile:
    content: bytes
    prep_proof: dict


MOVING_PICTURES_PIPELINE_ID = "moving-pictures-16s-rulegraph-v1"
WORKFLOW_SAMPLE_DATA_SOURCE = "QIIME 2 Moving Pictures tutorial"
WORKFLOW_SAMPLE_DATA_CACHE_POLICY = "verified-sha256-local-cache"
WORKFLOW_SAMPLE_DATA_PREP_PROOF_SCHEMA = "h2ometa.workflow-sample-data-prep-proof.v1"
WORKFLOW_SAMPLE_DATA_STATUS_SCHEMA = "h2ometa.workflow-sample-data-status.v1"

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
            "source": WORKFLOW_SAMPLE_DATA_SOURCE,
            "items": uploads,
            "prepProof": _sample_data_prep_proof(uploads),
        }
    }


async def inspect_workflow_sample_data_status(pipeline_id: str) -> dict:
    if pipeline_id != MOVING_PICTURES_PIPELINE_ID:
        raise WorkflowSampleDataUnavailableError(
            f"No bundled sample data for pipeline: {pipeline_id}"
        )
    return {"data": await run_sync(_inspect_moving_pictures_sample_data_status)}


def _download_and_upload_moving_pictures(server_id: str) -> list[dict]:
    runtime = runtime_service()
    uploads = []
    for item in MOVING_PICTURES_FILES:
        prepared = _prepare_sample_file(item)
        integrity = _verify_sample_file_integrity(item, prepared.content)
        mime_type = item.mime_type or mimetypes.guess_type(item.filename)[0] or "application/octet-stream"
        upload = runtime.upload_file(
            {
                "serverId": server_id,
                "filename": item.filename,
                "contentBase64": base64.b64encode(prepared.content).decode("ascii"),
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
                "prepProof": prepared.prep_proof,
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


def _sample_data_prep_proof(uploads: list[dict]) -> dict:
    return {
        "schemaVersion": WORKFLOW_SAMPLE_DATA_PREP_PROOF_SCHEMA,
        "source": WORKFLOW_SAMPLE_DATA_SOURCE,
        "cachePolicy": WORKFLOW_SAMPLE_DATA_CACHE_POLICY,
        "items": [item.get("prepProof") for item in uploads if item.get("prepProof")],
    }


def _inspect_moving_pictures_sample_data_status() -> dict:
    items = [_inspect_sample_file_status(item) for item in MOVING_PICTURES_FILES]
    blocker_codes = sorted({code for item in items for code in item.get("blockerCodes", [])})
    verified_count = sum(1 for item in items if item["cacheStatus"] == "verified")
    missing_count = sum(1 for item in items if item["cacheStatus"] == "missing")
    status = "blocked" if blocker_codes else "ready" if verified_count == len(items) else "source_required"
    return {
        "schemaVersion": WORKFLOW_SAMPLE_DATA_STATUS_SCHEMA,
        "pipelineId": MOVING_PICTURES_PIPELINE_ID,
        "source": WORKFLOW_SAMPLE_DATA_SOURCE,
        "cachePolicy": WORKFLOW_SAMPLE_DATA_CACHE_POLICY,
        "status": status,
        "itemCount": len(items),
        "verifiedCacheCount": verified_count,
        "missingCacheCount": missing_count,
        "sourceRequired": status == "source_required",
        "blockerCodes": blocker_codes,
        "items": items,
    }


def _inspect_sample_file_status(item: SampleFile) -> dict:
    base = {
        "filename": item.filename,
        "role": item.role,
        "sourceUrl": item.url,
        "expectedSha256": item.expected_sha256,
        "expectedSizeBytes": item.expected_size_bytes,
    }
    path = _sample_cache_path(item)
    if not path.exists():
        return {
            **base,
            "cacheStatus": "missing",
            "status": "source_required",
            "sourceRequired": True,
            "blockerCodes": [],
        }
    try:
        content = path.read_bytes()
    except OSError:
        return {
            **base,
            "cacheStatus": "unreadable",
            "status": "blocked",
            "sourceRequired": False,
            "blockerCodes": ["WORKFLOW_SAMPLE_DATA_CACHE_UNREADABLE"],
        }
    actual_size = len(content)
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_size != item.expected_size_bytes or actual_sha256 != item.expected_sha256:
        return {
            **base,
            "cacheStatus": "integrity_mismatch",
            "status": "blocked",
            "sourceRequired": False,
            "observedSizeBytes": actual_size,
            "blockerCodes": ["WORKFLOW_SAMPLE_DATA_CACHE_INTEGRITY_MISMATCH"],
        }
    return {
        **base,
        "cacheStatus": "verified",
        "status": "ready",
        "sourceRequired": False,
        "sha256": actual_sha256,
        "sizeBytes": actual_size,
        "blockerCodes": [],
    }


def _prepare_sample_file(item: SampleFile) -> PreparedSampleFile:
    cached = _read_verified_sample_cache(item)
    if cached is not None:
        return PreparedSampleFile(
            content=cached,
            prep_proof=_sample_prep_proof(
                item,
                cache_status="hit",
                download_status="skipped-cache-hit",
                download_attempts=0,
            ),
        )

    content, attempts = _download_sample_bytes(item)
    integrity = _verify_sample_file_integrity(item, content)
    cache_status = _write_sample_cache(item, content)
    return PreparedSampleFile(
        content=content,
        prep_proof=_sample_prep_proof(
            item,
            cache_status=cache_status,
            download_status="downloaded",
            download_attempts=attempts,
            sha256=integrity["sha256"],
        ),
    )


def _read_verified_sample_cache(item: SampleFile) -> bytes | None:
    path = _sample_cache_path(item)
    if not path.exists():
        return None
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise WorkflowSampleDataSourceError(
            f"WORKFLOW_SAMPLE_DATA_CACHE_UNREADABLE: {item.filename} cause={type(exc).__name__}"
        ) from exc
    _verify_sample_file_integrity(item, content)
    return content


def _write_sample_cache(item: SampleFile, content: bytes) -> str:
    path = _sample_cache_path(item)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError:
        return "write-failed"
    return "stored"


def _sample_cache_path(item: SampleFile) -> Path:
    safe_name = item.filename.replace("/", "_").replace("\\", "_")
    return _sample_data_cache_root() / MOVING_PICTURES_PIPELINE_ID / f"{item.role}-{item.expected_sha256}-{safe_name}"


def _sample_data_cache_root() -> Path:
    configured = os.environ.get("H2OMETA_SAMPLE_DATA_CACHE_DIR", "").strip()
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "H2OMeta" / "sample-data-cache"
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME", "").strip()
    return (Path(xdg_cache_home) if xdg_cache_home else Path.home() / ".cache") / "h2ometa" / "sample-data-cache"


def _download_sample_bytes(item: SampleFile) -> tuple[bytes, int]:
    attempts = 2
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _download_bytes(item.url), attempt
        except (OSError, TimeoutError) as exc:
            last_error = exc
    raise WorkflowSampleDataSourceError(
        f"WORKFLOW_SAMPLE_DATA_SOURCE_UNAVAILABLE: {item.filename} "
        f"url={item.url} attempts={attempts} cause={type(last_error).__name__}"
    ) from last_error


def _sample_prep_proof(
    item: SampleFile,
    *,
    cache_status: str,
    download_attempts: int,
    download_status: str,
    sha256: str | None = None,
) -> dict:
    return {
        "schemaVersion": WORKFLOW_SAMPLE_DATA_PREP_PROOF_SCHEMA,
        "role": item.role,
        "filename": item.filename,
        "sourceUrl": item.url,
        "sha256": sha256 or item.expected_sha256,
        "expectedSha256": item.expected_sha256,
        "expectedSizeBytes": item.expected_size_bytes,
        "cacheStatus": cache_status,
        "downloadStatus": download_status,
        "downloadAttempts": download_attempts,
    }


def _download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "H2OMeta workflow sample loader"})
    with urlopen(request, timeout=60) as response:
        return response.read()
