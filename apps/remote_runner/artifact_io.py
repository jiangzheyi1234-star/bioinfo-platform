from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from .artifact_directory_package import (
    DIRECTORY_PACKAGE_SCHEMA_VERSION,
    create_directory_artifact_package,
    directory_package_preview,
    directory_package_stats,
    iter_directory_package_payloads,
)
from .config import RemoteRunnerConfig


def local_artifact_location(path: Path) -> dict[str, str]:
    resolved = Path(path).resolve()
    return {
        "storageBackend": "local",
        "storageUri": resolved.as_uri(),
        "localPath": str(resolved),
    }


def persist_artifact_location(
    cfg: RemoteRunnerConfig,
    *,
    path: Path,
    run_id: str,
    artifact_id: str,
    sha256: str,
    size_bytes: int,
    mime_type: str,
) -> dict[str, str]:
    backend = artifact_storage_backend(cfg)
    if backend == "local":
        return local_artifact_location(path)
    if backend == "s3":
        return _persist_s3_artifact(
            cfg,
            path=path,
            run_id=run_id,
            artifact_id=artifact_id,
            sha256=sha256,
            size_bytes=size_bytes,
            mime_type=mime_type,
        )
    raise ValueError(f"ARTIFACT_STORAGE_BACKEND_UNSUPPORTED: {backend}")


def artifact_storage_backend(cfg: RemoteRunnerConfig) -> str:
    backend = str(cfg.artifact_storage_backend or "local").strip().lower()
    if backend not in {"local", "s3"}:
        raise ValueError(f"ARTIFACT_STORAGE_BACKEND_UNSUPPORTED: {backend or 'missing'}")
    return backend


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


def read_artifact_preview_text(
    cfg: RemoteRunnerConfig,
    record: dict[str, Any],
    *,
    limit: int,
) -> tuple[str, bool]:
    payload = read_artifact_bytes(cfg, record, limit=limit + 1)
    truncated = len(payload) > limit
    return payload[:limit].decode("utf-8", errors="ignore"), truncated


def iter_artifact_file_payloads(cfg: RemoteRunnerConfig, record: dict[str, Any]):
    storage_backend = str(record.get("storageBackend") or record.get("storage_backend") or "local")
    if storage_backend == "s3":
        if _artifact_is_directory(record):
            yield from iter_directory_package_payloads(read_artifact_bytes(cfg, record))
            return
        yield _artifact_filename(record), read_artifact_bytes(cfg, record)
        return
    path = artifact_local_path(record)
    if path.is_file():
        yield path.name or "artifact", path.read_bytes()
        return
    if not path.is_dir():
        raise ValueError("RESULT_ARTIFACT_PATH_INVALID")
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        if child.is_file():
            yield child.relative_to(path).as_posix(), child.read_bytes()


def read_artifact_bytes(
    cfg: RemoteRunnerConfig,
    record: dict[str, Any],
    *,
    limit: int | None = None,
) -> bytes:
    storage_backend = str(record.get("storageBackend") or record.get("storage_backend") or "local")
    if storage_backend == "local":
        path = artifact_local_path(record)
        with path.open("rb") as handle:
            return handle.read(limit if limit is not None else -1)
    if storage_backend == "s3":
        return _read_s3_artifact_bytes(cfg, record, limit=limit)
    raise ValueError(f"ARTIFACT_STORAGE_BACKEND_UNSUPPORTED: {storage_backend}")


def read_artifact_directory_preview(
    cfg: RemoteRunnerConfig,
    record: dict[str, Any],
    *,
    max_entries: int = 200,
) -> dict[str, Any]:
    storage_backend = str(record.get("storageBackend") or record.get("storage_backend") or "local")
    if storage_backend == "s3":
        return directory_package_preview(read_artifact_bytes(cfg, record), max_entries=max_entries)
    path = artifact_local_path(record)
    if not path.is_dir():
        raise ValueError("ARTIFACT_DIRECTORY_PREVIEW_PATH_INVALID")
    entries = []
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix()
        if child.is_dir():
            entries.append({"path": relative, "kind": "directory", "sizeBytes": 0, "sha256": ""})
        elif child.is_file():
            size, sha256 = _file_payload_stats(child)
            entries.append({"path": relative, "kind": "file", "sizeBytes": size, "sha256": sha256})
    size_bytes, sha256 = artifact_payload_stats(path)
    return {
        "kind": "directory",
        "packageProfile": "local-directory",
        "schemaVersion": "h2ometa.local-directory-preview.v1",
        "fileCount": sum(1 for item in entries if item["kind"] == "file"),
        "directoryCount": sum(1 for item in entries if item["kind"] == "directory"),
        "logicalSizeBytes": size_bytes,
        "logicalSha256": sha256,
        "entries": entries[:max_entries],
        "truncated": len(entries) > max_entries,
    }


