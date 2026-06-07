from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
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
    storage_backend = "local"
    storage_uri = path.resolve().as_uri()
    artifact = {
        "artifactId": f"art_{uuid.uuid4().hex[:10]}",
        "runId": run_id,
        "kind": kind,
        "path": str(path),
        "storageBackend": storage_backend,
        "storageUri": storage_uri,
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
) -> dict[str, Any]:
    normalized_key = str(artifact_key or "").strip()
    if not normalized_key:
        return {}

    from .artifact_ledger_storage import (
        record_artifact_blob_for_path,
        record_artifact_materialization,
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
        local_path=path,
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
    return {
        "artifactBlobId": blob["artifactBlobId"],
        "materializationId": materialization["materializationId"],
        "runArtifactEdgeId": edge["edgeId"],
    }


def artifact_payload_stats(path: Path) -> tuple[int, str]:
    if path.is_file():
        content = path.read_bytes()
        return len(content), hashlib.sha256(content).hexdigest()
    if path.is_dir():
        digest = hashlib.sha256()
        size_bytes = 0
        for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
            relative = child.relative_to(path).as_posix()
            if child.is_dir():
                digest.update(f"D\t{relative}\0".encode("utf-8"))
                continue
            if child.is_file():
                content = child.read_bytes()
                digest.update(f"F\t{relative}\0".encode("utf-8"))
                digest.update(content)
                size_bytes += len(content)
        return size_bytes, digest.hexdigest()
    raise ValueError("OUTPUT_ARTIFACT_PATH_INVALID")
