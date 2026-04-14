"""Workflow runtime helpers extracted from RuntimeService."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from core.workflow import LaunchSpec, RunRecord, WorkflowSnapshotRecord, WorkflowSpec, compile_workflow_bundle, create_workflow_backend
from core.workflow.backends import prepare_workflow_run_layout


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(raw: Any, *, default: Any) -> Any:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return default
        return json.loads(text)
    return default


def _workflow_hash(workflow_payload: dict[str, Any]) -> str:
    return hashlib.sha256(_json_dumps(workflow_payload).encode("utf-8")).hexdigest()


def _workflow_status_to_execution_status(status: str) -> str:
    mapping = {
        "pending": "pending",
        "running": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "failed",
    }
    return mapping.get(str(status or "").strip().lower(), "failed")


def _workflow_status_to_task_status(status: str) -> str:
    mapping = {
        "pending": "queued",
        "running": "in_progress",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    return mapping.get(str(status or "").strip().lower(), "failed")


def _is_terminal_workflow_status(status: str) -> bool:
    return str(status or "").strip().lower() in {"completed", "failed", "cancelled"}


def _conn(runtime: Any):
    return runtime._project_manager.db


def _metadata_keys() -> tuple[str, ...]:
    return (
        "profile",
        "resume",
        "local_bundle_dir",
        "local_run_dir",
        "resolved_config_path",
        "remote_task_dir",
        "remote_bundle_dir",
        "remote_work_dir",
        "remote_output_dir",
        "launcher_pid",
        "nextflow_pid",
        "scheduler_job_id",
        "backend_kind",
        "executor",
        "packaging_mode",
        "container_runtime",
        "remote_status",
        "artifacts",
    )


def _workflow_metadata_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in _metadata_keys() if key in row}


def _workflow_row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    metadata = _json_loads(item.pop("metadata_json", "{}"), default={})
    if not isinstance(metadata, dict):
        metadata = {}
    snapshot_payload = _json_loads(item.get("snapshot_payload_json", "{}"), default={})
    if not isinstance(snapshot_payload, dict):
        snapshot_payload = {}
    item["snapshot_payload_json"] = snapshot_payload
    item.update(metadata)
    if not isinstance(item.get("artifacts"), list):
        item["artifacts"] = []
    if item.get("remote_status") and not isinstance(item.get("remote_status"), dict):
        item["remote_status"] = {}
    return item


def _snapshot_row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["workflow_definition_json"] = _json_loads(item.get("workflow_definition_json", "{}"), default={})
    item["params_schema_json"] = _json_loads(item.get("params_schema_json", "{}"), default={})
    return item


def _get_current_snapshot(runtime: Any, *, project_id: str, task_id: str) -> dict[str, Any] | None:
    row = _conn(runtime).execute(
        """
        SELECT *
        FROM workflow_snapshots
        WHERE project_id = ? AND task_id = ?
        """,
        (project_id, task_id),
    ).fetchone()
    return _snapshot_row_to_dict(row) if row is not None else None


def upsert_task_workflow_snapshot(runtime: Any, *, project_id: str, task_id: str, workflow_payload: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    workflow_hash = _workflow_hash(workflow_payload)
    workflow_id = str(workflow_payload.get("workflow_id") or "").strip()
    name = str(workflow_payload.get("name") or "").strip()
    version = str(workflow_payload.get("version") or "0.1.0").strip() or "0.1.0"
    params_schema = workflow_payload.get("params_schema", {})
    if not isinstance(params_schema, dict):
        params_schema = {}

    current = _get_current_snapshot(runtime, project_id=project_id, task_id=task_id)
    if current is None:
        snapshot_id = f"wsnap_{uuid.uuid4().hex[:12]}"
        created_at = now
        _conn(runtime).execute(
            """
            INSERT INTO workflow_snapshots (
                workflow_snapshot_id, project_id, task_id, workflow_id, name, version,
                workflow_definition_json, params_schema_json, workflow_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                project_id,
                task_id,
                workflow_id,
                name,
                version,
                _json_dumps(workflow_payload),
                _json_dumps(params_schema),
                workflow_hash,
                created_at,
                now,
            ),
        )
    else:
        snapshot_id = str(current["workflow_snapshot_id"])
        created_at = float(current.get("created_at") or now)
        _conn(runtime).execute(
            """
            UPDATE workflow_snapshots
            SET workflow_id = ?,
                name = ?,
                version = ?,
                workflow_definition_json = ?,
                params_schema_json = ?,
                workflow_hash = ?,
                updated_at = ?
            WHERE project_id = ? AND task_id = ?
            """,
            (
                workflow_id,
                name,
                version,
                _json_dumps(workflow_payload),
                _json_dumps(params_schema),
                workflow_hash,
                now,
                project_id,
                task_id,
            ),
        )
    _conn(runtime).commit()
    return WorkflowSnapshotRecord(
        workflow_snapshot_id=snapshot_id,
        project_id=project_id,
        task_id=task_id,
        workflow_id=workflow_id,
        name=name,
        version=version,
        workflow_definition_json=workflow_payload,
        params_schema_json=params_schema,
        workflow_hash=workflow_hash,
        created_at=created_at,
        updated_at=now,
    ).to_dict()


