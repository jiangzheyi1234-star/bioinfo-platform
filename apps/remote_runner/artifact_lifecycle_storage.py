from __future__ import annotations

import json
import sqlite3
from typing import Any

from .config import RemoteRunnerConfig
from .storage_core import get_connection


TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled", "cancelled"}
TERMINAL_JOB_STATES = {"completed", "failed", "canceled", "cancelled", "dead_lettered"}
TERMINAL_ATTEMPT_STATES = {"succeeded", "failed", "canceled", "cancelled"}


def list_artifact_lifecycle_rows(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT
                artifacts.*,
                runs.pipeline_id,
                runs.status AS run_status,
                runs.finished_at AS run_finished_at,
                runs.last_updated_at AS run_last_updated_at,
                runs.result_dir AS run_result_dir,
                blobs.artifact_blob_id,
                materializations.materialization_id,
                materializations.lifecycle_state AS materialization_lifecycle_state,
                materializations.deleted_at AS materialization_deleted_at,
                materializations.gc_reason AS materialization_gc_reason,
                materializations.retention_until AS materialization_retention_until
            FROM artifacts
            LEFT JOIN runs
              ON runs.run_id = artifacts.run_id
            LEFT JOIN artifact_blobs AS blobs
              ON blobs.sha256 = artifacts.sha256
            LEFT JOIN artifact_materializations AS materializations
              ON materializations.artifact_blob_id = blobs.artifact_blob_id
             AND materializations.storage_backend = artifacts.storage_backend
             AND materializations.storage_uri = artifacts.storage_uri
            ORDER BY artifacts.created_at ASC, artifacts.artifact_id ASC
            """
        ).fetchall()
    return [_artifact_row_to_dict(row) for row in rows]


def list_ledger_only_materialization_rows(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT
                materializations.*,
                blobs.sha256,
                blobs.size_bytes,
                blobs.media_type
            FROM artifact_materializations AS materializations
            JOIN artifact_blobs AS blobs
              ON blobs.artifact_blob_id = materializations.artifact_blob_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM artifacts
                WHERE artifacts.sha256 = blobs.sha256
                  AND artifacts.storage_backend = materializations.storage_backend
                  AND artifacts.storage_uri = materializations.storage_uri
            )
            ORDER BY materializations.created_at ASC, materializations.materialization_id ASC
            """
        ).fetchall()
    return [_ledger_only_row_to_dict(row) for row in rows]


def lifecycle_reference_reasons(cfg: RemoteRunnerConfig) -> dict[str, set[str]]:
    reasons: dict[str, set[str]] = {}
    with get_connection(cfg) as connection:
        _add_run_ref_reasons(
            reasons,
            connection.execute(
                f"""
                SELECT run_id
                FROM runs
                WHERE status NOT IN ({_sql_placeholders(TERMINAL_RUN_STATUSES)})
                """,
                tuple(sorted(TERMINAL_RUN_STATUSES)),
            ).fetchall(),
            "run_active",
        )
        _add_run_ref_reasons(
            reasons,
            connection.execute(
                f"""
                SELECT run_id
                FROM run_jobs
                WHERE state NOT IN ({_sql_placeholders(TERMINAL_JOB_STATES)})
                """
                ,
                tuple(sorted(TERMINAL_JOB_STATES)),
            ).fetchall(),
            "job_active",
        )
        _add_run_ref_reasons(
            reasons,
            connection.execute(
                "SELECT run_id FROM run_leases WHERE state = 'active'"
            ).fetchall(),
            "lease_active",
        )
        _add_run_ref_reasons(
            reasons,
            connection.execute(
                f"""
                SELECT run_id
                FROM run_attempts
                WHERE state NOT IN ({_sql_placeholders(TERMINAL_ATTEMPT_STATES)})
                """,
                tuple(sorted(TERMINAL_ATTEMPT_STATES)),
            ).fetchall(),
            "attempt_active",
        )
        _add_run_ref_reasons(
            reasons,
            connection.execute(
                """
                SELECT run_id
                FROM candidate_outputs
                WHERE adopted_artifact_id IS NULL OR adopted_at IS NULL
                """
            ).fetchall(),
            "candidate_output_pending",
        )
        _add_production_evidence_reasons(reasons, connection)
    return reasons


