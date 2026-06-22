from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .audit_routes import router as audit_router
from .database_routes import router as database_router
from .execution_query_routes import router as execution_query_router
from .health_routes import router as health_router
from .pipeline_routes import router as pipeline_router
from .route_errors import register_exception_handlers
from .worker_supervisor import start_configured_run_worker_supervisor, start_configured_tool_prepare_worker_supervisor
from .submission_routes import router as submission_router
from .tool_routes import router as tool_router
from .workflow_design_routes import router as workflow_design_router
from .workflow_trigger_routes import router as workflow_trigger_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    supervisors = [
        supervisor
        for supervisor in (
            start_configured_run_worker_supervisor(),
            start_configured_tool_prepare_worker_supervisor(),
        )
        if supervisor is not None
    ]
    if supervisors:
        app.state.worker_supervisors = supervisors
    try:
        yield
    finally:
        for supervisor in supervisors:
            supervisor.stop()


app = FastAPI(title="H2OMeta Remote Runner", version="0.1.1-control-plane", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(pipeline_router)
app.include_router(submission_router)
app.include_router(execution_query_router)
app.include_router(database_router)
app.include_router(tool_router)
app.include_router(workflow_design_router)
app.include_router(workflow_trigger_router)
app.include_router(audit_router)
