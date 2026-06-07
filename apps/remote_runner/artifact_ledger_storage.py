"""Content-addressed artifact blob and lineage storage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid
from typing import Any

from .artifact_storage import artifact_payload_stats
from .config import RemoteRunnerConfig
from .storage_core import get_connection, now_iso


def record_artifact_blob_for_path(
    cfg: RemoteRunnerConfig,
    *,
    path: Path,
    media_type: str,
    blake3: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    artifact_path = Path(path)
    size_bytes, sha256 = artifact_payload_stats(artifact_path)
    blob_id = f"ablob_{sha256[:24]}"
    timestamp = _optional_text(created_at) or now_iso()
    normalized_media_type = _required_text(media_type, "ARTIFACT_MEDIA_TYPE_REQUIRED")
    normalized_blake3 = _optional_text(blake3)

    with get_connection(cfg) as connection:
        existing = connection.execute(
            "SELECT * FROM artifact_blobs WHERE sha256 = ?",
            (sha256,),
        ).fetchone()
        if existing is not None:
            return {**_blob_row_to_dict(existing), "created": False}
        connection.execute(
            """
            INSERT INTO artifact_blobs (
                artifact_blob_id, sha256, blake3, size_bytes, media_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (blob_id, sha256, normalized_blake3, size_bytes, normalized_media_type, timestamp),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM artifact_blobs WHERE artifact_blob_id = ?",
            (blob_id,),
        ).fetchone()
    return {**_blob_row_to_dict(row), "created": True}


def record_artifact_materialization(
    cfg: RemoteRunnerConfig,
    *,
    artifact_blob_id: str,
    storage_backend: str,
    storage_uri: str,
    local_path: Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    normalized_blob_id = _required_text(artifact_blob_id, "ARTIFACT_BLOB_ID_REQUIRED")
    normalized_backend = _required_text(storage_backend, "ARTIFACT_STORAGE_BACKEND_REQUIRED")
    normalized_uri = _required_text(storage_uri, "ARTIFACT_STORAGE_URI_REQUIRED")
    normalized_local_path = str(local_path) if local_path is not None else None
    timestamp = _optional_text(created_at) or now_iso()

    with get_connection(cfg) as connection:
        _require_blob(connection, normalized_blob_id)
        existing = connection.execute(
            """
            SELECT * FROM artifact_materializations
            WHERE artifact_blob_id = ? AND storage_backend = ? AND storage_uri = ?
            """,
            (normalized_blob_id, normalized_backend, normalized_uri),
        ).fetchone()
        if existing is not None:
            return {**_materialization_row_to_dict(existing), "created": False}
        materialization_id = f"amat_{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO artifact_materializations (
                materialization_id, artifact_blob_id, storage_backend,
                storage_uri, local_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                materialization_id,
                normalized_blob_id,
                normalized_backend,
                normalized_uri,
                normalized_local_path,
                timestamp,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM artifact_materializations WHERE materialization_id = ?",
            (materialization_id,),
        ).fetchone()
    return {**_materialization_row_to_dict(row), "created": True}


def list_artifact_materializations(cfg: RemoteRunnerConfig, artifact_blob_id: str) -> list[dict[str, Any]]:
    normalized_blob_id = _required_text(artifact_blob_id, "ARTIFACT_BLOB_ID_REQUIRED")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT * FROM artifact_materializations
            WHERE artifact_blob_id = ?
            ORDER BY created_at ASC, materialization_id ASC
            """,
            (normalized_blob_id,),
        ).fetchall()
    return [_materialization_row_to_dict(row) for row in rows]


def record_run_artifact_edge(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    artifact_blob_id: str,
    role: str,
    port_name: str | None = None,
    step_id: str | None = None,
    content_hash: str | None = None,
    upstream_run_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_blob_id = _required_text(artifact_blob_id, "ARTIFACT_BLOB_ID_REQUIRED")
    normalized_role = _required_text(role, "ARTIFACT_EDGE_ROLE_REQUIRED")
    timestamp = _optional_text(created_at) or now_iso()

    with get_connection(cfg) as connection:
        blob = _require_blob(connection, normalized_blob_id)
        edge_id = f"aredge_{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO run_artifact_edges (
                edge_id, run_id, artifact_blob_id, role, port_name, step_id,
                content_hash, upstream_run_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge_id,
                normalized_run_id,
                normalized_blob_id,
                normalized_role,
                _optional_text(port_name),
                _optional_text(step_id),
                _optional_text(content_hash) or blob["sha256"],
                _optional_text(upstream_run_id),
                timestamp,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM run_artifact_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
    return _edge_row_to_dict(row)


def list_run_artifact_edges(cfg: RemoteRunnerConfig, run_id: str) -> list[dict[str, Any]]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT * FROM run_artifact_edges
            WHERE run_id = ?
            ORDER BY created_at ASC, edge_id ASC
            """,
            (normalized_run_id,),
        ).fetchall()
    return [_edge_row_to_dict(row) for row in rows]


