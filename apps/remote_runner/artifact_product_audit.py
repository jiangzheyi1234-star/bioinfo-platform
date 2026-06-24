from __future__ import annotations

from typing import Any

from .artifact_io import artifact_record_exists, artifact_record_stats, assert_managed_artifact_storage
from .config import RemoteRunnerConfig


def audit_artifact(
    cfg: RemoteRunnerConfig,
    artifact: dict[str, Any],
    *,
    verify_payload: bool,
) -> dict[str, Any]:
    expected_size = int(artifact.get("sizeBytes") or 0)
    expected_sha = str(artifact.get("sha256") or "")
    lifecycle_state = str(artifact.get("lifecycleState") or "active")
    verification_mode = "payload-checksum" if verify_payload else "metadata-only"
    if lifecycle_state == "deleted":
        return {
            "artifactId": artifact["artifactId"],
            "path": str(artifact.get("path") or ""),
            "storageBackend": artifact["storageBackend"],
            "storageUri": artifact["storageUri"],
            "verificationMode": verification_mode,
            "exists": False,
            "expectedSizeBytes": expected_size,
            "actualSizeBytes": None,
            "expectedSha256": expected_sha,
            "actualSha256": None,
            "sizeOk": False,
            "checksumOk": False,
            "status": "deleted",
            "deletedAt": artifact.get("deletedAt"),
            "gcReason": str(artifact.get("gcReason") or ""),
        }
    missing_metadata = _missing_artifact_metadata(artifact)
    if missing_metadata:
        return {
            "artifactId": artifact.get("artifactId"),
            "path": str(artifact.get("path") or ""),
            "storageBackend": str(artifact.get("storageBackend") or ""),
            "storageUri": str(artifact.get("storageUri") or ""),
            "verificationMode": verification_mode,
            "exists": False,
            "expectedSizeBytes": expected_size,
            "actualSizeBytes": None,
            "expectedSha256": expected_sha,
            "actualSha256": None,
            "sizeOk": False if verify_payload else None,
            "checksumOk": False if verify_payload else None,
            "status": "failed",
            "error": f"RESULT_ARTIFACT_METADATA_INCOMPLETE: {', '.join(missing_metadata)}",
        }
    exists = False
    actual_size: int | None = None
    actual_sha: str | None = None
    error = ""
    try:
        assert_managed_artifact_storage(cfg, artifact)
        exists = artifact_record_exists(cfg, artifact)
        if verify_payload:
            actual_size, actual_sha = artifact_record_stats(cfg, artifact)
    except ValueError as exc:
        error = str(exc)
    if verify_payload:
        passed = exists and not error and actual_size == expected_size and actual_sha == expected_sha
        size_ok: bool | None = actual_size == expected_size
        checksum_ok: bool | None = actual_sha == expected_sha
    else:
        passed = exists and not error
        size_ok = None
        checksum_ok = None
    status = "passed" if passed else "failed"
    return {
        "artifactId": artifact["artifactId"],
        "path": str(artifact.get("path") or ""),
        "storageBackend": artifact["storageBackend"],
        "storageUri": artifact["storageUri"],
        "verificationMode": verification_mode,
        "exists": exists,
        "expectedSizeBytes": expected_size,
        "actualSizeBytes": actual_size,
        "expectedSha256": expected_sha,
        "actualSha256": actual_sha,
        "sizeOk": size_ok,
        "checksumOk": checksum_ok,
        "status": status,
        **({"error": error} if error else {}),
    }


def _missing_artifact_metadata(artifact: dict[str, Any]) -> list[str]:
    required = (
        "artifactId",
        "kind",
        "mimeType",
        "sizeBytes",
        "sha256",
        "storageBackend",
        "storageUri",
    )
    return [key for key in required if artifact.get(key) in (None, "")]