def _require_current_snapshot(runtime: Any, *, project_id: str, task_id: str) -> dict[str, Any]:
    snapshot = _get_current_snapshot(runtime, project_id=project_id, task_id=task_id)
    if snapshot is None:
        raise RuntimeError(f"Task {task_id} is missing current workflow snapshot")
    return snapshot


def _create_execution_row(runtime: Any, *, task_id: str, workflow_spec: WorkflowSpec, launch_spec: LaunchSpec, snapshot_id: str, snapshot_hash: str) -> str:
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    now = time.time()
    parameters = {
        "workflow_id": workflow_spec.workflow_id,
        "workflow_snapshot_id": snapshot_id,
        "snapshot_hash": snapshot_hash,
        "launch": launch_spec.to_dict(),
    }
    _conn(runtime).execute(
        """
        INSERT INTO executions (
            execution_id, task_id, sample_id, tool_id, tool_version, parameters, status,
            triggered_by, created_at, completed_at, error, retry_count, retry_of, remote_job_id,
            is_final_version, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            execution_id,
            task_id,
            None,
            f"workflow:{workflow_spec.workflow_id}",
            workflow_spec.version,
            _json_dumps(parameters),
            "pending",
            "workflow_runtime",
            now,
            None,
            None,
            0,
            None,
            None,
            0,
            None,
        ),
    )
    return execution_id


def _write_workflow_run(runtime: Any, row: dict[str, Any], *, insert: bool) -> None:
    metadata_json = _json_dumps(_workflow_metadata_from_row(row))
    if insert:
        _conn(runtime).execute(
            """
            INSERT INTO workflow_runs (
                run_id, project_id, task_id, workflow_snapshot_id, execution_id, workflow_id,
                profile_id, status, snapshot_hash, snapshot_payload_json, bundle_id, message,
                result_path, metadata_json, created_at, updated_at, started_at, finished_at, error_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(row.get("run_id") or ""),
                str(row.get("project_id") or ""),
                str(row.get("task_id") or ""),
                str(row.get("workflow_snapshot_id") or ""),
                str(row.get("execution_id") or ""),
                str(row.get("workflow_id") or ""),
                str(row.get("profile_id") or ""),
                str(row.get("status") or "pending"),
                str(row.get("snapshot_hash") or ""),
                _json_dumps(row.get("snapshot_payload_json", {})),
                str(row.get("bundle_id") or ""),
                str(row.get("message") or ""),
                str(row.get("result_path") or ""),
                metadata_json,
                float(row.get("created_at") or time.time()),
                float(row.get("updated_at") or time.time()),
                row.get("started_at"),
                row.get("finished_at"),
                str(row.get("error_text") or ""),
            ),
        )
        return

    _conn(runtime).execute(
        """
        UPDATE workflow_runs
        SET status = ?,
            message = ?,
            result_path = ?,
            metadata_json = ?,
            updated_at = ?,
            started_at = ?,
            finished_at = ?,
            error_text = ?
        WHERE project_id = ? AND run_id = ?
        """,
        (
            str(row.get("status") or "pending"),
            str(row.get("message") or ""),
            str(row.get("result_path") or ""),
            metadata_json,
            float(row.get("updated_at") or time.time()),
            row.get("started_at"),
            row.get("finished_at"),
            str(row.get("error_text") or ""),
            str(row.get("project_id") or ""),
            str(row.get("run_id") or ""),
        ),
    )


