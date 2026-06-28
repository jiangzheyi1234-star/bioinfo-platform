from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .artifact_cache_storage import (
    ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
    ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
    create_artifact_cache_pins,
    lookup_artifact_cache_entry,
    release_artifact_cache_pins,
)
from .artifact_io import (
    artifact_record_exists,
    artifact_record_stats,
    assert_managed_artifact_storage,
    restore_artifact_payload,
)
from .config import RemoteRunnerConfig
from .event_contracts import append_run_event_v2
from .evidence_storage import append_evidence_event
from .storage_core import get_connection, now_iso
from .workflow_run_storage import StaleRunAttemptError


ARTIFACT_CACHE_ADOPTION_EVENT_TYPE = "artifact.cache.adopt.v1"
ARTIFACT_CACHE_ADOPTION_SCHEMA_NAME = "ArtifactCacheAdoptionEvidence"


def try_adopt_cached_outputs(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    request_id: str,
    run_spec: dict[str, Any],
    output_schema: dict[str, Any] | None,
    outputs: dict[str, str] | None,
    attempt_id: str | None,
    lease_generation: int | None,
    result_dir: str,
    adopted_at: str | None = None,
) -> dict[str, Any]:
    if not _has_attempt_context(attempt_id, lease_generation):
        return _not_adopted("attempt_context_required")
    workflow_revision_id = str(run_spec.get("workflowRevisionId") or "").strip()
    if not workflow_revision_id:
        return _not_adopted("workflow_revision_missing")
    result_root = _result_dir_path(cfg, result_dir)
    specs = _declared_output_specs(output_schema, outputs, result_dir=result_root)
    if not specs:
        return _not_adopted("output_artifacts_missing")
    _require_current_run_revision_and_lease(
        cfg,
        run_id=run_id,
        attempt_id=str(attempt_id),
        lease_generation=int(lease_generation),
        workflow_revision_id=workflow_revision_id,
    )

    lookups: list[dict[str, Any]] = []
    misses: list[dict[str, str]] = []
    for spec in specs:
        lookup = lookup_artifact_cache_entry(
            cfg,
            _lookup_payload(
                run_spec,
                workflow_revision_id=workflow_revision_id,
                artifact_key=spec["artifactKey"],
                step_id=spec["stepId"],
            ),
        )
        lookups.append(lookup)
        if not lookup["hit"]:
            misses.append(
                {
                    "artifactKey": spec["artifactKey"],
                    "cacheKey": lookup["cacheKey"],
                    "reason": str(lookup["reason"]),
                }
            )
    if misses:
        return {
            **_not_adopted("cache_miss"),
            "misses": misses,
            "lookups": _lookup_summaries(lookups),
        }

    occurred_at = str(adopted_at or now_iso())
    cache_pins = create_artifact_cache_pins(
        cfg,
        entries=[lookup["entry"] for lookup in lookups],
        pin_scope=ARTIFACT_CACHE_RESTORE_PIN_SCOPE,
        owner_kind=ARTIFACT_CACHE_RESTORE_PIN_OWNER_KIND,
        owner_id=_restore_pin_owner_id(str(attempt_id), int(lease_generation)),
        reason="cache_restore",
        created_at=occurred_at,
    )
    pin_ids = [pin["cachePinId"] for pin in cache_pins]
    try:
        with get_connection(cfg) as connection:
            connection.execute("BEGIN IMMEDIATE")
            _require_active_lease(
                connection,
                run_id=run_id,
                attempt_id=str(attempt_id),
                lease_generation=int(lease_generation),
            )
            run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(run_id)
            if str(run["workflow_revision_id"] or "") != workflow_revision_id:
                raise ValueError("ARTIFACT_CACHE_WORKFLOW_REVISION_MISMATCH")
            artifacts: list[dict[str, str]] = []
            restored_paths: list[Path] = []
            try:
                for spec, lookup, cache_pin in zip(specs, lookups, cache_pins, strict=True):
                    artifact = _adopt_cached_artifact(
                        cfg,
                        connection,
                        run_id=run_id,
                        attempt_id=str(attempt_id),
                        workflow_revision_id=workflow_revision_id,
                        spec=spec,
                        lookup=lookup,
                        cache_pin=cache_pin,
                        occurred_at=occurred_at,
                    )
                    artifacts.append(artifact)
                    restored_paths.append(Path(artifact["restoredPath"]))
                _complete_run_from_cache(
                    connection,
                    run=run,
                    run_id=run_id,
                    request_id=request_id,
                    result_dir=str(result_root),
                    artifact_count=len(artifacts),
                    cache_keys=[lookup["cacheKey"] for lookup in lookups],
                    restored_paths=[artifact["restoredPath"] for artifact in artifacts],
                    restored_materialization_ids=[
                        artifact["restoredMaterializationId"] for artifact in artifacts
                    ],
                    cache_pin_ids=pin_ids,
                    occurred_at=occurred_at,
                )
                connection.commit()
            except Exception:
                for path in restored_paths:
                    _remove_restored_payload(path)
                raise
    finally:
        release_artifact_cache_pins(cfg, pin_ids=pin_ids)
    return {
        "adopted": True,
        "reason": "cache_hit",
        "runId": run_id,
        "attemptId": str(attempt_id),
        "leaseGeneration": int(lease_generation),
        "artifactIds": [artifact["artifactId"] for artifact in artifacts],
        "cacheKeys": [lookup["cacheKey"] for lookup in lookups],
        "cachePinIds": pin_ids,
        "lookups": _lookup_summaries(lookups),
        "adoptedAt": occurred_at,
    }


