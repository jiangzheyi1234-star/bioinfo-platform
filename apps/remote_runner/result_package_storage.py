from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection


SUPPORTED_ARTIFACT_PAYLOAD_MODES = {"included", "metadata-only"}
SUPPORTED_RESULT_PACKAGE_LIFECYCLE_STATES = {"active", "retired"}
SUPPORTED_RESULT_PACKAGE_BYTE_STATES = {"available", "deleting", "deleted"}
RESULT_PACKAGE_EXPORT_ID_RE = re.compile(r"^rpexp_[0-9a-f]{16}$")


def record_result_package_export(
    cfg: RemoteRunnerConfig,
    *,
    result_id: str,
    run_id: str,
    workflow_revision_id: str,
    package_path: Path,
    package_uri: str,
    size_bytes: int,
    sha256: str,
    manifest_sha256: str,
    evidence_event_id: str,
    artifact_ids: list[str],
    include_artifacts: bool,
    artifact_payload_mode: str,
    created_at: str,
) -> dict[str, Any]:
    normalized, export_id = _normalize_result_package_export(
        result_id=result_id,
        run_id=run_id,
        workflow_revision_id=workflow_revision_id,
        package_path=package_path,
        package_uri=package_uri,
        size_bytes=size_bytes,
        sha256=sha256,
        manifest_sha256=manifest_sha256,
        evidence_event_id=evidence_event_id,
        artifact_ids=artifact_ids,
        include_artifacts=include_artifacts,
        artifact_payload_mode=artifact_payload_mode,
        created_at=created_at,
    )
    with get_connection(cfg) as connection:
        row = _record_normalized_result_package_export(connection, normalized=normalized, export_id=export_id)
        connection.commit()
    return row


def record_result_package_export_in_connection(
    connection: Any,
    *,
    result_id: str,
    run_id: str,
    workflow_revision_id: str,
    package_path: Path,
    package_uri: str,
    size_bytes: int,
    sha256: str,
    manifest_sha256: str,
    evidence_event_id: str,
    artifact_ids: list[str],
    include_artifacts: bool,
    artifact_payload_mode: str,
    created_at: str,
) -> dict[str, Any]:
    normalized, export_id = _normalize_result_package_export(
        result_id=result_id,
        run_id=run_id,
        workflow_revision_id=workflow_revision_id,
        package_path=package_path,
        package_uri=package_uri,
        size_bytes=size_bytes,
        sha256=sha256,
        manifest_sha256=manifest_sha256,
        evidence_event_id=evidence_event_id,
        artifact_ids=artifact_ids,
        include_artifacts=include_artifacts,
        artifact_payload_mode=artifact_payload_mode,
        created_at=created_at,
    )
    return _record_normalized_result_package_export(connection, normalized=normalized, export_id=export_id)


def _record_normalized_result_package_export(
    connection: Any,
    *,
    normalized: dict[str, Any],
    export_id: str,
) -> dict[str, Any]:
    _ensure_result_package_export_recordable(
        connection,
        result_id=normalized["result_id"],
        artifact_payload_mode=normalized["artifact_payload_mode"],
    )
    existing = connection.execute(
        """
        SELECT lifecycle_state, package_bytes_state
        FROM result_package_exports
        WHERE result_id = ? AND sha256 = ? AND manifest_sha256 = ?
        """,
        (
            normalized["result_id"],
            normalized["sha256"],
            normalized["manifest_sha256"],
        ),
    ).fetchone()
    if existing is not None and str(existing["lifecycle_state"] or "") != "active":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_NOT_ACTIVE: {existing['lifecycle_state']}")
    if existing is not None and str(existing["package_bytes_state"] or "") != "available":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_BYTES_UNAVAILABLE: {existing['package_bytes_state']}")
    connection.execute(
        """
        INSERT INTO result_package_exports (
            package_export_id, result_id, run_id, workflow_revision_id,
            package_path, package_uri, size_bytes, sha256, manifest_sha256,
            evidence_event_id, artifact_ids_json, include_artifacts,
            artifact_payload_mode, lifecycle_state, package_bytes_state,
            retired_at, package_bytes_deleted_at, package_bytes_gc_reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'available', NULL, NULL, '', ?)
        """,
        (
            export_id,
            normalized["result_id"],
            normalized["run_id"],
            normalized["workflow_revision_id"],
            normalized["package_path"],
            normalized["package_uri"],
            normalized["size_bytes"],
            normalized["sha256"],
            normalized["manifest_sha256"],
            normalized["evidence_event_id"],
            normalized["artifact_ids_json"],
            normalized["include_artifacts"],
            normalized["artifact_payload_mode"],
            normalized["created_at"],
        ),
    )
    row = connection.execute(
        """
        SELECT *
        FROM result_package_exports
        WHERE result_id = ? AND sha256 = ? AND manifest_sha256 = ?
        """,
        (
            normalized["result_id"],
            normalized["sha256"],
            normalized["manifest_sha256"],
        ),
    ).fetchone()
    return _row_to_dict(row)