def _sync_execution_and_task_for_run(runtime: Any, row: dict[str, Any]) -> None:
    now = float(row.get("updated_at") or time.time())
    workflow_status = str(row.get("status") or "failed")
    execution_status = _workflow_status_to_execution_status(workflow_status)
    error_text = str(row.get("error_text") or "")
    message = str(row.get("message") or "")
    if workflow_status == "cancelled" and not error_text:
        error_text = "Workflow run cancelled."
    if execution_status != "failed":
        error_text = ""
    completed_at = now if _is_terminal_workflow_status(workflow_status) else None
    _conn(runtime).execute(
        """
        UPDATE executions
        SET status = ?,
            completed_at = ?,
            error = ?
        WHERE execution_id = ?
        """,
        (
            execution_status,
            completed_at,
            error_text,
            str(row.get("execution_id") or ""),
        ),
    )
    task_updates = [
        "status = ?",
        "latest_execution_id = ?",
        "summary = ?",
        "updated_at = ?",
        "last_activity_at = ?",
    ]
    task_values: list[Any] = [
        _workflow_status_to_task_status(workflow_status),
        str(row.get("execution_id") or ""),
        message,
        now,
        now,
    ]
    result_snapshot = row.get("result_snapshot")
    if isinstance(result_snapshot, dict):
        task_updates.append("result_snapshot = ?")
        task_values.append(_json_dumps(result_snapshot))
    task_values.extend([str(row.get("project_id") or ""), str(row.get("task_id") or "")])
    _conn(runtime).execute(
        f"UPDATE tasks SET {', '.join(task_updates)} WHERE project_id = ? AND task_id = ?",
        tuple(task_values),
    )