def artifact_record_stats(cfg: RemoteRunnerConfig, record: dict[str, Any]) -> tuple[int, str]:
    storage_backend = str(record.get("storageBackend") or record.get("storage_backend") or "local")
    if storage_backend == "local":
        return artifact_payload_stats(artifact_local_path(record))
    if storage_backend == "s3":
        payload = _read_s3_artifact_bytes(cfg, record)
        if _artifact_is_directory(record) or _s3_object_is_directory_package(cfg, record):
            _assert_s3_package_checksum(cfg, record, payload)
            return directory_package_stats(payload)
        return len(payload), hashlib.sha256(payload).hexdigest()
    raise ValueError(f"ARTIFACT_STORAGE_BACKEND_UNSUPPORTED: {storage_backend}")


def artifact_record_exists(cfg: RemoteRunnerConfig, record: dict[str, Any]) -> bool:
    storage_backend = str(record.get("storageBackend") or record.get("storage_backend") or "local")
    if storage_backend == "local":
        try:
            return artifact_local_path(record).exists()
        except ValueError:
            return False
    if storage_backend == "s3":
        bucket, object_name = _parse_s3_uri(record)
        _stat_s3_object(cfg, bucket, object_name)
        return True
    raise ValueError(f"ARTIFACT_STORAGE_BACKEND_UNSUPPORTED: {storage_backend}")


def delete_artifact_payload(cfg: RemoteRunnerConfig, record: dict[str, Any]) -> dict[str, Any]:
    storage_backend = str(record.get("storageBackend") or record.get("storage_backend") or "local")
    storage_uri = str(record.get("storageUri") or record.get("storage_uri") or "").strip()
    if storage_backend == "local":
        path = artifact_local_path(record).resolve()
        if path.is_dir():
            raise ValueError("ARTIFACT_GC_DIRECTORY_UNSUPPORTED")
        if not path.exists():
            return {
                "deleted": False,
                "storageBackend": "local",
                "storageUri": storage_uri or path.as_uri(),
            }
        if not path.is_file():
            raise ValueError("ARTIFACT_GC_LOCAL_PATH_UNSUPPORTED")
        path.unlink()
        return {
            "deleted": True,
            "storageBackend": "local",
            "storageUri": storage_uri or path.as_uri(),
        }
    if storage_backend == "s3":
        bucket, object_name = _parse_s3_uri(record)
        _assert_managed_s3_object(cfg, bucket, object_name)
        _remove_s3_object(cfg, bucket, object_name)
        return {
            "deleted": True,
            "storageBackend": "s3",
            "storageUri": f"s3://{bucket}/{object_name}",
        }
    raise ValueError(f"ARTIFACT_STORAGE_BACKEND_UNSUPPORTED: {storage_backend}")


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


