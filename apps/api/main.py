"""FastAPI app for desktop-shell migration."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from apps.api.models import (
    CompileWorkflowRequest,
    CreateRunRequest,
    CreateProjectRequest,
    CreateTaskRequest,
    CreateSampleRequest,
    DatabaseInstallRequest,
    RemoteEnvInstallRequest,
    SSHConnectionRequest,
    TaskWorkflowCompileRequest,
    TaskWorkflowRequest,
    UpdateProjectRequest,
    UpdateTaskRequest,
    UpdateSettingsRequest,
)
from apps.api.runtime import get_runtime_service
from core.app_runtime import RuntimeServiceError

app = FastAPI(
    title="H2OMeta Local API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _runtime():
    return get_runtime_service()


@app.on_event("startup")
async def on_startup() -> None:
    _runtime()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    runtime = get_runtime_service()
    runtime.shutdown()
    get_runtime_service.cache_clear()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/workflows/compile")
async def compile_workflow(payload: CompileWorkflowRequest) -> dict[str, Any]:
    try:
        return {
            "item": _runtime().compile_workflow(
                project_id=payload.project_id,
                workflow=payload.workflow.model_dump(),
                launch=payload.launch.model_dump(),
            )
        }
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/runs")
async def list_runs(project_id: str) -> dict[str, Any]:
    try:
        return {"items": _runtime().list_runs(project_id=project_id)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/runs/{run_id}")
async def get_run(project_id: str, run_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_run(project_id=project_id, run_id=run_id)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/runs")
async def create_run(payload: CreateRunRequest) -> dict[str, Any]:
    try:
        return {
            "item": _runtime().create_run(
                project_id=payload.project_id,
                task_id=payload.task_id,
                launch=payload.launch.model_dump(),
            )
        }
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/runs/{run_id}/cancel")
async def cancel_run(project_id: str, run_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().cancel_run(project_id=project_id, run_id=run_id)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/runs/{run_id}/artifacts")
async def get_run_artifacts(project_id: str, run_id: str) -> dict[str, Any]:
    try:
        return {"items": _runtime().get_run_artifacts(project_id=project_id, run_id=run_id)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/runs/{run_id}/resolved-config")
async def get_run_resolved_config(project_id: str, run_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_run_resolved_config(project_id=project_id, run_id=run_id)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/servers/{server_id}/doctor")
async def doctor_server(server_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().doctor_server(server_id=server_id)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/workflows/tools/{tool_id}/descriptor")
async def get_workflow_tool_descriptor(tool_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_tool_descriptor(tool_id=tool_id)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/settings")
async def get_settings() -> dict[str, Any]:
    try:
        return {"item": _runtime().get_settings()}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/v1/settings")
async def update_settings(payload: UpdateSettingsRequest) -> dict[str, Any]:
    try:
        return {"item": _runtime().update_settings(payload.patch)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/ssh/status")
async def get_ssh_status() -> dict[str, Any]:
    try:
        return {"item": _runtime().get_ssh_status()}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/ssh/connect")
async def connect_ssh(payload: SSHConnectionRequest | None = None) -> dict[str, Any]:
    try:
        patch = payload.model_dump(exclude_none=True) if payload is not None else None
        return {"item": _runtime().connect_ssh(patch)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/ssh/disconnect")
async def disconnect_ssh() -> dict[str, Any]:
    try:
        return {"item": _runtime().disconnect_ssh()}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/ssh/test")
async def test_ssh_connection(payload: SSHConnectionRequest | None = None) -> dict[str, Any]:
    try:
        patch = payload.model_dump(exclude_none=True) if payload is not None else None
        return {"item": _runtime().test_ssh_connection(patch)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/ssh/preflight")
async def run_ssh_preflight() -> dict[str, Any]:
    try:
        return {"item": _runtime().get_ssh_preflight()}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/ssh/env/status")
async def get_remote_env_status() -> dict[str, Any]:
    try:
        return {"item": _runtime().get_remote_env_status()}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/ssh/env/install")
async def install_remote_env(payload: RemoteEnvInstallRequest) -> dict[str, Any]:
    try:
        return {
            "item": _runtime().install_remote_env(
                target=payload.target,
                tool_id=payload.tool_id or "",
                profile_kind=payload.profile_kind or "",
            )
        }
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/ssh/env/install/{job_id}")
async def get_remote_env_install_status(job_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_remote_env_install_status(job_id=job_id)}
    except (RuntimeServiceError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects")
async def list_projects(sort_by: str = "created_at", include_archived: bool = False) -> dict[str, Any]:
    try:
        return {"items": _runtime().list_projects(sort_by=sort_by, include_archived=include_archived)}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/current")
async def get_current_project() -> dict[str, Any]:
    try:
        return {"item": _runtime().get_current_project()}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects")
async def create_project(payload: CreateProjectRequest) -> dict[str, Any]:
    try:
        item = _runtime().create_project(
            name=payload.name,
            description=payload.description,
            open_after_create=payload.open_after_create,
        )
        return {"item": item}
    except (RuntimeServiceError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/v1/projects/{project_id}")
async def update_project(project_id: str, payload: UpdateProjectRequest) -> dict[str, Any]:
    try:
        patch = payload.model_dump(exclude_none=True)
        return {"item": _runtime().update_project(project_id=project_id, patch=patch)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/archive")
async def archive_project(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().archive_project(project_id=project_id)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/restore")
async def restore_project(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().restore_project(project_id=project_id)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().delete_project(project_id=project_id)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/open")
async def open_project(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().open_project(project_id)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks")
async def list_tasks(project_id: str) -> dict[str, Any]:
    try:
        items = _runtime().list_tasks(project_id=project_id)
        return {"items": items, "total": len(items)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/tasks")
async def create_task(project_id: str, payload: CreateTaskRequest) -> dict[str, Any]:
    try:
        return {
            "item": _runtime().create_task(
                project_id=project_id,
                title=payload.title,
                description=payload.description,
            )
        }
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks/{task_id}")
async def get_task(project_id: str, task_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_task(project_id=project_id, task_id=task_id)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/v1/projects/{project_id}/tasks/{task_id}")
async def update_task(project_id: str, task_id: str, payload: UpdateTaskRequest) -> dict[str, Any]:
    try:
        patch = payload.model_dump(exclude_none=True)
        return {"item": _runtime().update_task(project_id=project_id, task_id=task_id, patch=patch)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/projects/{project_id}/tasks/{task_id}")
async def delete_task(project_id: str, task_id: str) -> dict[str, Any]:
    try:
        return _runtime().delete_task(project_id=project_id, task_id=task_id)
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks/{task_id}/workflow")
async def get_task_workflow(project_id: str, task_id: str) -> dict[str, Any]:
    try:
        return _runtime().get_task_workflow(project_id=project_id, task_id=task_id)
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/v1/projects/{project_id}/tasks/{task_id}/workflow")
async def put_task_workflow(project_id: str, task_id: str, payload: TaskWorkflowRequest) -> dict[str, Any]:
    try:
        return _runtime().put_task_workflow(
            project_id=project_id,
            task_id=task_id,
            workflow=payload.workflow.model_dump(),
        )
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/tasks/{task_id}/workflow/compile")
async def compile_task_workflow(project_id: str, task_id: str, payload: TaskWorkflowCompileRequest) -> dict[str, Any]:
    try:
        return _runtime().compile_task_workflow(
            project_id=project_id,
            task_id=task_id,
            launch=payload.launch.model_dump(),
        )
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/tasks/{task_id}/workflow/compatibility")
async def get_task_workflow_compatibility(project_id: str, task_id: str) -> dict[str, Any]:
    try:
        return _runtime().get_task_workflow_compatibility(project_id=project_id, task_id=task_id)
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks/{task_id}/runs")
async def list_task_runs(project_id: str, task_id: str) -> dict[str, Any]:
    try:
        items = _runtime().list_task_runs(project_id=project_id, task_id=task_id)
        return {"items": items, "total": len(items)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/tasks/{task_id}/runs")
async def create_task_run(project_id: str, task_id: str, payload: TaskWorkflowCompileRequest) -> dict[str, Any]:
    try:
        return _runtime().create_task_run(
            project_id=project_id,
            task_id=task_id,
            launch=payload.launch.model_dump(),
        )
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks/{task_id}/runs/{run_id}")
async def get_task_run(project_id: str, task_id: str, run_id: str) -> dict[str, Any]:
    try:
        return _runtime().get_task_run(project_id=project_id, task_id=task_id, run_id=run_id)
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/tasks/{task_id}/runs/{run_id}/cancel")
async def cancel_task_run(project_id: str, task_id: str, run_id: str) -> dict[str, Any]:
    try:
        return _runtime().cancel_task_run(project_id=project_id, task_id=task_id, run_id=run_id)
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks/{task_id}/results")
async def list_task_results(project_id: str, task_id: str, run_id: str | None = None) -> dict[str, Any]:
    try:
        items = _runtime().list_task_results(project_id=project_id, task_id=task_id, run_id=run_id)
        return {"items": items, "total": len(items)}
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks/{task_id}/results/summary")
async def get_task_results_summary(project_id: str, task_id: str, run_id: str | None = None) -> dict[str, Any]:
    try:
        return _runtime().get_task_results_summary(project_id=project_id, task_id=task_id, run_id=run_id)
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks/{task_id}/results/{result_id}")
async def get_task_result(project_id: str, task_id: str, result_id: str) -> dict[str, Any]:
    try:
        return _runtime().get_task_result(project_id=project_id, task_id=task_id, result_id=result_id)
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks/{task_id}/results/{result_id}/content")
async def get_task_result_content(project_id: str, task_id: str, result_id: str) -> dict[str, Any]:
    try:
        return _runtime().get_task_result_content(project_id=project_id, task_id=task_id, result_id=result_id)
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/tasks/{task_id}/workspace")
async def get_task_workspace(project_id: str, task_id: str) -> dict[str, Any]:
    try:
        return _runtime().get_task_workspace(project_id=project_id, task_id=task_id)
    except (RuntimeServiceError, ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/samples")
async def list_samples(project_id: str) -> dict[str, Any]:
    try:
        return {"items": _runtime().list_samples(project_id=project_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/samples")
async def create_sample(project_id: str, payload: CreateSampleRequest) -> dict[str, Any]:
    try:
        item = _runtime().create_sample(
            project_id=project_id,
            name=payload.name,
            source=payload.source,
            metadata=payload.metadata,
        )
        return {"item": item}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/databases")
async def list_databases(project_id: str, include_status: bool = False) -> dict[str, Any]:
    try:
        return {"items": _runtime().list_databases(project_id=project_id, include_status=include_status)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/databases/{db_id}/install")
async def install_database(project_id: str, db_id: str, payload: DatabaseInstallRequest | None = None) -> dict[str, Any]:
    try:
        mirror_index = payload.mirror_index if payload is not None else 0
        return {"item": _runtime().install_database(project_id=project_id, db_id=db_id, mirror_index=mirror_index)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/databases/{db_id}/install")
async def get_database_install_status(project_id: str, db_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_database_install_status(project_id=project_id, db_id=db_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/logs/app")
async def read_app_log(tail_lines: int = 200) -> dict[str, Any]:
    try:
        return {"item": _runtime().read_app_log(tail_lines=tail_lines)}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/events/executions")
async def list_runtime_events(after_seq: int = 0, limit: int = 200) -> dict[str, Any]:
    try:
        return {"item": _runtime().list_runtime_events(after_seq=after_seq, limit=limit)}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
