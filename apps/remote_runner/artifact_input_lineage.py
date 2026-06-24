from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_io import artifact_payload_stats
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .storage_core import get_connection, now_iso


INPUT_ARTIFACT_EVIDENCE_EVENT_TYPE = "artifact.input.v1"
INPUT_ARTIFACT_EVIDENCE_SCHEMA_NAME = "ArtifactInputEvidence"


def record_run_input_artifact_lineage(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    resolved_inputs: list[dict[str, Any]],
    attempt_id: str | None = None,
    created_at: str | None = None,
) -> list[dict[str, Any]]:
    normalized_run_id = _required_text(run_id, "RUN_ID_REQUIRED")
    if not isinstance(resolved_inputs, list):
        raise ValueError("RUN_INPUTS_REQUIRED")
    timestamp = _optional_text(created_at) or now_iso()
    return [
        _record_one_input(
            cfg,
            run_id=normalized_run_id,
            resolved_input=item,
            attempt_id=attempt_id,
            created_at=timestamp,
        )
        for item in resolved_inputs
    ]


def _record_one_input(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    resolved_input: dict[str, Any],
    attempt_id: str | None,
    created_at: str,
) -> dict[str, Any]:
    if not isinstance(resolved_input, dict):
        raise ValueError("RUN_INPUT_INVALID")
    input_path = Path(_required_text(resolved_input.get("path"), "INPUT_PATH_REQUIRED"))
    expected_sha256 = _required_text(resolved_input.get("sha256"), "INPUT_SHA256_REQUIRED")
    expected_size = _required_int(resolved_input.get("sizeBytes"), "INPUT_SIZE_BYTES_REQUIRED")
    upload_id = _required_text(resolved_input.get("uploadId"), "INPUT_UPLOAD_ID_REQUIRED")
    filename = _required_text(resolved_input.get("filename"), "INPUT_FILENAME_REQUIRED")
    mime_type = _required_text(
        resolved_input.get("mimeType") or "application/octet-stream",
        "INPUT_MIME_TYPE_REQUIRED",
    )
    input_index = _input_index(resolved_input)
    port_name = _input_port_name(resolved_input, input_index=input_index)
    input_name = _optional_text(resolved_input.get("name"))
    input_role = _optional_text(resolved_input.get("role")) or "input"
    upstream_run_id = _optional_text(resolved_input.get("upstreamRunId"))

    if not input_path.exists():
        raise ValueError("INPUT_FILE_MISSING")
    actual_size, actual_sha256 = artifact_payload_stats(input_path)
    if actual_size != expected_size or actual_sha256 != expected_sha256:
        raise ValueError(f"INPUT_ARTIFACT_DIGEST_MISMATCH: {upload_id}")

    from .artifact_ledger_storage import (
        list_lineage_edges_for_run,
        list_run_artifact_edges,
        record_artifact_blob_for_path,
        record_artifact_materialization,
        record_lineage_edge,
        record_run_artifact_edge,
    )

    blob = record_artifact_blob_for_path(
        cfg,
        path=input_path,
        media_type=mime_type,
        created_at=created_at,
    )
    materialization = record_artifact_materialization(
        cfg,
        artifact_blob_id=blob["artifactBlobId"],
        storage_backend="local",
        storage_uri=input_path.resolve().as_uri(),
        local_path=input_path,
        created_at=created_at,
    )
    edge = _existing_input_edge(
        list_run_artifact_edges(cfg, run_id),
        artifact_blob_id=blob["artifactBlobId"],
        port_name=port_name,
        upstream_run_id=upstream_run_id,
    )
    if edge is None:
        edge = record_run_artifact_edge(
            cfg,
            run_id=run_id,
            artifact_blob_id=blob["artifactBlobId"],
            role="input",
            port_name=port_name,
            step_id=None,
            content_hash=blob["sha256"],
            upstream_run_id=upstream_run_id,
            created_at=created_at,
        )

    existing_lineage = _existing_input_lineage(
        list_lineage_edges_for_run(cfg, run_id),
        artifact_blob_id=blob["artifactBlobId"],
        run_artifact_edge_id=edge["edgeId"],
    )
    if existing_lineage is not None:
        return _input_record(
            resolved_input=resolved_input,
            blob=blob,
            materialization=materialization,
            edge=edge,
            lineage_edge=existing_lineage,
            evidence_event=None,
            port_name=port_name,
            input_index=input_index,
        )

    evidence_event = _record_artifact_input_evidence(
        cfg,
        run_id=run_id,
        resolved_input=resolved_input,
        blob=blob,
        materialization=materialization,
        edge=edge,
        attempt_id=attempt_id,
        port_name=port_name,
        input_index=input_index,
        input_name=input_name,
        input_role=input_role,
        created_at=created_at,
    )
    lineage_edge = record_lineage_edge(
        cfg,
        subject_kind="run",
        subject_id=run_id,
        predicate="prov:used",
        object_kind="artifact_blob",
        object_id=blob["artifactBlobId"],
        run_id=run_id,
        attempt_id=attempt_id,
        workflow_revision_id=_workflow_revision_id_for_run(cfg, run_id),
        evidence_event_id=evidence_event["eventId"],
        payload={
            "uploadId": upload_id,
            "filename": filename,
            "inputName": input_name or "",
            "inputRole": input_role,
            "inputIndex": input_index,
            "portName": port_name,
            "mimeType": mime_type,
            "sizeBytes": expected_size,
            "sha256": expected_sha256,
            "evidenceEventId": evidence_event["eventId"],
            "materializationId": materialization["materializationId"],
            "role": "input",
            "runArtifactEdgeId": edge["edgeId"],
            **({"upstreamRunId": upstream_run_id} if upstream_run_id else {}),
        },
        content_hash=blob["sha256"],
        created_at=created_at,
    )
    return _input_record(
        resolved_input=resolved_input,
        blob=blob,
        materialization=materialization,
        edge=edge,
        lineage_edge=lineage_edge,
        evidence_event=evidence_event,
        port_name=port_name,
        input_index=input_index,
    )


