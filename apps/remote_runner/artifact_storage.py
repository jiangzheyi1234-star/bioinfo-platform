from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


def persist_artifact(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    kind: str,
    path: Path,
    mime_type: str,
) -> dict[str, Any]:
    size_bytes, sha256 = _artifact_payload_stats(path)
    created_at = now_iso()
    artifact = {
        "artifactId": f"art_{uuid.uuid4().hex[:10]}",
        "runId": run_id,
        "kind": kind,
        "path": str(path),
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "mimeType": mime_type,
        "createdAt": created_at,
    }
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO artifacts (artifact_id, run_id, kind, path, size_bytes, sha256, mime_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact["artifactId"],
                artifact["runId"],
                artifact["kind"],
                artifact["path"],
                artifact["sizeBytes"],
                artifact["sha256"],
                artifact["mimeType"],
                artifact["createdAt"],
            ),
        )
        connection.commit()
    return artifact


def _artifact_payload_stats(path: Path) -> tuple[int, str]:
    if path.is_file():
        content = path.read_bytes()
        return len(content), hashlib.sha256(content).hexdigest()
    if path.is_dir():
        digest = hashlib.sha256()
        size_bytes = 0
        for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
            relative = child.relative_to(path).as_posix()
            if child.is_dir():
                digest.update(f"D\t{relative}\0".encode("utf-8"))
                continue
            if child.is_file():
                content = child.read_bytes()
                digest.update(f"F\t{relative}\0".encode("utf-8"))
                digest.update(content)
                size_bytes += len(content)
        return size_bytes, digest.hexdigest()
    raise ValueError("OUTPUT_ARTIFACT_PATH_INVALID")
