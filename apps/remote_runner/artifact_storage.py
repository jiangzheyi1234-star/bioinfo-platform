from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .artifact_io import artifact_payload_stats, persist_artifact_location
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .storage_core import get_connection, now_iso
from .workflow_run_storage import StaleRunAttemptError, run_attempt_can_publish


def persist_artifact(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    kind: str,
    path: Path,
    mime_type: str,
    attempt_id: str | None = None,
    lease_generation: int | None = None,
    artifact_key: str | None = None,
    role: str = "output",
    step_id: str | None = None,
    upstream_run_id: str | None = None,
) -> dict[str, Any]:
    size_bytes, sha256 = artifact_payload_stats(path)
    created_at = now_iso()
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
    artifact = {
        "artifactId": artifact_id,
        "runId": run_id,
        "kind": kind,
        "path": str(path),
        "storageBackend": location["storageBackend"],
        "storageUri": location["storageUri"],
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "mimeType": mime_type,
        "createdAt": created_at,
    }
    with get_connection(cfg) as connection:
        if not run_attempt_can_publish(
            connection,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
        ):
            raise StaleRunAttemptError("RUN_ATTEMPT_STALE")
        connection.execute(
            """
            INSERT INTO artifacts (
                artifact_id, run_id, kind, path, storage_backend, storage_uri,
                size_bytes, sha256, mime_type, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact["artifactId"],
                artifact["runId"],
                artifact["kind"],
                artifact["path"],
                artifact["storageBackend"],
                artifact["storageUri"],
                artifact["sizeBytes"],
                artifact["sha256"],
                artifact["mimeType"],
                artifact["createdAt"],
            ),
        )
        connection.commit()
    ledger = _record_artifact_ledger(
        cfg,
        artifact=artifact,
        path=path,
        artifact_key=artifact_key,
        role=role,
        step_id=step_id,
        upstream_run_id=upstream_run_id,
        attempt_id=attempt_id,
    )
    artifact.update(ledger)
    return artifact


def _record_artifact_ledger(
    cfg: RemoteRunnerConfig,
    *,
    artifact: dict[str, Any],
    path: Path,
    artifact_key: str | None,
    role: str,
    step_id: str | None,
    upstream_run_id: str | None,
    attempt_id: str | None,
) -> dict[str, Any]:
    normalized_key = str(artifact_key or "").strip()
    if not normalized_key:
        return {}

    from .artifact_ledger_storage import (
        record_artifact_blob_for_path,
        record_artifact_materialization,
        record_lineage_edge,
        record_run_artifact_edge,
    )

    blob = record_artifact_blob_for_path(
        cfg,
        path=path,
        media_type=str(artifact["mimeType"]),
        created_at=str(artifact["createdAt"]),
    )
    materialization = record_artifact_materialization(
        cfg,
        artifact_blob_id=blob["artifactBlobId"],
        storage_backend=str(artifact["storageBackend"]),
        storage_uri=str(artifact["storageUri"]),
        local_path=path if artifact["storageBackend"] == "local" else None,
        created_at=str(artifact["createdAt"]),
    )
    edge = record_run_artifact_edge(
        cfg,
        run_id=str(artifact["runId"]),
        artifact_blob_id=blob["artifactBlobId"],
        role=str(role or "output").strip() or "output",
        port_name=normalized_key,
        step_id=step_id,
        content_hash=blob["sha256"],
        upstream_run_id=upstream_run_id,
        created_at=str(artifact["createdAt"]),
    )
    evidence_event = _record_artifact_materialization_evidence(
        cfg,
        artifact=artifact,
        artifact_key=normalized_key,
        blob=blob,
        materialization=materialization,
        edge=edge,
        role=role,
        step_id=step_id,
        upstream_run_id=upstream_run_id,
        attempt_id=attempt_id,
    )
    lineage_edge = record_lineage_edge(
        cfg,
        subject_kind="run",
        subject_id=str(artifact["runId"]),
        predicate="prov:generated",
        object_kind="artifact_blob",
        object_id=blob["artifactBlobId"],
        run_id=str(artifact["runId"]),
        attempt_id=attempt_id,
        evidence_event_id=evidence_event["eventId"],
        payload={
            "artifactId": artifact["artifactId"],
            "artifactKey": normalized_key,
            "evidenceEventId": evidence_event["eventId"],
            "materializationId": materialization["materializationId"],
            "role": str(role or "output").strip() or "output",
            "runArtifactEdgeId": edge["edgeId"],
            **({"stepId": step_id} if step_id else {}),
            **({"upstreamRunId": upstream_run_id} if upstream_run_id else {}),
        },
        content_hash=blob["sha256"],
        created_at=str(artifact["createdAt"]),
    )
    return {
        "artifactBlobId": blob["artifactBlobId"],
        "materializationId": materialization["materializationId"],
        "runArtifactEdgeId": edge["edgeId"],
        "lineageEdgeId": lineage_edge["lineageEdgeId"],
        "evidenceEventId": evidence_event["eventId"],
    }


def _record_artifact_materialization_evidence(
    cfg: RemoteRunnerConfig,
    *,
    artifact: dict[str, Any],
    artifact_key: str,
    blob: dict[str, Any],
    materialization: dict[str, Any],
    edge: dict[str, Any],
    role: str,
    step_id: str | None,
    upstream_run_id: str | None,
    attempt_id: str | None,
) -> dict[str, Any]:
    payload = {
        "artifactId": str(artifact["artifactId"]),
        "artifactKey": artifact_key,
        "artifactBlobId": str(blob["artifactBlobId"]),
        "materializationId": str(materialization["materializationId"]),
        "runArtifactEdgeId": str(edge["edgeId"]),
        "runId": str(artifact["runId"]),
        "attemptId": str(attempt_id or ""),
        "role": str(role or "output").strip() or "output",
        "stepId": str(step_id or ""),
        "upstreamRunId": str(upstream_run_id or ""),
        "storageBackend": str(materialization["storageBackend"]),
        "storageUri": str(materialization["storageUri"]),
        "localPath": str(materialization.get("localPath") or ""),
        "mimeType": str(artifact["mimeType"]),
        "sizeBytes": int(artifact["sizeBytes"]),
        "sha256": str(blob["sha256"]),
    }
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type="artifact.materialization.v1",
            schema_name="ArtifactMaterializationEvidence",
            subject_kind="artifact_blob",
            subject_id=str(blob["artifactBlobId"]),
            payload=payload,
            occurred_at=str(artifact["createdAt"]),
        )
        connection.commit()
    return event
