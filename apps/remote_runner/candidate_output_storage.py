"""Candidate output ledger for fenced or crashed run attempts."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any

from .artifact_io import artifact_payload_stats, persist_artifact_location
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .event_contracts import append_run_event_v2
from .storage_core import get_connection, now_iso
from .workflow_run_storage import StaleRunAttemptError


def record_candidate_output(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    output_key: str,
    path: Path,
    observed_at: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    normalized_generation = _required_generation(lease_generation)
    normalized_output_key = _required_text(output_key, "OUTPUT_KEY_REQUIRED")
    output_path = Path(path)
    observed = _optional_text(observed_at) or now_iso()
    size_bytes: int | None = None
    sha256: str | None = None
    exists = output_path.exists()
    if exists:
        size_bytes, sha256 = artifact_payload_stats(output_path)
    verification = {
        "exists": exists,
        "observedAt": observed,
    }

    with get_connection(cfg) as connection:
        existing = connection.execute(
            """
            SELECT * FROM candidate_outputs
            WHERE run_id = ? AND attempt_id = ? AND lease_generation = ? AND output_key = ?
            """,
            (normalized_run_id, normalized_attempt_id, normalized_generation, normalized_output_key),
        ).fetchone()
        if existing is not None and existing["adopted_artifact_id"]:
            raise ValueError(f"CANDIDATE_OUTPUT_ALREADY_ADOPTED: {normalized_output_key}")
        candidate_id = existing["candidate_output_id"] if existing is not None else f"cout_{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO candidate_outputs (
                candidate_output_id, run_id, attempt_id, lease_generation, output_key, path,
                size_bytes, sha256, observed_at, verification_state,
                verification_json, adopted_artifact_id, adopted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, attempt_id, lease_generation, output_key) DO UPDATE SET
                path = excluded.path,
                size_bytes = excluded.size_bytes,
                sha256 = excluded.sha256,
                observed_at = excluded.observed_at,
                verification_state = excluded.verification_state,
                verification_json = excluded.verification_json,
                adopted_artifact_id = NULL,
                adopted_at = NULL
            """,
            (
                candidate_id,
                normalized_run_id,
                normalized_attempt_id,
                normalized_generation,
                normalized_output_key,
                str(output_path),
                size_bytes,
                sha256,
                observed,
                "pending",
                _stable_json(verification),
                None,
                None,
            ),
        )
        connection.commit()
        row = _fetch_candidate_row(
            connection,
            run_id=normalized_run_id,
            attempt_id=normalized_attempt_id,
            lease_generation=normalized_generation,
            output_key=normalized_output_key,
        )
    return _row_to_candidate(row)


