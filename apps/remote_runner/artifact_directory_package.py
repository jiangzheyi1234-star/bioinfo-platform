from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile
from typing import Any


DIRECTORY_PACKAGE_SCHEMA_VERSION = "h2ometa.directory-artifact-package.v1"
DIRECTORY_PACKAGE_PROFILE = "bagit-directory-artifact.v1"
DIRECTORY_PACKAGE_MANIFEST = "h2ometa-directory-manifest.json"
DIRECTORY_PACKAGE_BAGIT = "bagit.txt"
DIRECTORY_PACKAGE_PAYLOAD_MANIFEST = "manifest-sha256.txt"
DIRECTORY_PACKAGE_DATA_PREFIX = "data/"


def create_directory_artifact_package(
    source_dir: Path,
    package_path: Path,
    *,
    logical_sha256: str,
    logical_size_bytes: int,
) -> dict[str, Any]:
    source = Path(source_dir)
    if not source.is_dir():
        raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_SOURCE_REQUIRED")
    manifest = _directory_manifest(
        source,
        logical_sha256=logical_sha256,
        logical_size_bytes=logical_size_bytes,
    )
    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_zip_bytes(archive, DIRECTORY_PACKAGE_BAGIT, b"BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n")
        _write_zip_bytes(archive, DIRECTORY_PACKAGE_PAYLOAD_MANIFEST, _bagit_payload_manifest_bytes(manifest))
        _write_zip_bytes(archive, DIRECTORY_PACKAGE_MANIFEST, _json_bytes(manifest))
        for directory in manifest["directories"]:
            _write_zip_directory(archive, f"{DIRECTORY_PACKAGE_DATA_PREFIX}{directory['path']}/")
        for item in manifest["files"]:
            _write_zip_bytes(archive, f"{DIRECTORY_PACKAGE_DATA_PREFIX}{item['path']}", source.joinpath(item["path"]).read_bytes())
    package_size, package_sha = _file_stats(package_path)
    return {
        "schemaVersion": DIRECTORY_PACKAGE_SCHEMA_VERSION,
        "packageProfile": DIRECTORY_PACKAGE_PROFILE,
        "packageSizeBytes": package_size,
        "packageSha256": package_sha,
        "logicalSizeBytes": int(manifest["logicalSizeBytes"]),
        "logicalSha256": str(manifest["logicalSha256"]),
        "fileCount": len(manifest["files"]),
        "directoryCount": len(manifest["directories"]),
    }


def directory_package_stats(payload: bytes) -> tuple[int, str]:
    manifest, _files = _validated_directory_package(payload, include_payloads=False)
    return int(manifest["logicalSizeBytes"]), str(manifest["logicalSha256"])


def iter_directory_package_payloads(payload: bytes):
    manifest, files = _validated_directory_package(payload, include_payloads=True)
    for item in manifest["files"]:
        yield str(item["path"]), files[str(item["path"])]


