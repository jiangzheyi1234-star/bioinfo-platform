from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import RemoteRunnerConfig
from .result_package_storage import fetch_result_package_export


RESULT_PACKAGE_DOWNLOAD_MEDIA_TYPE = "application/zip"


def result_package_download_url(result_id: str, package_export_id: str) -> str:
    return (
        f"/api/v1/results/{quote(str(result_id), safe='')}/exports/"
        f"{quote(str(package_export_id), safe='')}/download"
    )


def build_result_package_download(
    cfg: RemoteRunnerConfig,
    *,
    result_id: str,
    package_export_id: str,
) -> dict[str, Any]:
    record = fetch_result_package_export(
        cfg,
        package_export_id=package_export_id,
    )
    if record is None:
        raise ValueError("RESULT_PACKAGE_EXPORT_NOT_FOUND")
    if record["resultId"] != str(result_id or "").strip():
        raise ValueError("RESULT_PACKAGE_EXPORT_RESULT_MISMATCH")
    if record["lifecycleState"] != "active":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_NOT_ACTIVE: {record['lifecycleState']}")

    package_path = Path(str(record["packagePath"] or "")).resolve()
    managed_root = (Path(cfg.results_dir) / "packages").resolve()
    if not _is_relative_to(package_path, managed_root):
        raise ValueError("RESULT_PACKAGE_PATH_UNMANAGED")
    if not package_path.is_file():
        raise ValueError("RESULT_PACKAGE_FILE_MISSING")

    size_bytes = package_path.stat().st_size
    if size_bytes != int(record["sizeBytes"]):
        raise ValueError("RESULT_PACKAGE_SIZE_MISMATCH")
    sha256 = _file_sha256(package_path)
    if sha256 != record["sha256"]:
        raise ValueError("RESULT_PACKAGE_CHECKSUM_MISMATCH")

    filename = package_path.name
    return {
        "schemaVersion": "h2ometa.result-package-download.v1",
        "resultId": record["resultId"],
        "runId": record["runId"],
        "packageExportId": record["packageExportId"],
        "workflowRevisionId": record["workflowRevisionId"],
        "path": package_path,
        "filename": filename,
        "mediaType": RESULT_PACKAGE_DOWNLOAD_MEDIA_TYPE,
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "manifestSha256": record["manifestSha256"],
        "artifactPayloadMode": record["artifactPayloadMode"],
        "headers": _download_headers(record, filename),
    }


def _download_headers(record: dict[str, Any], filename: str) -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
        "X-H2OMeta-Result-Id": record["resultId"],
        "X-H2OMeta-Package-Export-Id": record["packageExportId"],
        "X-H2OMeta-Sha256": record["sha256"],
        "X-H2OMeta-Manifest-Sha256": record["manifestSha256"],
        "X-H2OMeta-Artifact-Payload-Mode": record["artifactPayloadMode"],
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