def verify_candidate_outputs(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    expected_outputs: dict[str, dict[str, Any]],
    output_keys: set[str] | None = None,
    verified_at: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    normalized_generation = _required_generation(lease_generation)
    expected = _normalize_expected_outputs(expected_outputs)
    occurred_at = _optional_text(verified_at) or now_iso()
    verified: list[str] = []
    rejected: list[dict[str, str]] = []

    with get_connection(cfg) as connection:
        rows = _candidate_rows_for_verification(
            connection,
            run_id=normalized_run_id,
            attempt_id=normalized_attempt_id,
            lease_generation=normalized_generation,
            output_keys=output_keys,
        )
        seen = {str(row["output_key"]) for row in rows}
        missing = sorted(key for key in expected if key not in seen)
        for row in rows:
            output_key = str(row["output_key"])
            reason = _candidate_rejection_reason(row, expected.get(output_key))
            state = "rejected" if reason else "verified"
            if reason:
                rejected.append({"outputKey": output_key, "reason": reason})
            else:
                verified.append(output_key)
            connection.execute(
                """
                UPDATE candidate_outputs
                SET verification_state = ?, verification_json = ?
                WHERE candidate_output_id = ?
                """,
                (
                    state,
                    _stable_json({"verifiedAt": occurred_at, "reason": reason, "expected": expected.get(output_key)}),
                    row["candidate_output_id"],
                ),
            )
        connection.commit()
    return {
        "runId": normalized_run_id,
        "attemptId": normalized_attempt_id,
        "leaseGeneration": normalized_generation,
        "verified": verified,
        "rejected": rejected,
        "missing": missing,
    }


def _candidate_rows_for_verification(
    connection,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    output_keys: set[str] | None,
):
    if output_keys is None:
        return connection.execute(
            """
            SELECT * FROM candidate_outputs
            WHERE run_id = ? AND attempt_id = ? AND lease_generation = ?
            ORDER BY output_key ASC
            """,
            (run_id, attempt_id, lease_generation),
        ).fetchall()
    normalized_keys = sorted({_required_text(key, "OUTPUT_KEY_REQUIRED") for key in output_keys})
    if not normalized_keys:
        raise ValueError("OUTPUT_KEYS_REQUIRED")
    placeholders = ", ".join("?" for _ in normalized_keys)
    return connection.execute(
        f"""
        SELECT * FROM candidate_outputs
        WHERE run_id = ? AND attempt_id = ? AND lease_generation = ?
          AND output_key IN ({placeholders})
        ORDER BY output_key ASC
        """,
        (run_id, attempt_id, lease_generation, *normalized_keys),
    ).fetchall()


def adopt_verified_candidate_outputs(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    expected_outputs: dict[str, dict[str, Any]],
    adopted_at: str | None = None,
    finalize_run: bool = False,
    request_id: str | None = None,
    result_dir: str | None = None,
    lineage_predicate: str = "prov:generated",
    lineage_payload_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    normalized_attempt_id = _required_text(attempt_id, "ATTEMPT_ID_REQUIRED")
    normalized_generation = _required_generation(lease_generation)
    expected = _normalize_expected_outputs(expected_outputs)
    occurred_at = _optional_text(adopted_at) or now_iso()
    artifact_ids: list[str] = []

    with get_connection(cfg) as connection:
        connection.execute("BEGIN IMMEDIATE")
        _require_active_lease(
            connection,
            run_id=normalized_run_id,
            attempt_id=normalized_attempt_id,
            lease_generation=normalized_generation,
        )
        for output_key, spec in expected.items():
            row = _fetch_candidate_row(
                connection,
                run_id=normalized_run_id,
                attempt_id=normalized_attempt_id,
                lease_generation=normalized_generation,
                output_key=output_key,
            )
            if row is None or row["verification_state"] != "verified":
                raise ValueError(f"CANDIDATE_OUTPUT_NOT_VERIFIED: {output_key}")
            if row["adopted_artifact_id"]:
                artifact_ids.append(str(row["adopted_artifact_id"]))
                continue
            path = Path(str(row["path"]))
            size_bytes, sha256 = artifact_payload_stats(path)
            if size_bytes != row["size_bytes"] or sha256 != row["sha256"]:
                raise ValueError(f"CANDIDATE_OUTPUT_CHANGED_AFTER_VERIFICATION: {output_key}")
            expected_sha256 = _optional_text(spec.get("sha256"))
            if expected_sha256 and sha256 != expected_sha256:
                raise ValueError(f"CANDIDATE_OUTPUT_CHECKSUM_MISMATCH: {output_key}")
            artifact = _adopt_artifact(
                cfg,
                connection,
                run_id=normalized_run_id,
                attempt_id=normalized_attempt_id,
                kind=str(spec["kind"]),
                path=path,
                size_bytes=size_bytes,
                sha256=sha256,
                mime_type=str(spec["mimeType"]),
                artifact_key=output_key,
                step_id=_optional_text(spec.get("stepId")),
                upstream_run_id=_optional_text(spec.get("upstreamRunId")),
                created_at=occurred_at,
                lineage_predicate=lineage_predicate,
                lineage_payload_extra=lineage_payload_extra,
            )
            connection.execute(
                """
                UPDATE candidate_outputs
                SET adopted_artifact_id = ?, adopted_at = ?
                WHERE candidate_output_id = ?
                """,
                (artifact["artifactId"], occurred_at, row["candidate_output_id"]),
            )
            artifact_ids.append(artifact["artifactId"])
        if finalize_run:
            _complete_run_after_adoption(
                connection,
                run_id=normalized_run_id,
                request_id=_required_text(request_id, "REQUEST_ID_REQUIRED"),
                result_dir=_required_text(result_dir, "RESULT_DIR_REQUIRED"),
                occurred_at=occurred_at,
            )
        connection.commit()
    return {
        "runId": normalized_run_id,
        "attemptId": normalized_attempt_id,
        "leaseGeneration": normalized_generation,
        "artifactIds": artifact_ids,
    }


def _candidate_rejection_reason(row, expected: dict[str, Any] | None) -> str | None:
    if expected is None:
        return "OUTPUT_NOT_EXPECTED"
    if row["sha256"] is None:
        return "OUTPUT_MISSING"
    expected_path = _optional_text(expected.get("path"))
    if expected_path and str(row["path"]) != expected_path:
        return "OUTPUT_PATH_MISMATCH"
    expected_sha256 = _optional_text(expected.get("sha256"))
    if expected_sha256 and row["sha256"] != expected_sha256:
        return "OUTPUT_CHECKSUM_MISMATCH"
    return None


def _fetch_candidate_row(
    connection,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    output_key: str,
):
    return connection.execute(
        """
        SELECT * FROM candidate_outputs
        WHERE run_id = ? AND attempt_id = ? AND lease_generation = ? AND output_key = ?
        """,
        (run_id, attempt_id, lease_generation, output_key),
    ).fetchone()


def _row_to_candidate(row) -> dict[str, Any]:
    return {
        "candidateOutputId": row["candidate_output_id"],
        "runId": row["run_id"],
        "attemptId": row["attempt_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "outputKey": row["output_key"],
        "path": row["path"],
        "sizeBytes": int(row["size_bytes"]) if row["size_bytes"] is not None else None,
        "sha256": row["sha256"],
        "observedAt": row["observed_at"],
        "verificationState": row["verification_state"],
        "verification": json.loads(row["verification_json"] or "{}"),
        "adoptedArtifactId": row["adopted_artifact_id"],
        "adoptedAt": row["adopted_at"],
    }


def _require_active_lease(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> None:
    lease = connection.execute(
        """
        SELECT attempt_id, lease_generation, state
        FROM run_leases
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if (
        lease is None
        or str(lease["attempt_id"]) != attempt_id
        or int(lease["lease_generation"]) != lease_generation
        or str(lease["state"]) != "active"
    ):
        raise StaleRunAttemptError("RUN_ATTEMPT_STALE")


def _adopt_artifact(
    cfg: RemoteRunnerConfig,
    connection: sqlite3.Connection,
    *,
    run_id: str,
    attempt_id: str,
    kind: str,
    path: Path,
    size_bytes: int,
    sha256: str,
    mime_type: str,
    artifact_key: str,
    step_id: str | None,
    upstream_run_id: str | None,
    created_at: str,
    lineage_predicate: str,
    lineage_payload_extra: dict[str, Any] | None,
) -> dict[str, Any]:
    existing_edge = connection.execute(
        """
        SELECT edges.*, artifacts.artifact_id
        FROM run_artifact_edges AS edges
        LEFT JOIN artifacts
          ON artifacts.run_id = edges.run_id
         AND artifacts.sha256 = edges.content_hash
        WHERE edges.run_id = ?
          AND edges.role = 'output'
          AND edges.port_name = ?
          AND edges.lifecycle_state = 'active'
        """,
        (run_id, artifact_key),
    ).fetchone()
    if existing_edge is not None:
        raise ValueError(f"RUN_OUTPUT_ALREADY_ADOPTED: {artifact_key}")

    artifact_id = f"art_{uuid.uuid4().hex[:10]}"
    location = persist_artifact_location(
        cfg,
        path=path,
        run_id=run_id,
        artifact_id=artifact_id,
        sha256=sha256,
        size_bytes=size_bytes,
        mime_type=mime_type,
    )
    connection.execute(
        """
        INSERT INTO artifacts (
            artifact_id, run_id, kind, path, storage_backend, storage_uri,
            size_bytes, sha256, mime_type, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            run_id,
            kind,
            str(path),
            location["storageBackend"],
            location["storageUri"],
            size_bytes,
            sha256,
            mime_type,
            created_at,
        ),
    )
    blob_id = f"ablob_{sha256[:24]}"
    connection.execute(
        """
        INSERT INTO artifact_blobs (
            artifact_blob_id, sha256, blake3, size_bytes, media_type, created_at
        ) VALUES (?, ?, NULL, ?, ?, ?)
        ON CONFLICT(sha256) DO NOTHING
        """,
        (blob_id, sha256, size_bytes, mime_type, created_at),
    )
    blob = connection.execute(
        "SELECT * FROM artifact_blobs WHERE sha256 = ?",
        (sha256,),
    ).fetchone()
    blob_id = str(blob["artifact_blob_id"])
    materialization_id = f"amat_{uuid.uuid4().hex[:12]}"
    connection.execute(
        """
        INSERT INTO artifact_materializations (
            materialization_id, artifact_blob_id, storage_backend,
            storage_uri, local_path, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(artifact_blob_id, storage_backend, storage_uri) DO NOTHING
        """,
        (
            materialization_id,
            blob_id,
            location["storageBackend"],
            location["storageUri"],
            location["localPath"] if location["storageBackend"] == "local" else None,
            created_at,
        ),
    )
    materialization = connection.execute(
        """
        SELECT * FROM artifact_materializations
        WHERE artifact_blob_id = ? AND storage_backend = ? AND storage_uri = ?
        """,
        (blob_id, location["storageBackend"], location["storageUri"]),
    ).fetchone()
    edge_id = f"aredge_{uuid.uuid4().hex[:12]}"
    connection.execute(
        """
        INSERT INTO run_artifact_edges (
            edge_id, run_id, artifact_blob_id, role, port_name, step_id,
            content_hash, upstream_run_id, created_at
        ) VALUES (?, ?, ?, 'output', ?, ?, ?, ?, ?)
        """,
        (
            edge_id,
            run_id,
            blob_id,
            artifact_key,
            step_id,
            sha256,
            upstream_run_id,
            created_at,
        ),
    )
    evidence = append_evidence_event(
        connection,
        event_type="artifact.materialization.v1",
        schema_name="ArtifactMaterializationEvidence",
        subject_kind="artifact_blob",
        subject_id=blob_id,
        payload={
            "artifactId": artifact_id,
            "artifactKey": artifact_key,
            "artifactBlobId": blob_id,
            "materializationId": str(materialization["materialization_id"]),
            "runArtifactEdgeId": edge_id,
            "runId": run_id,
            "attemptId": attempt_id,
            "role": "output",
            "stepId": str(step_id or ""),
            "upstreamRunId": str(upstream_run_id or ""),
            "storageBackend": location["storageBackend"],
            "storageUri": location["storageUri"],
            "localPath": location["localPath"] if location["storageBackend"] == "local" else "",
            "mimeType": mime_type,
            "sizeBytes": size_bytes,
            "sha256": sha256,
        },
        occurred_at=created_at,
    )
    lineage_id = f"lin_{uuid.uuid4().hex[:12]}"
    run_row = connection.execute(
        "SELECT workflow_revision_id FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    workflow_revision_id = str((run_row or {})["workflow_revision_id"] or "").strip() if run_row is not None else ""
    lineage_payload = {
        "artifactId": artifact_id,
        "artifactKey": artifact_key,
        "evidenceEventId": evidence["eventId"],
        "materializationId": str(materialization["materialization_id"]),
        "role": "output",
        "runArtifactEdgeId": edge_id,
        **(lineage_payload_extra or {}),
        **({"stepId": step_id} if step_id else {}),
        **({"upstreamRunId": upstream_run_id} if upstream_run_id else {}),
    }
    normalized_predicate = _required_text(lineage_predicate, "LINEAGE_PREDICATE_REQUIRED")
    connection.execute(
        """
        INSERT INTO lineage_edges (
            lineage_edge_id, subject_kind, subject_id, predicate, object_kind, object_id,
            run_id, attempt_id, workflow_revision_id, evidence_event_id,
            payload_json, content_hash, created_at
        ) VALUES (?, 'run', ?, ?, 'artifact_blob', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lineage_id,
            run_id,
            normalized_predicate,
            blob_id,
            run_id,
            attempt_id,
            workflow_revision_id or None,
            evidence["eventId"],
            _stable_json(lineage_payload),
            sha256,
            created_at,
        ),
    )
    from .artifact_cache_storage import record_artifact_cache_entry_record

    cache_entry = record_artifact_cache_entry_record(
        connection,
        cfg=cfg,
        artifact={
            "artifactId": artifact_id,
            "runId": run_id,
            "storageBackend": location["storageBackend"],
            "storageUri": location["storageUri"],
            "sizeBytes": size_bytes,
            "sha256": sha256,
        },
        artifact_key=artifact_key,
        role="output",
        step_id=step_id,
        artifact_blob_id=blob_id,
        materialization_id=str(materialization["materialization_id"]),
        created_at=created_at,
    )
    return {
        "artifactId": artifact_id,
        "artifactBlobId": blob_id,
        "materializationId": str(materialization["materialization_id"]),
        "runArtifactEdgeId": edge_id,
        "lineageEdgeId": lineage_id,
        "evidenceEventId": evidence["eventId"],
        **_cache_entry_payload(cache_entry),
    }


def _complete_run_after_adoption(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    request_id: str,
    result_dir: str,
    occurred_at: str,
) -> None:
    run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise KeyError(run_id)
    next_state_version = int(run["state_version"]) + 1
    connection.execute(
        """
        UPDATE runs
        SET status = 'completed', stage = 'finalize', state_version = ?,
            message = 'Snakemake execution completed.', result_dir = ?,
            last_error_json = '{}', last_updated_at = ?
        WHERE run_id = ?
        """,
        (next_state_version, result_dir, occurred_at, run_id),
    )
    connection.execute(
        """
        UPDATE run_attempts
        SET output_adoption_state = 'adopted', updated_at = ?
        WHERE attempt_id = (
            SELECT attempt_id FROM run_leases WHERE run_id = ?
        )
        """,
        (occurred_at, run_id),
    )
    append_run_event_v2(
        connection,
        run_id=run_id,
        event_type="status-transition",
        from_status=str(run["status"]),
        to_status="completed",
        stage="finalize",
        state_version=next_state_version,
        message="Snakemake execution completed.",
        request_id=request_id,
        payload={},
        occurred_at=occurred_at,
    )


def _normalize_expected_outputs(expected_outputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(expected_outputs, dict) or not expected_outputs:
        raise ValueError("EXPECTED_OUTPUTS_REQUIRED")
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in expected_outputs.items():
        output_key = _required_text(key, "OUTPUT_KEY_REQUIRED")
        if not isinstance(value, dict):
            raise ValueError(f"EXPECTED_OUTPUT_INVALID: {output_key}")
        normalized[output_key] = {
            "path": _required_text(value.get("path"), f"EXPECTED_OUTPUT_PATH_REQUIRED: {output_key}"),
            "kind": _required_text(value.get("kind"), f"EXPECTED_OUTPUT_KIND_REQUIRED: {output_key}"),
            "mimeType": _required_text(value.get("mimeType"), f"EXPECTED_OUTPUT_MIME_TYPE_REQUIRED: {output_key}"),
        }
        step_id = _optional_text(value.get("stepId"))
        if step_id:
            normalized[output_key]["stepId"] = step_id
        upstream_run_id = _optional_text(value.get("upstreamRunId"))
        if upstream_run_id:
            normalized[output_key]["upstreamRunId"] = upstream_run_id
        expected_sha256 = _optional_text(value.get("sha256"))
        if expected_sha256:
            normalized[output_key]["sha256"] = expected_sha256
    return normalized


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _cache_entry_payload(cache_entry: dict[str, Any]) -> dict[str, Any]:
    if cache_entry.get("cacheEligible") is False:
        return {
            "artifactCacheEligible": False,
            "artifactCacheIneligibleReason": str(cache_entry.get("cacheIneligibleReason") or ""),
            **({"artifactCacheKey": str(cache_entry["cacheKey"])} if cache_entry.get("cacheKey") else {}),
        }
    return {
        "artifactCacheEligible": True,
        "artifactCacheEntryId": str(cache_entry["cacheEntryId"]),
        "artifactCacheKey": str(cache_entry["cacheKey"]),
    }


def _required_text(value: object, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _required_generation(value: object) -> int:
    try:
        generation = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("LEASE_GENERATION_REQUIRED") from exc
    if generation <= 0:
        raise ValueError("LEASE_GENERATION_REQUIRED")
    return generation


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