def _record_artifact_input_evidence(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    resolved_input: dict[str, Any],
    blob: dict[str, Any],
    materialization: dict[str, Any],
    edge: dict[str, Any],
    attempt_id: str | None,
    port_name: str,
    input_index: int,
    input_name: str | None,
    input_role: str,
    created_at: str,
) -> dict[str, Any]:
    payload = {
        "runId": run_id,
        "attemptId": str(attempt_id or ""),
        "uploadId": str(resolved_input["uploadId"]),
        "filename": str(resolved_input["filename"]),
        "inputName": str(input_name or ""),
        "inputRole": input_role,
        "inputIndex": input_index,
        "portName": port_name,
        "artifactBlobId": str(blob["artifactBlobId"]),
        "materializationId": str(materialization["materializationId"]),
        "runArtifactEdgeId": str(edge["edgeId"]),
        "mimeType": str(resolved_input["mimeType"]),
        "sizeBytes": int(resolved_input["sizeBytes"]),
        "sha256": str(blob["sha256"]),
        "role": "input",
    }
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type=INPUT_ARTIFACT_EVIDENCE_EVENT_TYPE,
            schema_name=INPUT_ARTIFACT_EVIDENCE_SCHEMA_NAME,
            subject_kind="artifact_blob",
            subject_id=str(blob["artifactBlobId"]),
            payload=payload,
            occurred_at=created_at,
        )
        connection.commit()
    return event


def _input_record(
    *,
    resolved_input: dict[str, Any],
    blob: dict[str, Any],
    materialization: dict[str, Any],
    edge: dict[str, Any],
    lineage_edge: dict[str, Any],
    evidence_event: dict[str, Any] | None,
    port_name: str,
    input_index: int,
) -> dict[str, Any]:
    return {
        "uploadId": str(resolved_input["uploadId"]),
        "filename": str(resolved_input["filename"]),
        "portName": port_name,
        "inputIndex": input_index,
        "artifactBlobId": blob["artifactBlobId"],
        "materializationId": materialization["materializationId"],
        "runArtifactEdgeId": edge["edgeId"],
        "lineageEdgeId": lineage_edge["lineageEdgeId"],
        "evidenceEventId": (
            evidence_event["eventId"]
            if evidence_event is not None
            else str(lineage_edge.get("evidenceEventId") or "")
        ),
        "sha256": blob["sha256"],
        "sizeBytes": blob["sizeBytes"],
        "mimeType": blob["mediaType"],
    }


def _existing_input_edge(
    edges: list[dict[str, Any]],
    *,
    artifact_blob_id: str,
    port_name: str,
    upstream_run_id: str | None,
) -> dict[str, Any] | None:
    for edge in edges:
        if (
            edge.get("artifactBlobId") == artifact_blob_id
            and edge.get("role") == "input"
            and edge.get("portName") == port_name
            and edge.get("upstreamRunId") == upstream_run_id
        ):
            return edge
    return None


def _existing_input_lineage(
    edges: list[dict[str, Any]],
    *,
    artifact_blob_id: str,
    run_artifact_edge_id: str,
) -> dict[str, Any] | None:
    for edge in edges:
        payload = edge.get("payload") if isinstance(edge.get("payload"), dict) else {}
        if (
            edge.get("predicate") == "prov:used"
            and edge.get("objectKind") == "artifact_blob"
            and edge.get("objectId") == artifact_blob_id
            and payload.get("runArtifactEdgeId") == run_artifact_edge_id
        ):
            return edge
    return None


def _workflow_revision_id_for_run(cfg: RemoteRunnerConfig, run_id: str) -> str | None:
    with get_connection(cfg) as connection:
        row = connection.execute(
            "SELECT workflow_revision_id FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return str(row["workflow_revision_id"] or "").strip() or None


def _input_port_name(resolved_input: dict[str, Any], *, input_index: int) -> str:
    return (
        _optional_text(resolved_input.get("name"))
        or _optional_text(resolved_input.get("role"))
        or f"input_{input_index + 1}"
    )


def _input_index(resolved_input: dict[str, Any]) -> int:
    try:
        return max(0, int(resolved_input.get("index") or 0))
    except (TypeError, ValueError):
        raise ValueError("INPUT_INDEX_INVALID") from None


def _required_int(value: object, code: str) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        raise ValueError(code) from None
    if normalized < 0:
        raise ValueError(code)
    return normalized


def _required_text(value: object, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
