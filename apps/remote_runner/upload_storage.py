from __future__ import annotations

import base64
import binascii
import hashlib
import uuid
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .errors import UploadTooLargeError
from .storage_core import get_connection, now_iso


MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def persist_upload(
    cfg: RemoteRunnerConfig,
    *,
    filename: str,
    content_base64: str,
    mime_type: str,
) -> dict[str, Any]:
    uploads_dir = Path(cfg.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    estimated_size = _estimate_base64_size(content_base64)
    if estimated_size > MAX_UPLOAD_BYTES:
        raise UploadTooLargeError("UPLOAD_TOO_LARGE")
    try:
        content = base64.b64decode(content_base64.encode("utf-8"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("INVALID_UPLOAD_BASE64") from exc
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadTooLargeError("UPLOAD_TOO_LARGE")
    upload_id = f"upl_{uuid.uuid4().hex[:12]}"
    target = uploads_dir / f"{upload_id}_{Path(filename).name}"
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_bytes(content)
    sha256 = hashlib.sha256(content).hexdigest()
    temp.rename(target)
    uploaded_at = now_iso()
    row = {
        "uploadId": upload_id,
        "filename": Path(filename).name,
        "path": str(target),
        "sizeBytes": len(content),
        "sha256": sha256,
        "mimeType": mime_type or "application/octet-stream",
        "uploadedAt": uploaded_at,
    }
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO uploads (upload_id, filename, path, size_bytes, sha256, mime_type, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["uploadId"],
                row["filename"],
                row["path"],
                row["sizeBytes"],
                row["sha256"],
                row["mimeType"],
                row["uploadedAt"],
            ),
        )
        connection.commit()
    return row


def fetch_upload(cfg: RemoteRunnerConfig, upload_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT * FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
    if row is None:
        return None
    return {
        "uploadId": row["upload_id"],
        "filename": row["filename"],
        "path": row["path"],
        "sizeBytes": row["size_bytes"],
        "sha256": row["sha256"],
        "mimeType": row["mime_type"],
        "uploadedAt": row["uploaded_at"],
    }


def _estimate_base64_size(content_base64: str) -> int:
    raw = "".join(str(content_base64 or "").split())
    if not raw:
        return 0
    padding = len(raw) - len(raw.rstrip("="))
    return max(0, (len(raw) * 3) // 4 - padding)