def _persist_s3_artifact(
    cfg: RemoteRunnerConfig,
    *,
    path: Path,
    run_id: str,
    artifact_id: str,
    sha256: str,
    size_bytes: int,
    mime_type: str,
) -> dict[str, str]:
    artifact_path = Path(path)
    package_info: dict[str, Any] = {}
    upload_path = artifact_path
    content_type = str(mime_type or "application/octet-stream")
    if artifact_path.is_dir():
        with tempfile.TemporaryDirectory(prefix="h2ometa-artifact-dir-") as temp_dir:
            package_path = Path(temp_dir) / f"{artifact_id}.zip"
            package_info = create_directory_artifact_package(
                artifact_path,
                package_path,
                logical_sha256=sha256,
                logical_size_bytes=size_bytes,
            )
            return _upload_s3_artifact_object(
                cfg,
                path=package_path,
                bucket=_required_s3_value(cfg.artifact_s3_bucket, "ARTIFACT_S3_BUCKET_REQUIRED"),
                object_name=_artifact_s3_object_name(cfg, sha256=sha256),
                artifact_id=artifact_id,
                run_id=run_id,
                sha256=sha256,
                size_bytes=size_bytes,
                content_type="application/zip",
                package_info=package_info,
            )
    if not artifact_path.is_file():
        raise ValueError("OUTPUT_ARTIFACT_PATH_INVALID")
    bucket = _required_s3_value(cfg.artifact_s3_bucket, "ARTIFACT_S3_BUCKET_REQUIRED")
    object_name = _artifact_s3_object_name(cfg, sha256=sha256)
    return _upload_s3_artifact_object(
        cfg,
        path=upload_path,
        bucket=bucket,
        object_name=object_name,
        artifact_id=artifact_id,
        run_id=run_id,
        sha256=sha256,
        size_bytes=size_bytes,
        content_type=content_type,
        package_info=package_info,
    )


def _upload_s3_artifact_object(
    cfg: RemoteRunnerConfig,
    *,
    path: Path,
    bucket: str,
    object_name: str,
    artifact_id: str,
    run_id: str,
    sha256: str,
    size_bytes: int,
    content_type: str,
    package_info: dict[str, Any],
) -> dict[str, str]:
    metadata = {
        "X-Amz-Meta-H2OMeta-Artifact-Id": str(artifact_id),
        "X-Amz-Meta-H2OMeta-Run-Id": str(run_id),
        "X-Amz-Meta-H2OMeta-Sha256": str(sha256),
        "X-Amz-Meta-H2OMeta-Size-Bytes": str(int(size_bytes)),
    }
    if package_info:
        metadata.update(
            {
                "X-Amz-Meta-H2OMeta-Package-Type": DIRECTORY_PACKAGE_SCHEMA_VERSION,
                "X-Amz-Meta-H2OMeta-Package-Sha256": str(package_info["packageSha256"]),
                "X-Amz-Meta-H2OMeta-Package-Size-Bytes": str(int(package_info["packageSizeBytes"])),
            }
        )
    _build_s3_client(cfg).fput_object(
        bucket,
        object_name,
        str(path),
        content_type=content_type,
        metadata=metadata,
    )
    return {
        "storageBackend": "s3",
        "storageUri": f"s3://{bucket}/{object_name}",
        "localPath": "",
    }


def _read_s3_artifact_bytes(
    cfg: RemoteRunnerConfig,
    record: dict[str, Any],
    *,
    limit: int | None = None,
) -> bytes:
    bucket, object_name = _parse_s3_uri(record)
    response = _get_s3_object(cfg, bucket, object_name)
    try:
        if limit is not None:
            return response.read(limit)
        chunks: list[bytes] = []
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
        release = getattr(response, "release_conn", None)
        if callable(release):
            release()


def _stat_s3_object(cfg: RemoteRunnerConfig, bucket: str, object_name: str) -> Any:
    try:
        return _build_s3_client(cfg).stat_object(bucket, object_name)
    except Exception as exc:
        raise ValueError(f"ARTIFACT_S3_OBJECT_UNAVAILABLE: {exc.__class__.__name__}") from exc


def _get_s3_object(cfg: RemoteRunnerConfig, bucket: str, object_name: str) -> Any:
    try:
        return _build_s3_client(cfg).get_object(bucket, object_name)
    except Exception as exc:
        raise ValueError(f"ARTIFACT_S3_READ_FAILED: {exc.__class__.__name__}") from exc


def _remove_s3_object(cfg: RemoteRunnerConfig, bucket: str, object_name: str) -> None:
    try:
        _build_s3_client(cfg).remove_object(bucket, object_name)
    except Exception as exc:
        raise ValueError(f"ARTIFACT_S3_DELETE_FAILED: {exc.__class__.__name__}") from exc


