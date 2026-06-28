from __future__ import annotations

import json
from typing import Any

from .artifact_output_labels import safe_artifact_output_label
from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError
from .storage_core import get_connection


def fetch_run(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    last_error = json.loads(row["last_error_json"]) if row["last_error_json"] else None
    return {
        "runId": row["run_id"],
        "serverId": row["server_id"],
        "projectId": row["project_id"],
        "pipelineId": row["pipeline_id"],
        "pipelineVersion": row["pipeline_version"],
        "runSpecVersion": row["run_spec_version"],
        "workflowRevisionId": row["workflow_revision_id"],
        "status": row["status"],
        "stage": row["stage"],
        "stateVersion": row["state_version"],
        "message": row["message"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "resultDir": row["result_dir"],
        "lastError": last_error,
        "lastUpdatedAt": row["last_updated_at"],
        "requestId": row["request_id"],
        "submittedAt": row["submitted_at"],
        "trigger": (
            {
                "triggerId": row["trigger_id"],
                "triggerEventId": row["trigger_event_id"],
                "source": row["trigger_source"],
                "cursor": row["trigger_cursor"],
            }
            if row["trigger_id"] or row["trigger_event_id"] or row["trigger_source"] or row["trigger_cursor"]
            else None
        ),
        "resumeSupported": False,
        "runSpec": json.loads(row["run_spec_json"]),
    }


def require_run(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    run = fetch_run(cfg, run_id)
    if run is None:
        raise RemoteRunnerNotFoundError("RUN_NOT_FOUND")
    return run


def list_runs(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute("SELECT run_id FROM runs ORDER BY submitted_at DESC").fetchall()
    return [fetch_run(cfg, row["run_id"]) for row in rows if fetch_run(cfg, row["run_id"]) is not None]


def fetch_run_events(cfg: RemoteRunnerConfig, run_id: str) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [
        {
            "eventId": row["event_id"],
            "runId": row["run_id"],
            "eventType": row["event_type"],
            "sequence": row["seq"],
            "schemaVersion": row["schema_version"],
            "fromStatus": row["from_status"],
            "toStatus": row["to_status"],
            "stage": row["stage"],
            "stateVersion": row["state_version"],
            "message": row["message"],
            "requestId": row["request_id"],
            "commandId": row["command_id"],
            "correlationId": row["correlation_id"],
            "actor": row["actor"],
            "payloadHash": row["payload_hash"],
            "eventHash": row["event_hash"],
            "prevEventHash": row["prev_event_hash"],
            "createdAt": row["created_at"],
            "detailsJson": json.loads(row["details_json"]) if row["details_json"] else None,
        }
        for row in rows
    ]


def fetch_run_results(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    from .artifact_ledger_storage import list_lineage_edges_for_run
    from .artifact_product_lineage import input_artifacts_from_lineage

    run = fetch_run(cfg, run_id)
    if run is None:
        raise RemoteRunnerNotFoundError("RUN_NOT_FOUND")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    lineage_edges = list_lineage_edges_for_run(cfg, run_id)
    artifact_labels = _output_labels_by_artifact_id(lineage_edges)
    artifacts = []
    for row in rows:
        artifact = {
            "artifactId": row["artifact_id"],
            "runId": row["run_id"],
            "kind": row["kind"],
            "path": row["path"],
            "storageBackend": row["storage_backend"],
            "storageUri": row["storage_uri"],
            "sizeBytes": row["size_bytes"],
            "sha256": row["sha256"],
            "mimeType": row["mime_type"],
            "createdAt": row["created_at"],
            "lifecycleState": row["lifecycle_state"],
            "deletedAt": row["deleted_at"],
            "gcReason": row["gc_reason"],
            "retentionUntil": row["retention_until"],
        }
        label = artifact_labels.get(str(row["artifact_id"] or ""))
        if label:
            artifact["artifactKey"] = label
        artifacts.append(artifact)
    input_artifacts = input_artifacts_from_lineage(lineage_edges)
    return {
        "runId": run_id,
        "resultDir": run["resultDir"],
        "artifacts": artifacts,
        "artifactCount": len(artifacts),
        "inputArtifacts": input_artifacts,
        "inputArtifactCount": len(input_artifacts),
        "lineageEdges": lineage_edges,
    }


def list_results(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        rows = connection.execute(
            """
            SELECT run_id, pipeline_id, finished_at, last_updated_at
            FROM runs
            WHERE status IN ('completed', 'failed')
            ORDER BY COALESCE(finished_at, last_updated_at) DESC
            """
        ).fetchall()
    items = []
    for row in rows:
        results = fetch_run_results(cfg, row["run_id"])
        artifacts = results["artifacts"]
        items.append(
            {
                "resultId": f"res_{row['run_id']}",
                "runId": row["run_id"],
                "title": f"{row['pipeline_id']} result",
                "pipelineId": row["pipeline_id"],
                "artifactCount": len(artifacts),
                "inputArtifactCount": results["inputArtifactCount"],
                "lineageEdges": results["lineageEdges"],
                "producedAt": row["finished_at"] or row["last_updated_at"],
            }
        )
    return items


def fetch_result(cfg: RemoteRunnerConfig, result_id: str) -> dict[str, Any]:
    run_id = result_id.removeprefix("res_")
    run = fetch_run(cfg, run_id)
    if run is None:
        raise RemoteRunnerNotFoundError("RESULT_NOT_FOUND")
    results = fetch_run_results(cfg, run_id)
    return {
        "resultId": result_id,
        "runId": run_id,
        "title": f"{run['pipelineId']} result",
        "pipelineId": run["pipelineId"],
        "producedAt": run["finishedAt"] or run["lastUpdatedAt"],
        "artifactCount": len(results["artifacts"]),
        "inputArtifactCount": results["inputArtifactCount"],
        "artifacts": results["artifacts"],
        "inputArtifacts": results["inputArtifacts"],
        "lineageEdges": results["lineageEdges"],
    }


def _output_labels_by_artifact_id(lineage_edges: list[dict[str, Any]]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for edge in lineage_edges:
        if edge.get("predicate") not in {"prov:generated", "h2ometa:cache_adopted"} or edge.get("objectKind") != "artifact_blob":
            continue
        payload = edge.get("payload") if isinstance(edge.get("payload"), dict) else {}
        artifact_id = str(payload.get("artifactId") or "").strip()
        label = safe_artifact_output_label(payload.get("artifactKey"))
        if not artifact_id or not label:
            continue
        if artifact_id in labels:
            if label != labels[artifact_id]:
                raise ValueError(f"ARTIFACT_OUTPUT_LABEL_CONFLICT: {artifact_id}")
            continue
        labels[artifact_id] = label
    return labels