def record_lineage_edge(
    cfg: RemoteRunnerConfig,
    *,
    subject_kind: str,
    subject_id: str,
    predicate: str,
    object_kind: str,
    object_id: str,
    run_id: str | None = None,
    attempt_id: str | None = None,
    workflow_revision_id: str | None = None,
    evidence_event_id: str | None = None,
    payload: dict[str, Any] | None = None,
    content_hash: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    normalized_payload = payload if isinstance(payload, dict) else {}
    normalized = {
        "subject_kind": _required_text(subject_kind, "LINEAGE_SUBJECT_KIND_REQUIRED"),
        "subject_id": _required_text(subject_id, "LINEAGE_SUBJECT_ID_REQUIRED"),
        "predicate": _required_text(predicate, "LINEAGE_PREDICATE_REQUIRED"),
        "object_kind": _required_text(object_kind, "LINEAGE_OBJECT_KIND_REQUIRED"),
        "object_id": _required_text(object_id, "LINEAGE_OBJECT_ID_REQUIRED"),
        "run_id": _optional_text(run_id),
        "attempt_id": _optional_text(attempt_id),
        "workflow_revision_id": _optional_text(workflow_revision_id),
        "evidence_event_id": _optional_text(evidence_event_id),
        "payload_json": _stable_json(normalized_payload),
        "content_hash": _optional_text(content_hash) or _lineage_content_hash(
            subject_kind=subject_kind,
            subject_id=subject_id,
            predicate=predicate,
            object_kind=object_kind,
            object_id=object_id,
            payload=normalized_payload,
        ),
        "created_at": _optional_text(created_at) or now_iso(),
    }
    lineage_edge_id = f"lin_{uuid.uuid4().hex[:12]}"

    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO lineage_edges (
                lineage_edge_id, subject_kind, subject_id, predicate, object_kind, object_id,
                run_id, attempt_id, workflow_revision_id, evidence_event_id,
                payload_json, content_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lineage_edge_id,
                normalized["subject_kind"],
                normalized["subject_id"],
                normalized["predicate"],
                normalized["object_kind"],
                normalized["object_id"],
                normalized["run_id"],
                normalized["attempt_id"],
                normalized["workflow_revision_id"],
                normalized["evidence_event_id"],
                normalized["payload_json"],
                normalized["content_hash"],
                normalized["created_at"],
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM lineage_edges WHERE lineage_edge_id = ?",
            (lineage_edge_id,),
        ).fetchone()
    return _lineage_edge_row_to_dict(row)


def list_lineage_edges_for_run(cfg: RemoteRunnerConfig, run_id: str) -> list[dict[str, Any]]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT * FROM lineage_edges
            WHERE run_id = ?
            ORDER BY created_at ASC, lineage_edge_id ASC
            """,
            (normalized_run_id,),
        ).fetchall()
    return [_lineage_edge_row_to_dict(row) for row in rows]


def _require_blob(connection, artifact_blob_id: str):
    row = connection.execute(
        "SELECT * FROM artifact_blobs WHERE artifact_blob_id = ?",
        (artifact_blob_id,),
    ).fetchone()
    if row is None:
        raise KeyError(artifact_blob_id)
    return row


def _blob_row_to_dict(row) -> dict[str, Any]:
    return {
        "artifactBlobId": row["artifact_blob_id"],
        "sha256": row["sha256"],
        "blake3": row["blake3"],
        "sizeBytes": int(row["size_bytes"]),
        "mediaType": row["media_type"],
        "createdAt": row["created_at"],
    }


def _materialization_row_to_dict(row) -> dict[str, Any]:
    return {
        "materializationId": row["materialization_id"],
        "artifactBlobId": row["artifact_blob_id"],
        "storageBackend": row["storage_backend"],
        "storageUri": row["storage_uri"],
        "localPath": row["local_path"],
        "createdAt": row["created_at"],
    }


def _edge_row_to_dict(row) -> dict[str, Any]:
    return {
        "edgeId": row["edge_id"],
        "runId": row["run_id"],
        "artifactBlobId": row["artifact_blob_id"],
        "role": row["role"],
        "portName": row["port_name"],
        "stepId": row["step_id"],
        "contentHash": row["content_hash"],
        "upstreamRunId": row["upstream_run_id"],
        "createdAt": row["created_at"],
    }


def _lineage_edge_row_to_dict(row) -> dict[str, Any]:
    return {
        "lineageEdgeId": row["lineage_edge_id"],
        "subjectKind": row["subject_kind"],
        "subjectId": row["subject_id"],
        "predicate": row["predicate"],
        "objectKind": row["object_kind"],
        "objectId": row["object_id"],
        "runId": row["run_id"],
        "attemptId": row["attempt_id"],
        "workflowRevisionId": row["workflow_revision_id"],
        "evidenceEventId": row["evidence_event_id"],
        "payload": json.loads(row["payload_json"]),
        "contentHash": row["content_hash"],
        "createdAt": row["created_at"],
    }


def _lineage_content_hash(
    *,
    subject_kind: str,
    subject_id: str,
    predicate: str,
    object_kind: str,
    object_id: str,
    payload: dict[str, Any],
) -> str:
    return hashlib.sha256(
        _stable_json(
            {
                "subjectKind": subject_kind,
                "subjectId": subject_id,
                "predicate": predicate,
                "objectKind": object_kind,
                "objectId": object_id,
                "payload": payload,
            }
        ).encode("utf-8")
    ).hexdigest()


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required_text(value: object, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