def _commit_run_sync(runtime: Any, row: dict[str, Any], *, insert: bool) -> dict[str, Any]:
    conn = _conn(runtime)
    try:
        _write_workflow_run(runtime, row, insert=insert)
        _sync_execution_and_task_for_run(runtime, row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _get_workflow_run(runtime, project_id=str(row.get("project_id") or ""), run_id=str(row.get("run_id") or ""))


def _mark_run_failed(runtime: Any, row: dict[str, Any], message: str) -> dict[str, Any]:
    row["status"] = "failed"
    row["message"] = message
    row["error_text"] = message
    row["updated_at"] = time.time()
    row["finished_at"] = row["updated_at"]
    return _commit_run_sync(runtime, row, insert=False)


def _get_workflow_run(runtime: Any, *, project_id: str, run_id: str) -> dict[str, Any]:
    row = _conn(runtime).execute(
        "SELECT * FROM workflow_runs WHERE project_id = ? AND run_id = ?",
        (project_id, run_id),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Run not found: {run_id}")
    return _workflow_row_to_dict(row)


def _list_workflow_runs(runtime: Any, *, project_id: str) -> list[dict[str, Any]]:
    rows = _conn(runtime).execute(
        "SELECT * FROM workflow_runs WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ).fetchall()
    return [_workflow_row_to_dict(row) for row in rows]


def _list_task_workflow_runs(runtime: Any, *, project_id: str, task_id: str) -> list[dict[str, Any]]:
    rows = _conn(runtime).execute(
        """
        SELECT *
        FROM workflow_runs
        WHERE project_id = ? AND task_id = ?
        ORDER BY created_at DESC
        """,
        (project_id, task_id),
    ).fetchall()
    return [_workflow_row_to_dict(row) for row in rows]


def _upsert_workflow_result(runtime: Any, *, row: dict[str, Any], artifacts: list[dict[str, Any]] | None = None) -> None:
    now = time.time()
    result_items = artifacts if artifacts is not None else list(row.get("artifacts") or [])
    result_path = str(row.get("remote_output_dir") or row.get("local_run_dir") or row.get("result_path") or "")
    available_count = len([item for item in result_items if item.get("available")])
    summary = {
        "workflow_run_id": str(row.get("run_id") or ""),
        "artifact_count": len(result_items),
        "available_artifact_count": available_count,
        "updated_at": now,
        "result_path": result_path,
    }
    existing = _conn(runtime).execute(
        "SELECT workflow_result_id FROM workflow_results WHERE workflow_run_id = ? AND result_kind = ?",
        (str(row.get("run_id") or ""), "artifacts"),
    ).fetchone()
    if existing is None:
        _conn(runtime).execute(
            """
            INSERT INTO workflow_results (
                workflow_result_id, project_id, task_id, workflow_run_id,
                result_kind, summary_json, result_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"wres_{uuid.uuid4().hex[:12]}",
                str(row.get("project_id") or ""),
                str(row.get("task_id") or ""),
                str(row.get("run_id") or ""),
                "artifacts",
                _json_dumps(summary | {"artifacts": result_items}),
                result_path,
                now,
                now,
            ),
        )
    else:
        _conn(runtime).execute(
            "UPDATE workflow_results SET summary_json = ?, result_path = ?, updated_at = ? WHERE workflow_result_id = ?",
            (
                _json_dumps(summary | {"artifacts": result_items}),
                result_path,
                now,
                str(existing["workflow_result_id"]),
            ),
        )
    row["result_path"] = result_path
    row["result_snapshot"] = summary


def _result_viewer_contract(summary: dict[str, Any], *, project_id: str, task_id: str, result_id: str) -> tuple[str, str]:
    artifacts = summary.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            viewer = str(artifact.get("viewer_hint") or "").strip()
            artifact_type = str(artifact.get("artifact_type") or "").strip()
            if viewer == "html":
                return "html", "text/html"
            if viewer == "json" or artifact_type == "json":
                return "json", "application/json"
            if viewer == "table":
                return "table", "text/tab-separated-values"
            if viewer == "text" or artifact_type == "text":
                return "text", "text/plain"
    return "json", "application/json"


def _workflow_result_row_to_dict(row: Any, *, project_id: str, task_id: str) -> dict[str, Any]:
    item = dict(row)
    summary = _json_loads(item.get("summary_json", "{}"), default={})
    if not isinstance(summary, dict):
        summary = {}
    result_id = str(item.get("workflow_result_id") or "")
    viewer_kind, content_type = _result_viewer_contract(summary, project_id=project_id, task_id=task_id, result_id=result_id)
    return {
        "result_id": result_id,
        "task_id": str(item.get("task_id") or task_id),
        "run_id": str(item.get("workflow_run_id") or ""),
        "kind": str(item.get("result_kind") or "artifacts"),
        "summary": summary,
        "content_type": content_type,
        "viewer_kind": viewer_kind,
        "content_url": f"/api/v1/projects/{project_id}/tasks/{task_id}/results/{result_id}/content",
        "created_at": float(item.get("created_at") or 0.0),
        "updated_at": float(item.get("updated_at") or 0.0),
        "result_path": str(item.get("result_path") or ""),
    }


def _get_workflow_result(runtime: Any, *, project_id: str, task_id: str, result_id: str) -> dict[str, Any]:
    row = _conn(runtime).execute(
        """
        SELECT *
        FROM workflow_results
        WHERE project_id = ? AND task_id = ? AND workflow_result_id = ?
        """,
        (project_id, task_id, result_id),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Result not found: {result_id}")
    return _workflow_result_row_to_dict(row, project_id=project_id, task_id=task_id)


def list_runs(runtime: Any, *, project_id: str) -> list[dict[str, Any]]:
    runtime._ensure_project_open(project_id)
    return _list_workflow_runs(runtime, project_id=project_id)


def list_task_runs(runtime: Any, *, project_id: str, task_id: str) -> list[dict[str, Any]]:
    runtime._ensure_project_open(project_id)
    runtime._assert_task_exists(project_id=project_id, task_id=task_id)
    return _list_task_workflow_runs(runtime, project_id=project_id, task_id=task_id)


def get_run(runtime: Any, *, project_id: str, run_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    row = _get_workflow_run(runtime, project_id=project_id, run_id=str(run_id or "").strip())
    runtime._ensure_ssh_connected()
    backend = runtime._workflow_backend_for_row(row)
    remote_task_dir = str(row.get("remote_task_dir") or "").strip()
    if not remote_task_dir:
        return row
    remote_status = backend.query_run(ssh_run_fn=runtime._run_ssh_command, row=row)
    row["remote_status"] = remote_status
    row["status"] = str(remote_status.get("stage") or row.get("status") or "pending")
    row["updated_at"] = time.time()
    if row["status"] == "running" and not row.get("started_at"):
        row["started_at"] = row["updated_at"]
    if _is_terminal_workflow_status(row["status"]):
        row["finished_at"] = row["updated_at"]
    if remote_status.get("log_tail"):
        row["message"] = str(remote_status["log_tail"]).splitlines()[-1]
    return _commit_run_sync(runtime, row, insert=False)


def get_task_run(runtime: Any, *, project_id: str, task_id: str, run_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    runtime._assert_task_exists(project_id=project_id, task_id=task_id)
    row = get_run(runtime, project_id=project_id, run_id=run_id)
    if str(row.get("task_id") or "") != str(task_id or ""):
        raise RuntimeError(f"Run {run_id} does not belong to task {task_id}")
    return row


def create_run(runtime: Any, *, project_id: str, task_id: str, launch: dict[str, Any]) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        raise RuntimeError("task_id is required")
    runtime._assert_task_exists(project_id=project_id, task_id=normalized_task_id)
    snapshot = _require_current_snapshot(runtime, project_id=project_id, task_id=normalized_task_id)
    workflow_payload = snapshot.get("workflow_definition_json")
    if not isinstance(workflow_payload, dict):
        raise RuntimeError(f"Task {normalized_task_id} has invalid current workflow snapshot")
    workflow_spec = runtime._build_workflow_spec(workflow_payload)
    launch_spec = runtime._build_launch_spec(project_id=project_id, launch=launch)
    compiled = compile_workflow_bundle(
        workflow_spec,
        launch_spec,
        plugin_registry=runtime._service_locator.plugin_registry,
    )
    runtime._ensure_ssh_connected()
    ssh = runtime._service_locator.ssh_service
    project = runtime._project_manager.current_project
    project_dir = runtime._project_manager.current_project_dir
    if ssh is None or project is None or project_dir is None:
        raise RuntimeError("Current project or SSH service is not available")

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    layout = prepare_workflow_run_layout(
        project_dir=project_dir,
        remote_base=project.remote_base,
        run_id=run_id,
        compiled_bundle=compiled,
        launch=launch_spec,
    )
    now = time.time()
    execution_id = _create_execution_row(
        runtime,
        task_id=normalized_task_id,
        workflow_spec=workflow_spec,
        launch_spec=launch_spec,
        snapshot_id=str(snapshot["workflow_snapshot_id"]),
        snapshot_hash=str(snapshot["workflow_hash"]),
    )
    record = RunRecord(
        run_id=run_id,
        project_id=project_id,
        task_id=normalized_task_id,
        workflow_snapshot_id=str(snapshot["workflow_snapshot_id"]),
        execution_id=execution_id,
        workflow_id=workflow_spec.workflow_id,
        profile_id=launch_spec.profile.profile_id,
        status="pending",
        snapshot_hash=str(snapshot["workflow_hash"]),
        created_at=now,
        updated_at=now,
        snapshot_payload_json=workflow_payload,
        bundle_id=str(compiled.get("bundle_id") or ""),
        message="Workflow bundle prepared; awaiting backend submission.",
    )
    row = record.to_dict()
    row.update(layout)
    row["profile"] = launch_spec.profile.to_dict()
    row["resume"] = launch_spec.resume
    row["backend_kind"] = ""
    row["executor"] = launch_spec.profile.executor
    row["packaging_mode"] = launch_spec.profile.packaging_mode
    row["container_runtime"] = launch_spec.profile.container_runtime
    row["artifacts"] = []
    row["result_path"] = str(layout.get("remote_output_dir") or "")
    created = _commit_run_sync(runtime, row, insert=True)
    backend = create_workflow_backend(launch_spec.profile)
    try:
        submission = backend.submit_prepared_run(
            ssh_service=ssh,
            ssh_run_fn=runtime._run_ssh_command,
            layout=layout,
            launch=launch_spec,
        )
    except Exception as exc:
        return _mark_run_failed(runtime, created, str(exc))

    created["updated_at"] = time.time()
    created["message"] = "Workflow bundle uploaded and backend submitted."
    created["backend_kind"] = str(submission.get("backend_kind") or "")
    created["launcher_pid"] = str(submission.get("launcher_pid") or "")
    created["scheduler_job_id"] = str(submission.get("scheduler_job_id") or "")
    _upsert_workflow_result(runtime, row=created, artifacts=[])
    return _commit_run_sync(runtime, created, insert=False)


def create_task_run(runtime: Any, *, project_id: str, task_id: str, launch: dict[str, Any]) -> dict[str, Any]:
    return create_run(runtime, project_id=project_id, task_id=task_id, launch=launch)


def cancel_run(runtime: Any, *, project_id: str, run_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    row = _get_workflow_run(runtime, project_id=project_id, run_id=str(run_id or "").strip())
    runtime._ensure_ssh_connected()
    backend = runtime._workflow_backend_for_row(row)
    remote_status = backend.cancel_run(ssh_run_fn=runtime._run_ssh_command, row=row)
    row["remote_status"] = remote_status
    row["status"] = "cancelled"
    row["updated_at"] = time.time()
    row["finished_at"] = row["updated_at"]
    row["message"] = "Workflow run cancellation requested."
    row["error_text"] = "Workflow run cancelled."
    if remote_status.get("launcher_pid"):
        row["launcher_pid"] = remote_status["launcher_pid"]
    if remote_status.get("nextflow_pid"):
        row["nextflow_pid"] = remote_status["nextflow_pid"]
    return _commit_run_sync(runtime, row, insert=False)


def cancel_task_run(runtime: Any, *, project_id: str, task_id: str, run_id: str) -> dict[str, Any]:
    row = get_task_run(runtime, project_id=project_id, task_id=task_id, run_id=run_id)
    return cancel_run(runtime, project_id=project_id, run_id=str(row.get("run_id") or ""))


def get_run_artifacts(runtime: Any, *, project_id: str, run_id: str) -> list[dict[str, Any]]:
    runtime._ensure_project_open(project_id)
    row = _get_workflow_run(runtime, project_id=project_id, run_id=str(run_id or "").strip())
    runtime._ensure_ssh_connected()
    ssh = runtime._service_locator.ssh_service
    project_dir = runtime._project_manager.current_project_dir
    if ssh is None or project_dir is None:
        raise RuntimeError("Run artifacts are unavailable without SSH and current project directory")
    backend = runtime._workflow_backend_for_row(row)
    artifacts = backend.collect_artifacts(
        ssh_service=ssh,
        project_dir=project_dir,
        run_id=str(run_id or "").strip(),
        row=row,
    )
    row["artifacts"] = artifacts
    row["updated_at"] = time.time()
    _upsert_workflow_result(runtime, row=row, artifacts=artifacts)
    _commit_run_sync(runtime, row, insert=False)
    return artifacts


def get_task_workflow(runtime: Any, *, project_id: str, task_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    runtime._assert_task_exists(project_id=project_id, task_id=task_id)
    snapshot = _require_current_snapshot(runtime, project_id=project_id, task_id=task_id)
    workflow_payload = snapshot.get("workflow_definition_json")
    params_schema = snapshot.get("params_schema_json")
    if not isinstance(workflow_payload, dict):
        workflow_payload = {}
    if not isinstance(params_schema, dict):
        params_schema = {}
    return {
        "task_id": str(snapshot.get("task_id") or task_id),
        "project_id": str(snapshot.get("project_id") or project_id),
        "workflow_snapshot_id": str(snapshot.get("workflow_snapshot_id") or ""),
        "workflow_hash": str(snapshot.get("workflow_hash") or ""),
        "workflow_id": str(snapshot.get("workflow_id") or ""),
        "name": str(snapshot.get("name") or ""),
        "version": str(snapshot.get("version") or "0.1.0"),
        "workflow": workflow_payload,
        "params_schema": params_schema,
        "created_at": float(snapshot.get("created_at") or 0.0),
        "updated_at": float(snapshot.get("updated_at") or 0.0),
    }


def put_task_workflow(runtime: Any, *, project_id: str, task_id: str, workflow: dict[str, Any]) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    runtime._assert_task_exists(project_id=project_id, task_id=task_id)
    snapshot = upsert_task_workflow_snapshot(
        runtime,
        project_id=project_id,
        task_id=task_id,
        workflow_payload=runtime._build_workflow_spec(workflow).to_dict(),
    )
    now = time.time()
    _conn(runtime).execute(
        "UPDATE tasks SET updated_at = ?, last_activity_at = ? WHERE project_id = ? AND task_id = ?",
        (now, now, project_id, task_id),
    )
    _conn(runtime).commit()
    return get_task_workflow(runtime, project_id=project_id, task_id=task_id)


def compile_task_workflow(runtime: Any, *, project_id: str, task_id: str, launch: dict[str, Any]) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    snapshot = _require_current_snapshot(runtime, project_id=project_id, task_id=task_id)
    workflow_payload = snapshot.get("workflow_definition_json")
    if not isinstance(workflow_payload, dict):
        raise RuntimeError(f"Task {task_id} has invalid current workflow snapshot")
    workflow_spec = runtime._build_workflow_spec(workflow_payload)
    launch_spec = runtime._build_launch_spec(project_id=project_id, launch=launch)
    return compile_workflow_bundle(
        workflow_spec,
        launch_spec,
        plugin_registry=runtime._service_locator.plugin_registry,
    )


def get_task_workflow_compatibility(runtime: Any, *, project_id: str, task_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    snapshot = _require_current_snapshot(runtime, project_id=project_id, task_id=task_id)
    workflow_payload = snapshot.get("workflow_definition_json")
    if not isinstance(workflow_payload, dict):
        workflow_payload = {}
    response = {
        "task_id": task_id,
        "workflow_snapshot_id": str(snapshot.get("workflow_snapshot_id") or ""),
        "workflow_id": str(snapshot.get("workflow_id") or ""),
        "compatible": False,
        "reasons": [],
        "preflight": None,
        "recommended_profile": "",
        "recommended_profile_details": None,
        "runtime_capabilities": None,
    }
    try:
        preflight = runtime.get_ssh_preflight()
        response["preflight"] = preflight
        response["recommended_profile"] = str(preflight.get("recommended_profile") or "")
        response["recommended_profile_details"] = preflight.get("recommended_profile_details")
        response["runtime_capabilities"] = preflight.get("runtime_capabilities")
        response["compatible"] = bool(preflight.get("ok"))
        response["reasons"] = list(preflight.get("failures") or [])
    except Exception as exc:
        response["compatible"] = False
        response["reasons"] = [str(exc)]
    return response


def list_task_results(runtime: Any, *, project_id: str, task_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
    runtime._ensure_project_open(project_id)
    runtime._assert_task_exists(project_id=project_id, task_id=task_id)
    normalized_run_id = str(run_id or "").strip()
    if normalized_run_id:
        rows = _conn(runtime).execute(
            """
            SELECT *
            FROM workflow_results
            WHERE project_id = ? AND task_id = ? AND workflow_run_id = ?
            ORDER BY created_at DESC
            """,
            (project_id, task_id, normalized_run_id),
        ).fetchall()
    else:
        rows = _conn(runtime).execute(
            """
            SELECT *
            FROM workflow_results
            WHERE project_id = ? AND task_id = ?
            ORDER BY created_at DESC
            """,
            (project_id, task_id),
        ).fetchall()
    return [_workflow_result_row_to_dict(row, project_id=project_id, task_id=task_id) for row in rows]


def get_task_results_summary(runtime: Any, *, project_id: str, task_id: str, run_id: str | None = None) -> dict[str, Any]:
    results = list_task_results(runtime, project_id=project_id, task_id=task_id, run_id=run_id)
    latest = results[0] if results else None
    return {
        "task_id": task_id,
        "run_id": str(run_id or "") or (latest["run_id"] if latest else ""),
        "total": len(results),
        "latest_result_id": latest["result_id"] if latest else "",
        "latest_run_id": latest["run_id"] if latest else "",
        "kinds": sorted({str(item.get("kind") or "") for item in results if str(item.get("kind") or "")}),
    }


def get_task_result(runtime: Any, *, project_id: str, task_id: str, result_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    runtime._assert_task_exists(project_id=project_id, task_id=task_id)
    return _get_workflow_result(runtime, project_id=project_id, task_id=task_id, result_id=result_id)


def get_task_result_content(runtime: Any, *, project_id: str, task_id: str, result_id: str) -> dict[str, Any]:
    item = get_task_result(runtime, project_id=project_id, task_id=task_id, result_id=result_id)
    summary = item.get("summary")
    content: Any = summary
    if isinstance(summary, dict):
        artifacts = summary.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    continue
                local_path = str(artifact.get("local_path") or "").strip()
                viewer_hint = str(artifact.get("viewer_hint") or "").strip()
                if not local_path:
                    continue
                path = Path(local_path)
                if not path.exists():
                    continue
                if viewer_hint in {"html", "json", "text", "table"}:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    break
    return {
        "result_id": item["result_id"],
        "viewer_kind": item["viewer_kind"],
        "content_type": item["content_type"],
        "content": content,
    }


def get_task_workspace(runtime: Any, *, project_id: str, task_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    task = runtime.get_task(project_id=project_id, task_id=task_id)
    workflow_snapshot = get_task_workflow(runtime, project_id=project_id, task_id=task_id)
    runs = list_task_runs(runtime, project_id=project_id, task_id=task_id)
    results_summary = get_task_results_summary(runtime, project_id=project_id, task_id=task_id)
    latest_run = runs[0] if runs else None
    runs_summary = {
        "total": len(runs),
        "latest_run_id": latest_run["run_id"] if latest_run else "",
        "running": len([item for item in runs if item.get("status") == "running"]),
        "failed": len([item for item in runs if item.get("status") == "failed"]),
        "completed": len([item for item in runs if item.get("status") == "completed"]),
        "cancelled": len([item for item in runs if item.get("status") == "cancelled"]),
    }
    workspace = {
        "task": task,
        "workflow_snapshot": workflow_snapshot,
        "runs_summary": runs_summary,
        "results_summary": results_summary,
    }
    if latest_run is not None:
        workspace["latest_run"] = latest_run
    try:
        workspace["runtime_readiness"] = runtime.get_ssh_preflight()
    except Exception:
        pass
    try:
        workspace["compatibility"] = get_task_workflow_compatibility(runtime, project_id=project_id, task_id=task_id)
    except Exception:
        pass
    return workspace


def get_run_resolved_config(runtime: Any, *, project_id: str, run_id: str) -> dict[str, Any]:
    runtime._ensure_project_open(project_id)
    row = _get_workflow_run(runtime, project_id=project_id, run_id=str(run_id or "").strip())
    resolved_config_path = str(row.get("resolved_config_path") or "").strip()
    if not resolved_config_path:
        raise RuntimeError(f"Run {run_id} 缺少 resolved_config_path")
    path = Path(resolved_config_path)
    if not path.exists():
        raise RuntimeError(f"resolved config 不存在: {resolved_config_path}")
    return {"path": resolved_config_path, "content": path.read_text(encoding="utf-8")}