def _assert_managed_s3_object(cfg: RemoteRunnerConfig, bucket: str, object_name: str) -> None:
    expected_bucket = str(cfg.artifact_s3_bucket or "").strip()
    if expected_bucket and bucket != expected_bucket:
        raise ValueError("ARTIFACT_S3_BUCKET_MISMATCH")
    prefix = _normalized_s3_prefix(cfg.artifact_s3_prefix)
    managed_prefix = f"{prefix}/artifacts/sha256/" if prefix else "artifacts/sha256/"
    if not object_name.startswith(managed_prefix):
        raise ValueError("ARTIFACT_S3_PREFIX_UNMANAGED")


def _artifact_s3_object_name(cfg: RemoteRunnerConfig, *, sha256: str) -> str:
    prefix = _normalized_s3_prefix(cfg.artifact_s3_prefix)
    key = f"artifacts/sha256/{sha256[:2]}/{sha256}"
    return f"{prefix}/{key}" if prefix else key


def _normalized_s3_prefix(value: str) -> str:
    return str(value or "").strip().strip("/")


def _parse_s3_uri(record: dict[str, Any]) -> tuple[str, str]:
    storage_uri = str(record.get("storageUri") or record.get("storage_uri") or "").strip()
    parsed = urlparse(storage_uri)
    if parsed.scheme != "s3":
        raise ValueError(f"ARTIFACT_STORAGE_URI_UNSUPPORTED: {parsed.scheme or 'missing'}")
    bucket = str(parsed.netloc or "").strip()
    object_name = unquote(str(parsed.path or "").lstrip("/"))
    if not bucket or not object_name:
        raise ValueError("ARTIFACT_STORAGE_URI_REQUIRED")
    return bucket, object_name


def _artifact_filename(record: dict[str, Any]) -> str:
    local_path = str(record.get("path") or record.get("localPath") or "").strip()
    if local_path:
        name = Path(local_path).name
        if name:
            return name
    _, object_name = _parse_s3_uri(record)
    return PurePosixPath(object_name).name or "artifact"


def _artifact_is_directory(record: dict[str, Any]) -> bool:
    mime_type = str(record.get("mimeType") or record.get("mime_type") or "").strip()
    kind = str(record.get("kind") or "").strip().lower()
    return mime_type == "inode/directory" or kind == "directory" or bool(record.get("directory"))


def _assert_s3_package_checksum(cfg: RemoteRunnerConfig, record: dict[str, Any], payload: bytes) -> None:
    expected = _s3_package_metadata(cfg, record).get("packageSha256", "")
    if expected and hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("ARTIFACT_S3_PACKAGE_SHA256_MISMATCH")


def _s3_object_is_directory_package(cfg: RemoteRunnerConfig, record: dict[str, Any]) -> bool:
    return _s3_package_metadata(cfg, record).get("packageType") == DIRECTORY_PACKAGE_SCHEMA_VERSION


def _s3_package_metadata(cfg: RemoteRunnerConfig, record: dict[str, Any]) -> dict[str, str]:
    bucket, object_name = _parse_s3_uri(record)
    metadata = dict(getattr(_stat_s3_object(cfg, bucket, object_name), "metadata", {}) or {})
    return {
        "packageType": str(
            metadata.get("X-Amz-Meta-H2OMeta-Package-Type")
            or metadata.get("x-amz-meta-h2ometa-package-type")
            or ""
        ).strip(),
        "packageSha256": str(
            metadata.get("X-Amz-Meta-H2OMeta-Package-Sha256")
            or metadata.get("x-amz-meta-h2ometa-package-sha256")
            or ""
        ).strip(),
    }


def _build_s3_client(cfg: RemoteRunnerConfig):
    try:
        from minio import Minio
    except ImportError as exc:
        raise RuntimeError("ARTIFACT_S3_CLIENT_UNAVAILABLE") from exc
    endpoint = _required_s3_value(cfg.artifact_s3_endpoint, "ARTIFACT_S3_ENDPOINT_REQUIRED")
    access_key = _required_s3_value(cfg.artifact_s3_access_key, "ARTIFACT_S3_ACCESS_KEY_REQUIRED")
    secret_key = _required_s3_value(cfg.artifact_s3_secret_key, "ARTIFACT_S3_SECRET_KEY_REQUIRED")
    region = str(cfg.artifact_s3_region or "").strip() or None
    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=bool(cfg.artifact_s3_secure),
        region=region,
    )


def _required_s3_value(value: object, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized
