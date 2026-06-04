"""FastAPI app for desktop-shell migration."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.database_routes import router as database_router
from apps.api.execution_query_routes import router as execution_query_router
from apps.api.lifespan import lifespan
from apps.api.route_errors import register_exception_handlers
from apps.api.ssh_routes import router as ssh_router
from apps.api.submission_routes import router as submission_router
from apps.api.system_routes import router as system_router
from apps.api.tool_capability_routes import router as tool_capability_router
from apps.api.tool_contract_routes import router as tool_contract_router
from apps.api.tool_routes import router as tool_router
from apps.api.workflow_catalog_routes import router as workflow_catalog_router
from apps.api.workflow_design_routes import router as workflow_design_router
from apps.api.workflow_sample_data_routes import router as workflow_sample_data_router


app = FastAPI(
    title="H2OMeta Local API",
    version="0.1.0",
    lifespan=lifespan,
)
register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3765",
        "http://127.0.0.1:3765",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router)
app.include_router(tool_capability_router)
app.include_router(tool_contract_router)
app.include_router(tool_router)
app.include_router(execution_query_router)
app.include_router(submission_router)
app.include_router(ssh_router)
app.include_router(workflow_catalog_router)
app.include_router(workflow_design_router)
app.include_router(workflow_sample_data_router)
app.include_router(database_router)
