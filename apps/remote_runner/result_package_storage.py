from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection


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
    created_at: str,
) -> dict[str, Any]:
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
        "created_at": _required_text(created_at, "RESULT_PACKAGE_CREATED_AT_REQUIRED"),
    }
    export_id = _export_id(normalized)
    with get_connection(cfg) as connection:
        connection.execute(
            """
            INSERT INTO result_package_exports (
                package_export_id, result_id, run_id, workflow_revision_id,
                package_path, package_uri, size_bytes, sha256, manifest_sha256,
                evidence_event_id, artifact_ids_json, lifecycle_state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(result_id, sha256, manifest_sha256) DO UPDATE SET
                package_path = excluded.package_path,
                package_uri = excluded.package_uri,
                size_bytes = excluded.size_bytes,
                evidence_event_id = excluded.evidence_event_id,
                artifact_ids_json = excluded.artifact_ids_json,
                lifecycle_state = 'active'
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
                normalized["created_at"],
            ),
        )
        connection.commit()
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


def _row_to_dict(row: Any) -> dict[str, Any]:
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
        "lifecycleState": row["lifecycle_state"],
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
