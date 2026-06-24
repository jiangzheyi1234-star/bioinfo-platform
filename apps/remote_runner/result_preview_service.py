from __future__ import annotations

from typing import Any

from .artifact_io import (
    artifact_record_stats,
    assert_managed_artifact_storage,
    read_artifact_directory_preview,
    read_artifact_preview_text,
)
from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError
from .storage import fetch_result

MAX_PREVIEW_BYTES = 256 * 1024
MAX_PREVIEW_TABLE_ROWS = 200


def build_result_preview_data(
    cfg: RemoteRunnerConfig,
    result_id: str,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    result = fetch_result(cfg, result_id)
    artifact = _select_preview_artifact(result["artifacts"], artifact_id)
    _verify_preview_artifact_integrity(cfg, artifact)
    preview = _build_artifact_preview(cfg, artifact)
    return {
        "resultId": result_id,
        "artifactId": artifact["artifactId"],
        "artifact": artifact,
        "preview": preview,
    }


def _select_preview_artifact(artifacts: list[dict[str, Any]], artifact_id: str | None) -> dict[str, Any]:
    if artifact_id:
        selected = next((item for item in artifacts if item["artifactId"] == artifact_id), None)
    else:
        selected = artifacts[0] if artifacts else None
    if selected is None:
        raise RemoteRunnerNotFoundError("RESULT_NOT_FOUND")
    return selected


def _verify_preview_artifact_integrity(cfg: RemoteRunnerConfig, artifact: dict[str, Any]) -> None:
    lifecycle_state = str(artifact.get("lifecycleState") or "active")
    if lifecycle_state != "active":
        raise ValueError("RESULT_ARTIFACT_NOT_ACTIVE")
    missing = _missing_preview_metadata(artifact)
    if missing:
        raise ValueError(f"RESULT_ARTIFACT_METADATA_INCOMPLETE: {', '.join(missing)}")
    assert_managed_artifact_storage(cfg, artifact)
    expected_size = int(artifact["sizeBytes"])
    expected_sha = str(artifact["sha256"])
    try:
        actual_size, actual_sha = artifact_record_stats(cfg, artifact)
    except Exception as exc:  # noqa: BLE001 - preview must fail closed on storage/package verification errors.
        raise ValueError(f"RESULT_ARTIFACT_CHECKSUM_AUDIT_FAILED: {type(exc).__name__}") from exc
    if actual_size != expected_size or actual_sha != expected_sha:
        raise ValueError("RESULT_ARTIFACT_CHECKSUM_AUDIT_FAILED")


def _missing_preview_metadata(artifact: dict[str, Any]) -> list[str]:
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


def _build_artifact_preview(cfg: RemoteRunnerConfig, artifact: dict[str, Any]) -> dict[str, Any]:
    mime_type = artifact["mimeType"]
    if mime_type == "inode/directory":
        return read_artifact_directory_preview(cfg, artifact, max_entries=MAX_PREVIEW_TABLE_ROWS)
    if mime_type == "text/tab-separated-values":
        raw, truncated = _read_preview_text(cfg, artifact)
        rows = raw.splitlines()
        columns = rows[0].split("\t") if rows else []
        preview_rows = [row.split("\t") for row in rows[1 : 1 + MAX_PREVIEW_TABLE_ROWS]]
        return {
            "kind": "table",
            "columns": columns,
            "rows": preview_rows,
            "truncated": truncated or max(0, len(rows) - 1) > MAX_PREVIEW_TABLE_ROWS,
        }
    if mime_type.startswith("text/html"):
        content, truncated = _read_preview_text(cfg, artifact)
        return {"kind": "html", "content": content, "truncated": truncated}
    content, truncated = _read_preview_text(cfg, artifact)
    return {"kind": "text", "content": content, "truncated": truncated}


def _read_preview_text(
    cfg: RemoteRunnerConfig,
    artifact: dict[str, Any],
    *,
    limit: int = MAX_PREVIEW_BYTES,
) -> tuple[str, bool]:
    return read_artifact_preview_text(cfg, artifact, limit=limit)
