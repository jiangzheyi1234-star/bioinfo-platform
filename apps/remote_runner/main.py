from __future__ import annotations

from fastapi import FastAPI

from .database_routes import router as database_router
from .execution_query_routes import router as execution_query_router
from .health_routes import router as health_router
from .pipeline_routes import router as pipeline_router
from .route_errors import register_exception_handlers
from .submission_routes import router as submission_router
from .tool_routes import router as tool_router
from .workflow_design_routes import router as workflow_design_router


app = FastAPI(title="H2OMeta Remote Runner", version="0.1.1-control-plane")
register_exception_handlers(app)
app.include_router(health_router)
app.include_router(pipeline_router)
app.include_router(submission_router)
app.include_router(execution_query_router)
app.include_router(database_router)
app.include_router(tool_router)
app.include_router(workflow_design_router)