def ensure_result_package_export_recordable(
    cfg: RemoteRunnerConfig,
    *,
    result_id: str,
    artifact_payload_mode: str,
) -> None:
    normalized_result_id = _required_text(result_id, "RESULT_ID_REQUIRED")
    normalized_mode = _required_text(
        artifact_payload_mode,
        "RESULT_PACKAGE_ARTIFACT_PAYLOAD_MODE_REQUIRED",
    )
    if normalized_mode not in SUPPORTED_ARTIFACT_PAYLOAD_MODES:
        raise ValueError(f"RESULT_PACKAGE_ARTIFACT_PAYLOAD_MODE_UNSUPPORTED: {normalized_mode}")
    with get_connection(cfg) as connection:
        _ensure_result_package_export_recordable(
            connection,
            result_id=normalized_result_id,
            artifact_payload_mode=normalized_mode,
        )


def _normalize_result_package_export(
    *,
    result_id: str,
    run_id: str,
    workflow_revision_id: str,
    package_path: Path,
    package_uri: str,
    size_bytes: int,
    sha256: str,
    manifest_sha256: str,
    evidence_event_id: str,
    artifact_ids: list[str],
    include_artifacts: bool,
    artifact_payload_mode: str,
    created_at: str,
) -> tuple[dict[str, Any], str]:
    normalized_mode = _required_text(
        artifact_payload_mode,
        "RESULT_PACKAGE_ARTIFACT_PAYLOAD_MODE_REQUIRED",
    )
    if normalized_mode not in SUPPORTED_ARTIFACT_PAYLOAD_MODES:
        raise ValueError(f"RESULT_PACKAGE_ARTIFACT_PAYLOAD_MODE_UNSUPPORTED: {normalized_mode}")
    if type(include_artifacts) is not bool:
        raise ValueError("RESULT_PACKAGE_INCLUDE_ARTIFACTS_BOOL_REQUIRED")
    normalized = {
        "result_id": _required_text(result_id, "RESULT_ID_REQUIRED"),
        "run_id": _required_text(run_id, "RUN_ID_REQUIRED"),
        "workflow_revision_id": _required_text(
            workflow_revision_id,
            "WORKFLOW_REVISION_ID_REQUIRED",
        ),
        "package_path": str(package_path),
        "package_uri": _required_text(package_uri, "RESULT_PACKAGE_URI_REQUIRED"),
        "size_bytes": int(size_bytes),
        "sha256": _required_text(sha256, "RESULT_PACKAGE_SHA256_REQUIRED"),
        "manifest_sha256": _required_text(manifest_sha256, "RESULT_PACKAGE_MANIFEST_SHA256_REQUIRED"),
        "evidence_event_id": _required_text(evidence_event_id, "RESULT_PACKAGE_EVIDENCE_ID_REQUIRED"),
        "artifact_ids_json": json.dumps(sorted(set(artifact_ids)), ensure_ascii=False),
        "include_artifacts": 1 if include_artifacts else 0,
        "artifact_payload_mode": normalized_mode,
        "created_at": _required_text(created_at, "RESULT_PACKAGE_CREATED_AT_REQUIRED"),
    }
    return normalized, _export_id(normalized)


