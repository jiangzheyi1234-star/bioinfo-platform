from __future__ import annotations

from typing import Any

from .api_models import UploadCreateRequest
from .config import RemoteRunnerConfig
from .storage import persist_upload


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
