from __future__ import annotations

import json
from typing import Any

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
    run = fetch_run(cfg, run_id)
    if run is None:
        raise RemoteRunnerNotFoundError("RUN_NOT_FOUND")
    with get_connection(cfg) as connection:
        rows = connection.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    artifacts = [
        {
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
        }
        for row in rows
    ]
    return {"runId": run_id, "resultDir": run["resultDir"], "artifacts": artifacts}


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
        artifacts = fetch_run_results(cfg, row["run_id"])["artifacts"]
        items.append(
            {
                "resultId": f"res_{row['run_id']}",
                "runId": row["run_id"],
                "title": f"{row['pipeline_id']} result",
                "pipelineId": row["pipeline_id"],
                "artifactCount": len(artifacts),
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
        "artifacts": results["artifacts"],
    }