def fetch_result_package_export(
    cfg: RemoteRunnerConfig,
    *,
    package_export_id: str,
) -> dict[str, Any] | None:
    normalized_export_id = _required_text(package_export_id, "RESULT_PACKAGE_EXPORT_ID_REQUIRED")
    if not RESULT_PACKAGE_EXPORT_ID_RE.fullmatch(normalized_export_id):
        raise ValueError("RESULT_PACKAGE_EXPORT_ID_INVALID")
    with get_connection(cfg) as connection:
        row = connection.execute(
            """
            SELECT *
            FROM result_package_exports
            WHERE package_export_id = ?
            """,
            (normalized_export_id,),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def list_result_package_exports(
    cfg: RemoteRunnerConfig,
    *,
    result_id: str,
    lifecycle_state: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    normalized_result_id = _required_text(result_id, "RESULT_ID_REQUIRED")
    normalized_lifecycle_state = str(lifecycle_state or "").strip() or None
    if (
        normalized_lifecycle_state is not None
        and normalized_lifecycle_state not in SUPPORTED_RESULT_PACKAGE_LIFECYCLE_STATES
    ):
        raise ValueError(f"RESULT_PACKAGE_LIFECYCLE_STATE_UNSUPPORTED: {normalized_lifecycle_state}")
    bounded_limit = _bounded_limit(limit)
    with get_connection(cfg) as connection:
        if normalized_lifecycle_state is None:
            rows = connection.execute(
                """
                SELECT *
                FROM result_package_exports
                WHERE result_id = ?
                ORDER BY created_at DESC, package_export_id DESC
                LIMIT ?
                """,
                (normalized_result_id, bounded_limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM result_package_exports
                WHERE result_id = ? AND lifecycle_state = ?
                ORDER BY created_at DESC, package_export_id DESC
                LIMIT ?
                """,
                (normalized_result_id, normalized_lifecycle_state, bounded_limit),
            ).fetchall()
    return [_row_to_dict(row) for row in rows]


def list_result_package_exports_for_byte_gc(cfg: RemoteRunnerConfig, *, limit: int = 1000) -> list[dict[str, Any]]:
    bounded_limit = _bounded_scan_limit(limit)
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM result_package_exports
            ORDER BY COALESCE(retired_at, created_at) ASC, created_at ASC, package_export_id ASC
            LIMIT ?
            """,
            (bounded_limit,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def _ensure_result_package_export_recordable(
    connection: Any,
    *,
    result_id: str,
    artifact_payload_mode: str,
) -> None:
    existing_mode = connection.execute(
        """
        SELECT package_export_id, lifecycle_state, package_bytes_state
        FROM result_package_exports
        WHERE result_id = ? AND artifact_payload_mode = ?
        ORDER BY created_at DESC, package_export_id DESC
        LIMIT 1
        """,
        (result_id, artifact_payload_mode),
    ).fetchone()
    if existing_mode is not None and str(existing_mode["lifecycle_state"] or "") != "active":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_NOT_ACTIVE: {existing_mode['lifecycle_state']}")
    if existing_mode is not None and str(existing_mode["package_bytes_state"] or "") != "available":
        raise ValueError(
            f"RESULT_PACKAGE_EXPORT_BYTES_UNAVAILABLE: {existing_mode['package_bytes_state']}"
        )
    if existing_mode is not None:
        raise ValueError(f"RESULT_PACKAGE_EXPORT_ALREADY_EXISTS: {existing_mode['package_export_id']}")


def mark_result_package_export_retired(
    connection: Any,
    *,
    package_export_id: str,
    retired_at: str,
) -> dict[str, Any]:
    normalized_export_id = _required_text(package_export_id, "RESULT_PACKAGE_EXPORT_ID_REQUIRED")
    normalized_retired_at = _required_text(retired_at, "RESULT_PACKAGE_RETIRED_AT_REQUIRED")
    if not RESULT_PACKAGE_EXPORT_ID_RE.fullmatch(normalized_export_id):
        raise ValueError("RESULT_PACKAGE_EXPORT_ID_INVALID")
    row = connection.execute(
        """
        SELECT *
        FROM result_package_exports
        WHERE package_export_id = ?
        """,
        (normalized_export_id,),
    ).fetchone()
    if row is None:
        raise ValueError("RESULT_PACKAGE_EXPORT_NOT_FOUND")
    if str(row["lifecycle_state"] or "") != "active":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_NOT_ACTIVE: {row['lifecycle_state']}")
    connection.execute(
        """
        UPDATE result_package_exports
        SET lifecycle_state = 'retired',
            retired_at = ?
        WHERE package_export_id = ?
        """,
        (normalized_retired_at, normalized_export_id),
    )
    updated = connection.execute(
        """
        SELECT *
        FROM result_package_exports
        WHERE package_export_id = ?
        """,
        (normalized_export_id,),
    ).fetchone()
    return _row_to_dict(updated)


def mark_result_package_export_bytes_deleting(
    connection: Any,
    *,
    package_export_id: str,
    deleted_at: str,
    reason: str,
) -> dict[str, Any]:
    normalized_export_id = _required_text(package_export_id, "RESULT_PACKAGE_EXPORT_ID_REQUIRED")
    if not RESULT_PACKAGE_EXPORT_ID_RE.fullmatch(normalized_export_id):
        raise ValueError("RESULT_PACKAGE_EXPORT_ID_INVALID")
    normalized_deleted_at = _required_text(
        deleted_at,
        "RESULT_PACKAGE_BYTES_DELETED_AT_REQUIRED",
    )
    row = connection.execute(
        """
        SELECT *
        FROM result_package_exports
        WHERE package_export_id = ?
        """,
        (normalized_export_id,),
    ).fetchone()
    if row is None:
        raise ValueError("RESULT_PACKAGE_EXPORT_NOT_FOUND")
    if str(row["lifecycle_state"] or "") != "retired":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_NOT_RETIRED: {row['lifecycle_state']}")
    byte_state = str(row["package_bytes_state"] or "")
    if byte_state == "deleted":
        raise ValueError("RESULT_PACKAGE_EXPORT_BYTES_ALREADY_DELETED")
    if byte_state != "available":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_BYTES_STATE_UNSUPPORTED: {byte_state}")
    cursor = connection.execute(
        """
        UPDATE result_package_exports
        SET package_bytes_state = 'deleting',
            package_bytes_deleted_at = ?,
            package_bytes_gc_reason = ?
        WHERE package_export_id = ?
          AND package_bytes_state = 'available'
        """,
        (normalized_deleted_at, str(reason or "").strip(), normalized_export_id),
    )
    if cursor.rowcount != 1:
        _raise_result_package_byte_state_conflict(connection, normalized_export_id)
    updated = connection.execute(
        """
        SELECT *
        FROM result_package_exports
        WHERE package_export_id = ?
        """,
        (normalized_export_id,),
    ).fetchone()
    return _row_to_dict(updated)


def mark_result_package_export_bytes_deleted(
    connection: Any,
    *,
    package_export_id: str,
    deleted_at: str,
    reason: str,
) -> dict[str, Any]:
    normalized_export_id = _required_text(package_export_id, "RESULT_PACKAGE_EXPORT_ID_REQUIRED")
    if not RESULT_PACKAGE_EXPORT_ID_RE.fullmatch(normalized_export_id):
        raise ValueError("RESULT_PACKAGE_EXPORT_ID_INVALID")
    normalized_deleted_at = _required_text(
        deleted_at,
        "RESULT_PACKAGE_BYTES_DELETED_AT_REQUIRED",
    )
    row = connection.execute(
        """
        SELECT *
        FROM result_package_exports
        WHERE package_export_id = ?
        """,
        (normalized_export_id,),
    ).fetchone()
    if row is None:
        raise ValueError("RESULT_PACKAGE_EXPORT_NOT_FOUND")
    if str(row["lifecycle_state"] or "") != "retired":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_NOT_RETIRED: {row['lifecycle_state']}")
    byte_state = str(row["package_bytes_state"] or "")
    if byte_state == "deleted":
        raise ValueError("RESULT_PACKAGE_EXPORT_BYTES_ALREADY_DELETED")
    if byte_state != "deleting":
        raise ValueError(f"RESULT_PACKAGE_EXPORT_BYTES_STATE_UNSUPPORTED: {byte_state}")
    cursor = connection.execute(
        """
        UPDATE result_package_exports
        SET package_bytes_state = 'deleted',
            package_bytes_deleted_at = ?,
            package_bytes_gc_reason = ?
        WHERE package_export_id = ?
          AND package_bytes_state = 'deleting'
        """,
        (normalized_deleted_at, str(reason or "").strip(), normalized_export_id),
    )
    if cursor.rowcount != 1:
        _raise_result_package_byte_state_conflict(connection, normalized_export_id)
    updated = connection.execute(
        """
        SELECT *
        FROM result_package_exports
        WHERE package_export_id = ?
        """,
        (normalized_export_id,),
    ).fetchone()
    return _row_to_dict(updated)


def _raise_result_package_byte_state_conflict(
    connection: Any,
    package_export_id: str,
) -> None:
    row = connection.execute(
        """
        SELECT package_bytes_state
        FROM result_package_exports
        WHERE package_export_id = ?
        """,
        (package_export_id,),
    ).fetchone()
    if row is None:
        raise ValueError("RESULT_PACKAGE_EXPORT_NOT_FOUND")
    byte_state = str(row["package_bytes_state"] or "")
    if byte_state == "deleted":
        raise ValueError("RESULT_PACKAGE_EXPORT_BYTES_ALREADY_DELETED")
    raise ValueError(f"RESULT_PACKAGE_EXPORT_BYTES_STATE_UNSUPPORTED: {byte_state}")


def _row_to_dict(row: Any) -> dict[str, Any]:
    package_bytes_state = row["package_bytes_state"]
    return {
        "packageExportId": row["package_export_id"],
        "resultId": row["result_id"],
        "runId": row["run_id"],
        "workflowRevisionId": row["workflow_revision_id"],
        "packagePath": row["package_path"],
        "packageUri": row["package_uri"],
        "sizeBytes": int(row["size_bytes"]),
        "sha256": row["sha256"],
        "manifestSha256": row["manifest_sha256"],
        "evidenceEventId": row["evidence_event_id"],
        "artifactIds": json.loads(row["artifact_ids_json"] or "[]"),
        "includeArtifacts": bool(row["include_artifacts"]),
        "artifactPayloadMode": row["artifact_payload_mode"],
        "lifecycleState": row["lifecycle_state"],
        "retiredAt": row["retired_at"],
        "packageBytesState": package_bytes_state,
        "packageBytesDeletedAt": row["package_bytes_deleted_at"],
        "packageBytesGcReason": row["package_bytes_gc_reason"],
        "packageFileDeleted": package_bytes_state == "deleted",
        "createdAt": row["created_at"],
    }


def _export_id(value: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "resultId": value["result_id"],
            "sha256": value["sha256"],
            "manifestSha256": value["manifest_sha256"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"rpexp_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _required_text(value: object, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _bounded_limit(value: object) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("RESULT_PACKAGE_EXPORT_LIST_LIMIT_INVALID") from exc
    if limit < 1 or limit > 500:
        raise ValueError("RESULT_PACKAGE_EXPORT_LIST_LIMIT_INVALID")
    return limit


def _bounded_scan_limit(value: object) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("RESULT_PACKAGE_EXPORT_GC_SCAN_LIMIT_INVALID") from exc
    if limit < 1 or limit > 5000:
        raise ValueError("RESULT_PACKAGE_EXPORT_GC_SCAN_LIMIT_INVALID")
    return limit
