from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .api_models import UploadCreateRequest
from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError
from .storage import fetch_upload, persist_upload


def persist_upload_from_request(
    cfg: RemoteRunnerConfig,
    request: UploadCreateRequest,
) -> dict[str, Any]:
    return persist_upload(
        cfg,
        filename=request.filename,
        content_base64=request.contentBase64,
        mime_type=request.mimeType,
    )


def require_materialized_upload(
    cfg: RemoteRunnerConfig,
    upload_id: str,
) -> dict[str, Any]:
    """Return immutable upload metadata only after checking the stored bytes."""

    normalized_id = str(upload_id or "").strip()
    if not normalized_id:
        raise ValueError("INPUT_UPLOAD_ID_REQUIRED")
    upload = fetch_upload(cfg, normalized_id)
    if upload is None:
        raise RemoteRunnerNotFoundError("INPUT_UPLOAD_NOT_FOUND")
    uploads_root = Path(cfg.uploads_dir).resolve()
    path = Path(str(upload["path"])).resolve()
    if uploads_root not in (path, *path.parents):
        raise ValueError("INPUT_UPLOAD_PATH_INVALID")
    if not path.is_file():
        raise ValueError("INPUT_UPLOAD_FILE_MISSING")
    if path.stat().st_size != int(upload["sizeBytes"]):
        raise ValueError("INPUT_UPLOAD_SIZE_MISMATCH")
    if _file_sha256(path) != str(upload["sha256"]):
        raise ValueError("INPUT_UPLOAD_SHA256_MISMATCH")
    return {
        key: upload[key]
        for key in (
            "uploadId",
            "filename",
            "sizeBytes",
            "sha256",
            "mimeType",
            "uploadedAt",
        )
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