def _adopt_cached_artifact(
    cfg: RemoteRunnerConfig,
    connection: sqlite3.Connection,
    *,
    run_id: str,
    attempt_id: str,
    workflow_revision_id: str,
    spec: dict[str, str],
    lookup: dict[str, Any],
    cache_pin: dict[str, Any],
    occurred_at: str,
) -> dict[str, str]:
    entry = lookup["entry"]
    cache_row = connection.execute(
        """
        SELECT *
        FROM artifact_cache_entries
        WHERE cache_entry_id = ? AND lifecycle_state = 'active'
        """,
        (entry["cacheEntryId"],),
    ).fetchone()
    if cache_row is None:
        raise ValueError(f"ARTIFACT_CACHE_ENTRY_NOT_ACTIVE: {entry['cacheEntryId']}")
    _require_cache_payload_available(cfg, entry)
    if connection.execute(
        """
        SELECT 1
        FROM run_artifact_edges
        WHERE run_id = ? AND role = 'output' AND port_name = ?
        """,
        (run_id, spec["artifactKey"]),
    ).fetchone():
        raise ValueError(f"RUN_OUTPUT_ALREADY_ADOPTED: {spec['artifactKey']}")

    materialization = connection.execute(
        "SELECT * FROM artifact_materializations WHERE materialization_id = ?",
        (entry["materializationId"],),
    ).fetchone()
    if materialization is None:
        raise ValueError(f"ARTIFACT_CACHE_MATERIALIZATION_NOT_FOUND: {entry['materializationId']}")
    restore: dict[str, Any] | None = None
    try:
        restore = restore_artifact_payload(cfg, entry, Path(spec["declaredPath"]))
        restored_materialization_id = _record_restored_materialization(
            connection,
            artifact_blob_id=entry["artifactBlobId"],
            restore=restore,
            occurred_at=occurred_at,
        )
        artifact_id = f"art_{uuid.uuid4().hex[:10]}"
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
                spec["kind"],
                restore["path"],
                restore["storageBackend"],
                restore["storageUri"],
                int(entry["sizeBytes"]),
                entry["sha256"],
                spec["mimeType"],
                occurred_at,
            ),
        )
        edge_id = f"aredge_{uuid.uuid4().hex[:12]}"
        connection.execute(
            """
            INSERT INTO run_artifact_edges (
                edge_id, run_id, artifact_blob_id, role, port_name, step_id,
                content_hash, upstream_run_id, created_at
            ) VALUES (?, ?, ?, 'output', ?, ?, ?, NULL, ?)
            """,
            (
                edge_id,
                run_id,
                entry["artifactBlobId"],
                spec["artifactKey"],
                spec["stepId"] or None,
                entry["sha256"],
                occurred_at,
            ),
        )
        evidence = append_evidence_event(
            connection,
            event_type=ARTIFACT_CACHE_ADOPTION_EVENT_TYPE,
            schema_name=ARTIFACT_CACHE_ADOPTION_SCHEMA_NAME,
            subject_kind="artifact_cache",
            subject_id=entry["cacheKey"],
            payload={
                "cacheKey": entry["cacheKey"],
                "cacheEntryId": entry["cacheEntryId"],
                "cachePinId": cache_pin["cachePinId"],
                "sourceRunId": entry["runId"],
                "sourceArtifactId": entry["artifactId"],
                "artifactBlobId": entry["artifactBlobId"],
                "materializationId": entry["materializationId"],
                "runId": run_id,
                "attemptId": attempt_id,
                "artifactId": artifact_id,
                "artifactKey": spec["artifactKey"],
                "stepId": spec["stepId"],
                "runArtifactEdgeId": edge_id,
                "lookupEvidenceId": lookup["evidenceId"],
                "sourceStorageBackend": entry["storageBackend"],
                "sourceStorageUri": entry["storageUri"],
                "storageBackend": restore["storageBackend"],
                "storageUri": restore["storageUri"],
                "localPath": restore["localPath"],
                "restoredMaterializationId": restored_materialization_id,
                "sizeBytes": int(entry["sizeBytes"]),
                "sha256": entry["sha256"],
            },
            producer="artifact_cache_adoption",
            occurred_at=occurred_at,
        )
        lineage_id = f"lin_{uuid.uuid4().hex[:12]}"
        lineage_payload = {
            "artifactId": artifact_id,
            "artifactKey": spec["artifactKey"],
            "cacheKey": entry["cacheKey"],
            "cacheEntryId": entry["cacheEntryId"],
            "cachePinId": cache_pin["cachePinId"],
            "sourceArtifactId": entry["artifactId"],
            "sourceRunId": entry["runId"],
            "sourceStorageBackend": entry["storageBackend"],
            "sourceStorageUri": entry["storageUri"],
            "restoredPath": restore["path"],
            "restoredMaterializationId": restored_materialization_id,
            "evidenceEventId": evidence["eventId"],
            "runArtifactEdgeId": edge_id,
            **({"stepId": spec["stepId"]} if spec["stepId"] else {}),
        }
        connection.execute(
            """
            INSERT INTO lineage_edges (
                lineage_edge_id, subject_kind, subject_id, predicate, object_kind, object_id,
                run_id, attempt_id, workflow_revision_id, evidence_event_id,
                payload_json, content_hash, created_at
            ) VALUES (?, 'run', ?, 'h2ometa:cache_adopted', 'artifact_blob', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lineage_id,
                run_id,
                entry["artifactBlobId"],
                run_id,
                attempt_id,
                workflow_revision_id,
                evidence["eventId"],
                _stable_json(lineage_payload),
                entry["sha256"],
                occurred_at,
            ),
        )
    except Exception:
        if restore is not None:
            _remove_restored_payload(Path(restore["path"]))
        raise
    return {
        "artifactId": artifact_id,
        "runArtifactEdgeId": edge_id,
        "lineageEdgeId": lineage_id,
        "restoredPath": str(restore["path"]),
        "restoredMaterializationId": restored_materialization_id,
        "cachePinId": cache_pin["cachePinId"],
    }


def _record_restored_materialization(
    connection: sqlite3.Connection,
    *,
    artifact_blob_id: str,
    restore: dict[str, Any],
    occurred_at: str,
) -> str:
    existing = connection.execute(
        """
        SELECT materialization_id
        FROM artifact_materializations
        WHERE artifact_blob_id = ? AND storage_backend = ? AND storage_uri = ?
        """,
        (artifact_blob_id, restore["storageBackend"], restore["storageUri"]),
    ).fetchone()
    if existing is not None:
        return str(existing["materialization_id"])
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
            artifact_blob_id,
            restore["storageBackend"],
            restore["storageUri"],
            restore["localPath"],
            occurred_at,
        ),
    )
    return materialization_id


def _remove_restored_payload(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _complete_run_from_cache(
    connection: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    run_id: str,
    request_id: str,
    result_dir: str,
    artifact_count: int,
    cache_keys: list[str],
    restored_paths: list[str],
    restored_materialization_ids: list[str],
    cache_pin_ids: list[str],
    occurred_at: str,
) -> None:
    next_state_version = int(run["state_version"]) + 1
    connection.execute(
        """
        UPDATE runs
        SET status = 'completed', stage = 'cache', state_version = ?,
            message = 'Workflow outputs adopted from artifact cache.', result_dir = ?,
            last_error_json = NULL, finished_at = ?, last_updated_at = ?
        WHERE run_id = ?
        """,
        (next_state_version, result_dir, occurred_at, occurred_at, run_id),
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
        stage="cache",
        state_version=next_state_version,
        message="Workflow outputs adopted from artifact cache.",
        request_id=request_id,
        payload={
            "artifactCount": artifact_count,
            "cacheKeys": cache_keys,
            "restoredPaths": restored_paths,
            "restoredMaterializationIds": restored_materialization_ids,
            "cachePinIds": cache_pin_ids,
        },
        occurred_at=occurred_at,
    )


def _restore_pin_owner_id(attempt_id: str, lease_generation: int) -> str:
    return f"{attempt_id}:{lease_generation}"


def _declared_output_specs(
    output_schema: dict[str, Any] | None,
    outputs: dict[str, str] | None,
    *,
    result_dir: Path,
) -> list[dict[str, str]]:
    if not isinstance(output_schema, dict) or not isinstance(outputs, dict) or not outputs:
        return []
    raw_artifacts = output_schema.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        return []
    specs: list[dict[str, str]] = []
    for artifact in raw_artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("OUTPUT_ARTIFACT_INVALID")
        key = str(artifact.get("key") or "").strip()
        if not key or key not in outputs:
            raise ValueError(f"OUTPUT_ARTIFACT_KEY_UNKNOWN: {key}")
        kind = str(artifact.get("kind") or "").strip()
        mime_type = str(artifact.get("mimeType") or "").strip()
        if not kind or not mime_type:
            raise ValueError(f"OUTPUT_ARTIFACT_METADATA_REQUIRED: {key}")
        specs.append(
            {
                "artifactKey": key,
                "stepId": str(artifact.get("stepId") or "").strip(),
                "kind": kind,
                "mimeType": mime_type,
                "declaredPath": str(_declared_output_path(outputs[key], result_dir=result_dir)),
            }
        )
    return specs


def _result_dir_path(cfg: RemoteRunnerConfig, result_dir: str) -> Path:
    normalized = str(result_dir or "").strip()
    if not normalized:
        raise ValueError("ARTIFACT_CACHE_ADOPTION_RESULT_DIR_REQUIRED")
    resolved = Path(normalized).resolve()
    if not _is_relative_to(resolved, Path(cfg.results_dir).resolve()):
        raise ValueError("ARTIFACT_CACHE_ADOPTION_RESULT_DIR_UNMANAGED")
    return resolved


def _declared_output_path(raw: Any, *, result_dir: Path) -> Path:
    path = Path(str(raw or "").strip())
    if not str(path):
        raise ValueError("ARTIFACT_CACHE_ADOPTION_OUTPUT_PATH_REQUIRED")
    candidate = path if path.is_absolute() else result_dir / path
    resolved = candidate.resolve()
    if not _is_relative_to(resolved, result_dir):
        raise ValueError("ARTIFACT_CACHE_ADOPTION_OUTPUT_PATH_UNMANAGED")
    return resolved


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _lookup_payload(
    run_spec: dict[str, Any],
    *,
    workflow_revision_id: str,
    artifact_key: str,
    step_id: str,
) -> dict[str, Any]:
    return {
        "workflowRevisionId": workflow_revision_id,
        "artifactKey": artifact_key,
        "stepId": step_id,
        "role": "output",
        "inputs": run_spec.get("inputs") if "inputs" in run_spec else [],
        "params": run_spec.get("params") if "params" in run_spec else {},
        "resourceBindings": run_spec.get("resourceBindings") if "resourceBindings" in run_spec else {},
        "execution": run_spec.get("execution") if "execution" in run_spec else {},
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
        or int(lease["lease_generation"]) != int(lease_generation)
        or str(lease["state"]) != "active"
    ):
        raise StaleRunAttemptError("RUN_ATTEMPT_STALE")


def _require_current_run_revision_and_lease(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    workflow_revision_id: str,
) -> None:
    with get_connection(cfg) as connection:
        _require_active_lease(
            connection,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        )
        run = connection.execute(
            "SELECT workflow_revision_id FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise KeyError(run_id)
        if str(run["workflow_revision_id"] or "") != workflow_revision_id:
            raise ValueError("ARTIFACT_CACHE_WORKFLOW_REVISION_MISMATCH")


def _require_cache_payload_available(cfg: RemoteRunnerConfig, entry: dict[str, Any]) -> None:
    record = {
        "storageBackend": entry["storageBackend"],
        "storageUri": entry["storageUri"],
        "sizeBytes": int(entry["sizeBytes"]),
        "sha256": entry["sha256"],
        "path": "",
    }
    try:
        assert_managed_artifact_storage(cfg, record)
    except ValueError as exc:
        if str(exc).startswith("RESULT_ARTIFACT_STORAGE_UNMANAGED"):
            raise ValueError(f"ARTIFACT_CACHE_PAYLOAD_UNMANAGED: {entry['cacheEntryId']}") from exc
        raise
    if not artifact_record_exists(cfg, record):
        raise ValueError(f"ARTIFACT_CACHE_PAYLOAD_UNAVAILABLE: {entry['cacheEntryId']}")
    actual_size, actual_sha = artifact_record_stats(cfg, record)
    if int(actual_size) != int(entry["sizeBytes"]) or str(actual_sha) != str(entry["sha256"]):
        raise ValueError(f"ARTIFACT_CACHE_PAYLOAD_CHECKSUM_MISMATCH: {entry['cacheEntryId']}")


def _lookup_summaries(lookups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "cacheKey": lookup["cacheKey"],
            "hit": bool(lookup["hit"]),
            "reason": str(lookup["reason"]),
            "evidenceId": lookup["evidenceId"],
            "artifactKey": str(lookup["keyPayload"].get("artifactKey") or ""),
        }
        for lookup in lookups
    ]


def _not_adopted(reason: str) -> dict[str, Any]:
    return {"adopted": False, "reason": reason}


def _has_attempt_context(attempt_id: str | None, lease_generation: int | None) -> bool:
    return bool(str(attempt_id or "").strip() and lease_generation is not None)


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
