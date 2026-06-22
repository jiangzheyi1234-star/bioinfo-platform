from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


def local_artifact_location(path: Path) -> dict[str, str]:
    resolved = Path(path).resolve()
    return {
        "storageBackend": "local",
        "storageUri": resolved.as_uri(),
        "localPath": str(resolved),
    }


def artifact_local_path(record: dict[str, Any]) -> Path:
    storage_backend = str(record.get("storageBackend") or record.get("storage_backend") or "local")
    if storage_backend != "local":
        raise ValueError(f"ARTIFACT_STORAGE_BACKEND_UNSUPPORTED: {storage_backend}")
    storage_uri = str(record.get("storageUri") or record.get("storage_uri") or "").strip()
    if storage_uri:
        return _path_from_file_uri(storage_uri)
    local_path = str(record.get("localPath") or record.get("path") or "").strip()
    if local_path:
        return Path(local_path)
    raise ValueError("ARTIFACT_STORAGE_URI_REQUIRED")


def read_artifact_preview_text(record: dict[str, Any], *, limit: int) -> tuple[str, bool]:
    path = artifact_local_path(record)
    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    truncated = len(payload) > limit
    return payload[:limit].decode("utf-8", errors="ignore"), truncated


def iter_artifact_file_payloads(record: dict[str, Any]):
    path = artifact_local_path(record)
    if path.is_file():
        yield path.name or "artifact", path.read_bytes()
        return
    if not path.is_dir():
        raise ValueError("RESULT_ARTIFACT_PATH_INVALID")
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        if child.is_file():
            yield child.relative_to(path).as_posix(), child.read_bytes()


def artifact_payload_stats(path: Path) -> tuple[int, str]:
    artifact_path = Path(path)
    if artifact_path.is_file():
        return _file_payload_stats(artifact_path)
    if artifact_path.is_dir():
        return _directory_payload_stats(artifact_path)
    raise ValueError("OUTPUT_ARTIFACT_PATH_INVALID")


def _directory_payload_stats(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size_bytes = 0
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix()
        if child.is_dir():
            digest.update(f"D\t{relative}\0".encode("utf-8"))
            continue
        if child.is_file():
            digest.update(f"F\t{relative}\0".encode("utf-8"))
            file_size = _update_digest_with_file(digest, child)
            size_bytes += file_size
    return size_bytes, digest.hexdigest()


def _file_payload_stats(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size_bytes = _update_digest_with_file(digest, path)
    return size_bytes, digest.hexdigest()


def _update_digest_with_file(digest: Any, path: Path) -> int:
    size_bytes = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size_bytes += len(chunk)
            digest.update(chunk)
    return size_bytes


def _path_from_file_uri(storage_uri: str) -> Path:
    parsed = urlparse(storage_uri)
    if parsed.scheme != "file":
        raise ValueError(f"ARTIFACT_STORAGE_URI_UNSUPPORTED: {parsed.scheme or 'missing'}")
    path = unquote(parsed.path)
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    elif len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return Path(path)