def directory_package_preview(payload: bytes, *, max_entries: int = 200) -> dict[str, Any]:
    manifest, _files = _validated_directory_package(payload, include_payloads=False)
    files = list(manifest["files"])
    directories = list(manifest["directories"])
    entries = [
        {"path": str(item["path"]), "kind": "directory", "sizeBytes": 0, "sha256": ""}
        for item in directories
    ]
    entries.extend(
        {
            "path": str(item["path"]),
            "kind": "file",
            "sizeBytes": int(item["sizeBytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in files
    )
    entries.sort(key=lambda item: (str(item["path"]), str(item["kind"])))
    return {
        "kind": "directory",
        "packageProfile": str(manifest["packageProfile"]),
        "schemaVersion": str(manifest["schemaVersion"]),
        "fileCount": len(files),
        "directoryCount": len(directories),
        "logicalSizeBytes": int(manifest["logicalSizeBytes"]),
        "logicalSha256": str(manifest["logicalSha256"]),
        "entries": entries[:max_entries],
        "truncated": len(entries) > max_entries,
    }


def _directory_manifest(
    source: Path,
    *,
    logical_sha256: str,
    logical_size_bytes: int,
) -> dict[str, Any]:
    directories: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for child in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
        relative = _safe_relative_path(child.relative_to(source).as_posix())
        if child.is_dir():
            directories.append({"path": relative})
        elif child.is_file():
            size, sha = _file_stats(child)
            files.append({"path": relative, "sizeBytes": size, "sha256": sha})
    return {
        "schemaVersion": DIRECTORY_PACKAGE_SCHEMA_VERSION,
        "packageProfile": DIRECTORY_PACKAGE_PROFILE,
        "logicalSizeBytes": int(logical_size_bytes),
        "logicalSha256": str(logical_sha256),
        "bagIt": {
            "version": "1.0",
            "payloadManifest": DIRECTORY_PACKAGE_PAYLOAD_MANIFEST,
            "payloadDirectory": "data",
        },
        "directories": directories,
        "files": files,
    }


def _validated_directory_package(payload: bytes, *, include_payloads: bool) -> tuple[dict[str, Any], dict[str, bytes]]:
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        if DIRECTORY_PACKAGE_BAGIT not in names:
            raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_BAGIT_MISSING")
        if DIRECTORY_PACKAGE_PAYLOAD_MANIFEST not in names:
            raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_PAYLOAD_MANIFEST_MISSING")
        if DIRECTORY_PACKAGE_MANIFEST not in names:
            raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_MANIFEST_MISSING")
        manifest = json.loads(archive.read(DIRECTORY_PACKAGE_MANIFEST).decode("utf-8"))
        _validate_manifest_shape(manifest)
        for directory in manifest["directories"]:
            directory_path = _safe_relative_path(str(directory["path"]))
            if f"{DIRECTORY_PACKAGE_DATA_PREFIX}{directory_path}/" not in names:
                raise ValueError(f"ARTIFACT_DIRECTORY_PACKAGE_DIRECTORY_MISSING: {directory_path}")
        logical_digest = hashlib.sha256()
        logical_size = 0
        for entry in _logical_entries(manifest):
            if entry["kind"] == "directory":
                logical_digest.update(f"D\t{entry['path']}\0".encode("utf-8"))
                continue
            path = str(entry["path"])
            data_name = f"{DIRECTORY_PACKAGE_DATA_PREFIX}{path}"
            if data_name not in names:
                raise ValueError(f"ARTIFACT_DIRECTORY_PACKAGE_FILE_MISSING: {path}")
            payload_bytes = archive.read(data_name)
            expected_size = int(entry["sizeBytes"])
            expected_sha = str(entry["sha256"])
            actual_sha = hashlib.sha256(payload_bytes).hexdigest()
            if len(payload_bytes) != expected_size:
                raise ValueError(f"ARTIFACT_DIRECTORY_PACKAGE_FILE_SIZE_MISMATCH: {path}")
            if actual_sha != expected_sha:
                raise ValueError(f"ARTIFACT_DIRECTORY_PACKAGE_FILE_SHA256_MISMATCH: {path}")
            logical_digest.update(f"F\t{path}\0".encode("utf-8"))
            logical_digest.update(payload_bytes)
            logical_size += len(payload_bytes)
            if include_payloads:
                files[path] = payload_bytes
        if logical_size != int(manifest["logicalSizeBytes"]):
            raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_LOGICAL_SIZE_MISMATCH")
        if logical_digest.hexdigest() != str(manifest["logicalSha256"]):
            raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_LOGICAL_SHA256_MISMATCH")
        _validate_bagit_payload_manifest(archive.read(DIRECTORY_PACKAGE_PAYLOAD_MANIFEST), manifest)
    return manifest, files


def _validate_manifest_shape(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_MANIFEST_INVALID")
    if manifest.get("schemaVersion") != DIRECTORY_PACKAGE_SCHEMA_VERSION:
        raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_SCHEMA_UNSUPPORTED")
    if manifest.get("packageProfile") != DIRECTORY_PACKAGE_PROFILE:
        raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_PROFILE_UNSUPPORTED")
    for key in ("directories", "files"):
        if not isinstance(manifest.get(key), list):
            raise ValueError(f"ARTIFACT_DIRECTORY_PACKAGE_{key.upper()}_INVALID")
    seen: set[str] = set()
    for directory in manifest["directories"]:
        path = _safe_relative_path(str(directory.get("path") if isinstance(directory, dict) else ""))
        if path in seen:
            raise ValueError(f"ARTIFACT_DIRECTORY_PACKAGE_DUPLICATE_PATH: {path}")
        seen.add(path)
        directory["path"] = path
    for item in manifest["files"]:
        if not isinstance(item, dict):
            raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_FILE_INVALID")
        path = _safe_relative_path(str(item.get("path") or ""))
        if path in seen:
            raise ValueError(f"ARTIFACT_DIRECTORY_PACKAGE_DUPLICATE_PATH: {path}")
        seen.add(path)
        item["path"] = path
        item["sizeBytes"] = int(item.get("sizeBytes") or 0)
        item["sha256"] = _required_sha256(str(item.get("sha256") or ""))
    manifest["logicalSizeBytes"] = int(manifest.get("logicalSizeBytes") or 0)
    manifest["logicalSha256"] = _required_sha256(str(manifest.get("logicalSha256") or ""))


def _validate_bagit_payload_manifest(payload: bytes, manifest: dict[str, Any]) -> None:
    expected = _bagit_payload_manifest_bytes(manifest).decode("utf-8").splitlines()
    actual = payload.decode("utf-8").splitlines()
    if actual != expected:
        raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_BAGIT_MANIFEST_MISMATCH")


def _logical_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    entries = [{"kind": "directory", **item} for item in manifest["directories"]]
    entries.extend({"kind": "file", **item} for item in manifest["files"])
    return sorted(entries, key=lambda item: str(item["path"]))


def _bagit_payload_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    lines = [
        f"{item['sha256']} {DIRECTORY_PACKAGE_DATA_PREFIX}{item['path']}"
        for item in sorted(manifest["files"], key=lambda value: str(value["path"]))
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def _safe_relative_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip("/")
    if not raw or "\n" in raw or "\r" in raw or "\0" in raw:
        raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_PATH_UNSUPPORTED")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_PATH_UNSUPPORTED")
    return path.as_posix()


def _required_sha256(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError("ARTIFACT_DIRECTORY_PACKAGE_SHA256_INVALID")
    return normalized


def _write_zip_bytes(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, payload)


def _write_zip_directory(archive: zipfile.ZipFile, name: str) -> None:
    info = zipfile.ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.external_attr = 0o40755 << 16
    archive.writestr(info, b"")


def _file_stats(path: Path) -> tuple[int, str]:
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
