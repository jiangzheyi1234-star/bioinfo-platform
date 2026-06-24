from __future__ import annotations

import sqlite3
from typing import Any


_INPUT_SOURCE_KEYS = {
    "uploadId",
    "artifactId",
    "sourceArtifactId",
    "artifactBlobId",
    "materializationId",
    "sourceMaterializationId",
    "sourceType",
    "sourceId",
    "sourceStorageBackend",
    "inputStorageBackend",
    "path",
    "filename",
    "storageUri",
    "inputStorageUri",
    "sourceStorageUri",
    "upstreamRunId",
}


def normalize_cache_inputs(connection: sqlite3.Connection | None, value: Any) -> Any:
    if isinstance(value, list):
        return [normalize_cache_inputs(connection, item) for item in value if item not in (None, "", [], {})]
    if not isinstance(value, dict):
        return _normalize(value)

    upload_id = str(value.get("uploadId") or "").strip()
    artifact_id = str(value.get("artifactId") or value.get("sourceArtifactId") or "").strip()
    artifact_blob_id = str(value.get("artifactBlobId") or "").strip()
    materialization_id = str(value.get("materializationId") or value.get("sourceMaterializationId") or "").strip()
    normalized = {
        str(key): normalize_cache_inputs(connection, item)
        for key, item in sorted(value.items())
        if item not in (None, "", [], {}) and key not in _INPUT_SOURCE_KEYS
    }

    if upload_id and connection is not None:
        upload = connection.execute(
            "SELECT sha256, size_bytes, mime_type FROM uploads WHERE upload_id = ?",
            (upload_id,),
        ).fetchone()
        if upload is not None:
            normalized["content"] = _upload_content(upload)
            return normalized
    if upload_id:
        normalized["uploadId"] = upload_id

    if artifact_id or artifact_blob_id or materialization_id:
        if connection is None:
            raise ValueError("ARTIFACT_CACHE_INPUT_ARTIFACT_CONNECTION_REQUIRED")
        normalized["content"] = _artifact_input_content(
            connection,
            artifact_id=artifact_id,
            artifact_blob_id=artifact_blob_id,
            materialization_id=materialization_id,
        )
    return normalized


def _upload_content(upload: sqlite3.Row) -> dict[str, Any]:
    return {
        "sha256": str(upload["sha256"]),
        "sizeBytes": int(upload["size_bytes"]),
        "mimeType": str(upload["mime_type"]),
    }


def _artifact_input_content(
    connection: sqlite3.Connection,
    *,
    artifact_id: str,
    artifact_blob_id: str,
    materialization_id: str,
) -> dict[str, Any]:
    if artifact_id:
        artifact = connection.execute(
            """
            SELECT sha256, size_bytes, mime_type, lifecycle_state
            FROM artifacts
            WHERE artifact_id = ?
            """,
            (artifact_id,),
        ).fetchone()
        if artifact is None:
            raise ValueError("ARTIFACT_CACHE_INPUT_ARTIFACT_NOT_FOUND")
        if str(artifact["lifecycle_state"] or "") != "active":
            raise ValueError("ARTIFACT_CACHE_INPUT_ARTIFACT_NOT_ACTIVE")
        return {
            "sha256": str(artifact["sha256"]),
            "sizeBytes": int(artifact["size_bytes"]),
            "mimeType": str(artifact["mime_type"]),
        }

    if not artifact_blob_id or not materialization_id:
        raise ValueError("ARTIFACT_CACHE_INPUT_ARTIFACT_REF_REQUIRED")
    row = connection.execute(
        """
        SELECT blobs.sha256, blobs.size_bytes, blobs.media_type,
               materializations.lifecycle_state
        FROM artifact_materializations AS materializations
        JOIN artifact_blobs AS blobs
          ON blobs.artifact_blob_id = materializations.artifact_blob_id
        WHERE materializations.materialization_id = ?
          AND materializations.artifact_blob_id = ?
        """,
        (materialization_id, artifact_blob_id),
    ).fetchone()
    if row is None:
        raise ValueError("ARTIFACT_CACHE_INPUT_MATERIALIZATION_NOT_FOUND")
    if str(row["lifecycle_state"] or "") != "active":
        raise ValueError("ARTIFACT_CACHE_INPUT_MATERIALIZATION_NOT_ACTIVE")
    return {
        "sha256": str(row["sha256"]),
        "sizeBytes": int(row["size_bytes"]),
        "mimeType": str(row["media_type"]),
    }


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items()) if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_normalize(item) for item in value if item not in (None, "", [], {})]
    return value