def mark_lifecycle_deleted(
    connection: sqlite3.Connection,
    *,
    artifact_ids: list[str],
    storage_backend: str,
    storage_uri: str,
    sha256: str,
    deleted_at: str,
    reason: str,
    retention_until: str,
) -> None:
    if artifact_ids:
        connection.executemany(
            """
            UPDATE artifacts
            SET lifecycle_state = 'deleted',
                deleted_at = ?,
                gc_reason = ?,
                retention_until = ?
            WHERE artifact_id = ? AND lifecycle_state = 'active'
            """,
            [(deleted_at, reason, retention_until, artifact_id) for artifact_id in artifact_ids],
        )
    connection.execute(
        """
        UPDATE artifact_materializations
        SET lifecycle_state = 'deleted',
            deleted_at = ?,
            gc_reason = ?,
            retention_until = ?
        WHERE storage_backend = ?
          AND storage_uri = ?
          AND lifecycle_state = 'active'
          AND artifact_blob_id IN (
              SELECT artifact_blob_id
              FROM artifact_blobs
              WHERE sha256 = ?
          )
        """,
        (deleted_at, reason, retention_until, storage_backend, storage_uri, sha256),
    )


def _artifact_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "artifactId": row["artifact_id"],
        "runId": row["run_id"],
        "pipelineId": row["pipeline_id"],
        "runStatus": row["run_status"],
        "runFinishedAt": row["run_finished_at"],
        "runLastUpdatedAt": row["run_last_updated_at"],
        "runResultDir": row["run_result_dir"],
        "kind": row["kind"],
        "path": row["path"],
        "storageBackend": row["storage_backend"],
        "storageUri": row["storage_uri"],
        "sizeBytes": int(row["size_bytes"] or 0),
        "sha256": row["sha256"],
        "mimeType": row["mime_type"],
        "createdAt": row["created_at"],
        "lifecycleState": row["lifecycle_state"],
        "deletedAt": row["deleted_at"],
        "gcReason": row["gc_reason"],
        "retentionUntil": row["retention_until"],
        "artifactBlobId": row["artifact_blob_id"],
        "materializationId": row["materialization_id"],
        "materializationLifecycleState": row["materialization_lifecycle_state"],
        "materializationDeletedAt": row["materialization_deleted_at"],
        "materializationGcReason": row["materialization_gc_reason"],
        "materializationRetentionUntil": row["materialization_retention_until"],
    }


def _ledger_only_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "materializationId": row["materialization_id"],
        "artifactBlobId": row["artifact_blob_id"],
        "storageBackend": row["storage_backend"],
        "storageUri": row["storage_uri"],
        "localPath": row["local_path"],
        "sizeBytes": int(row["size_bytes"] or 0),
        "sha256": row["sha256"],
        "mediaType": row["media_type"],
        "createdAt": row["created_at"],
        "lifecycleState": row["lifecycle_state"],
        "deletedAt": row["deleted_at"],
        "gcReason": row["gc_reason"],
        "retentionUntil": row["retention_until"],
    }


def _add_run_ref_reasons(reasons: dict[str, set[str]], rows: list[sqlite3.Row], reason: str) -> None:
    for row in rows:
        run_id = str(row["run_id"] or "").strip()
        if run_id:
            reasons.setdefault(run_id, set()).add(reason)


def _add_production_evidence_reasons(reasons: dict[str, set[str]], connection: sqlite3.Connection) -> None:
    rows = connection.execute("SELECT contract_status_json FROM tools").fetchall()
    for row in rows:
        contract_status = _json_object(row["contract_status_json"])
        production = contract_status.get("production") if isinstance(contract_status.get("production"), dict) else {}
        run_id = str(production.get("runId") or "").strip()
        if run_id:
            reasons.setdefault(run_id, set()).add("production_evidence")


def _json_object(payload: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(str(payload or "{}"))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _sql_placeholders(values: set[str]) -> str:
    return ", ".join("?" for _ in values)
