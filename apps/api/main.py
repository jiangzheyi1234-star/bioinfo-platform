"""FastAPI app for desktop-shell migration."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from apps.api.models import (
    CreateProjectRequest,
    CreateSampleRequest,
    RunWorkbenchToolRequest,
    SSHConnectionRequest,
    SubmitExecutionRequest,
    UpdateSettingsRequest,
)
from apps.api.runtime import get_runtime_service
from core.app_runtime import ExecutionSubmitRequest, RuntimeServiceError

app = FastAPI(
    title="H2OMeta Local API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
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


@app.get("/api/v1/tools")
async def list_tools() -> dict[str, Any]:
    try:
        return {"items": _runtime().list_tools()}
    except RuntimeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/tools/{tool_id}/descriptor")
async def get_tool_descriptor(tool_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_tool_descriptor(tool_id=tool_id)}
    except RuntimeServiceError as exc:
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


@app.get("/api/v1/projects")
async def list_projects(sort_by: str = "created_at") -> dict[str, Any]:
    try:
        return {"items": _runtime().list_projects(sort_by=sort_by)}
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


@app.post("/api/v1/projects/{project_id}/open")
async def open_project(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().open_project(project_id)}
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


@app.get("/api/v1/projects/{project_id}/workbench/tools")
async def list_workbench_tools(project_id: str) -> dict[str, Any]:
    try:
        return {"items": _runtime().list_workbench_tools(project_id=project_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/workbench/config")
async def get_workbench_config(project_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_workbench_config(project_id=project_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/workbench/history")
async def get_workbench_history(project_id: str) -> dict[str, Any]:
    try:
        return {"items": _runtime().get_workbench_history(project_id=project_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/workbench/configured-databases")
async def get_workbench_configured_databases(project_id: str) -> dict[str, Any]:
    try:
        runtime = _runtime()
        runtime.open_project(project_id)
        settings = runtime.get_settings()
        databases_cfg = settings.get("databases", {})
        if not isinstance(databases_cfg, dict):
            raise RuntimeServiceError("settings.databases must be an object")

        items: list[dict[str, str]] = []
        db_root = str(databases_cfg.get("db_root", "") or "").strip()
        if db_root:
            items.append(
                {
                    "key": "db_root",
                    "path": db_root,
                    "label": f"db_root: {db_root}",
                }
            )
        overrides = databases_cfg.get("overrides", {})
        if isinstance(overrides, dict):
            for key in sorted(overrides.keys()):
                value = str(overrides.get(key, "") or "").strip()
                if not value:
                    continue
                items.append(
                    {
                        "key": str(key),
                        "path": value,
                        "label": f"{key}: {value}",
                    }
                )
        return {"items": items}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/workbench/executions/{execution_id}/result")
async def get_workbench_result(project_id: str, execution_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_workbench_result(project_id=project_id, execution_id=execution_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/v1/projects/{project_id}/workbench/executions/{execution_id}")
async def delete_workbench_execution(project_id: str, execution_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().archive_execution(project_id=project_id, execution_id=execution_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/workbench/executions/{execution_id}/remote-status")
async def get_workbench_remote_status(project_id: str, execution_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_workbench_remote_status(project_id=project_id, execution_id=execution_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/workbench/primer-results")
async def get_workbench_remote_primer_results(project_id: str, remote_result_dir: str) -> dict[str, Any]:
    try:
        return {
            "item": _runtime().get_workbench_remote_primer_results(
                project_id=project_id,
                remote_result_dir=remote_result_dir,
            )
        }
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/executions")
async def list_executions(project_id: str, limit: int = 50, archived: bool = False) -> dict[str, Any]:
    try:
        items = _runtime().list_executions(project_id=project_id, limit=limit, archived=archived)
        return {"items": items}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/executions/{execution_id}")
async def get_execution(project_id: str, execution_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().get_execution(project_id=project_id, execution_id=execution_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/projects/{project_id}/history")
async def list_execution_history(project_id: str, limit: int = 50) -> dict[str, Any]:
    try:
        return {"items": _runtime().list_execution_history(project_id=project_id, limit=limit)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/projects/{project_id}/executions/{execution_id}/archive")
async def archive_execution(project_id: str, execution_id: str) -> dict[str, Any]:
    try:
        return {"item": _runtime().archive_execution(project_id=project_id, execution_id=execution_id)}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/executions")
async def submit_execution(payload: SubmitExecutionRequest) -> dict[str, Any]:
    try:
        item = _runtime().submit_execution(
            ExecutionSubmitRequest(
                project_id=payload.project_id,
                tool_id=payload.tool_id,
                input_data_ids=payload.input_data_ids,
                parameters=payload.parameters,
                sample_id=payload.sample_id,
                sample_name=payload.sample_name,
                sample_source=payload.sample_source,
                sample_metadata=payload.sample_metadata,
                triggered_by=payload.triggered_by,
                database_paths=payload.database_paths,
            )
        )
        return {"item": item}
    except (RuntimeServiceError, KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/workbench/run")
async def run_workbench_tool(payload: RunWorkbenchToolRequest) -> dict[str, Any]:
    try:
        item = _runtime().run_workbench_tool(
            project_id=payload.project_id,
            tool_id=payload.tool_id,
            params=payload.params,
        )
        return {"item": item}
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
