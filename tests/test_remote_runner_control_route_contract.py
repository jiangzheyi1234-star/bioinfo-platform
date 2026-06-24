from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_result_preview_file_io_lives_in_service_not_route() -> None:
    main_source = _source("apps/remote_runner/main.py")
    control_source = _source("apps/remote_runner/control_service.py")
    service_source = _source("apps/remote_runner/result_preview_service.py")

    assert "from .result_preview_service import build_result_preview_data" not in main_source
    assert "build_result_preview_data(" not in main_source
    assert "run_sync(build_result_preview_data, cfg, result_id, artifact_id)" in control_source
    assert "run_sync(build_result_artifact_audit, cfg, result_id)" in control_source
    assert "ResultPackageExportRequest" in control_source
    assert "include_artifacts=request.includeArtifacts" in control_source
    assert "actor=request.actor" in control_source
    assert "_read_preview_text" not in main_source
    assert "Path(path)" not in main_source
    assert "MAX_PREVIEW_BYTES" not in main_source

    assert "def build_result_preview_data(" in service_source
    assert "def _read_preview_text(" in service_source
    assert "MAX_PREVIEW_BYTES = 256 * 1024" in service_source
    assert "from .artifact_product_service import build_result_artifact_audit, export_result_package" in control_source


def test_run_create_route_delegates_submission_to_service() -> None:
    route_source = _source("apps/remote_runner/submission_routes.py")
    control_source = _source("apps/remote_runner/control_service.py")
    service_source = _source("apps/remote_runner/submission_service.py")
    lifecycle_source = _source("tests/test_remote_runner_api_lifecycle.py")
    workflow_drafts_source = _source("tests/test_workflow_design_drafts.py")
    workflow_draft_api_lifecycle_source = _source(
        "tests/test_workflow_design_draft_api_lifecycle.py"
    )
    workflow_draft_sources = workflow_drafts_source + workflow_draft_api_lifecycle_source

    assert "from .submission_service import create_run_from_request" not in route_source
    assert "return await create_run_from_request(" in route_source
    assert "payload.runSpec" not in route_source
    assert "validate_run_spec_for_pipeline" not in route_source
    assert "preflight_run_spec" not in route_source
    assert "create_run_record" not in route_source
    assert "start_run_execution" not in route_source

    assert "from .submission_service import create_run_from_request as create_run_submission_from_request" in control_source
    assert "async def create_run_from_request(" in control_source
    assert "def create_run_from_request(" in service_source
    assert "ensure_execution_admission_ready(cfg)" in service_source
    assert "from .route_utils import request_payload" in service_source
    assert "request.runSpec.model_dump(" not in service_source
    assert "run_spec = request_payload(request.runSpec)" in service_source
    assert "pipeline_id = request.runSpec.pipelineId" in service_source
    assert "pipeline_version = request.runSpec.pipelineVersion" in service_source
    assert "apps.remote_runner.main.start_run_execution" not in lifecycle_source
    assert "start_run_execution" not in service_source
    assert "apps.remote_runner.submission_service.start_run_execution" not in lifecycle_source
    assert "apps.remote_runner.main.load_remote_runner_config" not in workflow_draft_sources
    assert "apps.remote_runner.main.inspect_workflow_runtime" not in workflow_draft_sources
    assert "apps.remote_runner.main.inspect_pipeline_registry" not in workflow_draft_sources
    assert "apps.remote_runner.main.start_run_execution" not in workflow_draft_sources
    assert (
        "apps.remote_runner.submission_service.ensure_submission_ready"
        in workflow_draft_api_lifecycle_source
    )
    assert "apps.remote_runner.submission_service.start_run_execution" not in workflow_draft_api_lifecycle_source


def test_remote_runner_app_lifespan_starts_durable_worker_supervisor() -> None:
    main_source = _source("apps/remote_runner/main.py")

    assert "from contextlib import asynccontextmanager" in main_source
    assert "from .worker_supervisor import start_configured_run_worker_supervisor" in main_source
    assert "start_configured_tool_prepare_worker_supervisor" in main_source
    assert "from .trigger_scheduler import start_configured_workflow_trigger_scheduler_supervisor" in main_source
    assert "from .trigger_readiness_watcher import start_configured_workflow_trigger_readiness_watcher_supervisor" in main_source
    assert "from .artifact_lifecycle_controller import start_configured_artifact_lifecycle_controller_supervisor" in main_source
    assert "@asynccontextmanager" in main_source
    assert "async def lifespan(" in main_source
    assert "FastAPI(title=\"H2OMeta Remote Runner\", version=\"0.1.1-control-plane\", lifespan=lifespan)" in main_source
    assert "start_configured_run_worker_supervisor()" in main_source
    assert "start_configured_tool_prepare_worker_supervisor()" in main_source
    assert "start_configured_workflow_trigger_scheduler_supervisor()" in main_source
    assert "start_configured_workflow_trigger_readiness_watcher_supervisor()" in main_source
    assert "start_configured_artifact_lifecycle_controller_supervisor()" in main_source
    assert "supervisor.stop()" in main_source


def test_remote_runner_control_plane_services_use_async_thread_boundary() -> None:
    control_source = _source("apps/remote_runner/control_service.py")
    route_sources = [
        _source("apps/remote_runner/health_routes.py"),
        _source("apps/remote_runner/pipeline_routes.py"),
        _source("apps/remote_runner/submission_routes.py"),
        _source("apps/remote_runner/execution_query_routes.py"),
        _source("apps/remote_runner/workflow_trigger_routes.py"),
    ]
    service_names = (
        "health_startup_from_request",
        "health_live_from_request",
        "health_ready_from_request",
        "health_meta_from_request",
        "health_workers_from_request",
        "execution_diagnostics_from_request",
        "list_pipelines_from_request",
        "get_pipeline_from_request",
        "create_upload_from_request",
        "create_run_from_request",
        "cancel_run_from_request",
        "retry_run_from_request",
        "list_runs_from_request",
        "get_run_from_request",
        "get_run_events_from_request",
        "get_run_execution_context_from_request",
        "get_run_logs_from_request",
        "get_run_results_from_request",
        "get_run_rules_from_request",
        "list_results_from_request",
        "get_result_from_request",
        "get_result_preview_from_request",
        "get_result_audit_from_request",
        "export_result_package_from_request",
        "download_result_package_from_request",
        "create_workflow_trigger_request",
        "list_workflow_triggers_request",
        "submit_workflow_trigger_event_request",
        "submit_workflow_trigger_inbox_event_envelope_request",
        "submit_workflow_trigger_inbox_event_request",
        "replay_workflow_trigger_inbox_event_request",
        "submit_workflow_trigger_readiness_event_request",
        "launch_workflow_trigger_backfill_request",
        "preview_workflow_trigger_backfill_request",
        "list_workflow_trigger_events_request",
        "list_workflow_trigger_inbox_events_request",
        "list_workflow_backfill_launches_request",
        "get_workflow_backfill_launch_request",
        "cancel_workflow_backfill_launch_request",
    )

    assert "from .route_utils import authorized_config, data_response, remote_runner_principal, run_sync" in control_source
    assert "await run_sync(" in control_source

    for name in service_names:
        assert f"async def {name}(" in control_source

    for source in route_sources:
        assert "return await " in source
        assert "return health_" not in source
        assert "return list_" not in source
        assert "return get_" not in source
        assert "return create_" not in source


def test_run_log_stream_query_is_validated_by_type_annotation() -> None:
    route_source = _source("apps/remote_runner/execution_query_routes.py")

    assert "Literal" in route_source
    assert 'stream: Literal["stdout", "stderr"] = "stdout"' in route_source
    assert "normalized_stream" not in route_source
    assert ".lower()" not in route_source


def test_workflow_trigger_routes_delegate_to_service() -> None:
    main_source = _source("apps/remote_runner/main.py")
    route_source = _source("apps/remote_runner/workflow_trigger_routes.py")
    control_source = _source("apps/remote_runner/control_service.py")
    service_source = _source("apps/remote_runner/trigger_service.py")
    inbox_source = _source("apps/remote_runner/trigger_inbox_service.py")
    replay_source = _source("apps/remote_runner/trigger_inbox_replay_service.py")

    assert "from .workflow_trigger_routes import router as workflow_trigger_router" in main_source
    assert "app.include_router(workflow_trigger_router)" in main_source
    assert "payload.runSpec" not in route_source
    assert "record_workflow_trigger_event" not in route_source
    assert "create_run_record" not in route_source
    assert "return await create_workflow_trigger_request(" in route_source
    assert "return await submit_workflow_trigger_event_request(" in route_source
    assert "Request" in route_source
    assert "await request.body()" in route_source
    assert "request.headers.raw" in route_source
    assert "build_webhook_raw_request_envelope(" in route_source
    assert "return await submit_workflow_trigger_inbox_event_envelope_request(" in route_source
    assert "return await replay_workflow_trigger_inbox_event_request(" in route_source
    assert "return await list_workflow_trigger_inbox_events_request(" in route_source
    assert "return await submit_workflow_trigger_readiness_event_request(" in route_source
    assert "return await launch_workflow_trigger_backfill_request(" in route_source
    assert "return await preview_workflow_trigger_backfill_request(" in route_source
    assert "return await list_workflow_backfill_launches_request(" in route_source
    assert "return await get_workflow_backfill_launch_request(" in route_source
    assert "return await cancel_workflow_backfill_launch_request(" in route_source

    for name in (
        "create_workflow_trigger_request",
        "list_workflow_triggers_request",
        "submit_workflow_trigger_event_request",
        "submit_workflow_trigger_inbox_event_envelope_request",
        "submit_workflow_trigger_inbox_event_request",
        "replay_workflow_trigger_inbox_event_request",
        "submit_workflow_trigger_readiness_event_request",
        "launch_workflow_trigger_backfill_request",
        "preview_workflow_trigger_backfill_request",
        "list_workflow_trigger_events_request",
        "list_workflow_trigger_inbox_events_request",
        "list_workflow_backfill_launches_request",
        "get_workflow_backfill_launch_request",
        "cancel_workflow_backfill_launch_request",
    ):
        assert f"async def {name}(" in control_source

    assert "def create_workflow_trigger_from_request(" in service_source
    assert "def list_workflow_backfill_launches_from_storage(" in service_source
    assert "def list_workflow_trigger_inbox_events_from_storage(" in inbox_source
    assert "def get_workflow_backfill_launch_from_storage(" in service_source
    assert "def cancel_workflow_backfill_launch_from_request(" in service_source
    assert "def submit_workflow_trigger_event_from_request(" in service_source
    assert "def submit_workflow_trigger_inbox_event_from_request(" in inbox_source
    assert "def replay_workflow_trigger_inbox_event_from_request(" in replay_source
    assert '_authorized_config_from_request(authorization, action="workflow_trigger.inbox_replay")' in control_source
    assert "def submit_workflow_trigger_readiness_event_from_request(" in service_source
    assert "def launch_workflow_trigger_backfill_from_request(" in service_source
    assert "def preview_workflow_trigger_backfill_from_request(" in service_source
    assert "record_workflow_trigger_event(" in service_source
    assert "create_run_record(" in service_source
    assert "WORKFLOW_TRIGGER_SOURCE_LAUNCH_UNSUPPORTED" in service_source
    assert "WORKFLOW_BACKFILL_LAUNCH_TRUNCATED" in service_source


def test_health_inspection_logic_lives_in_service_not_route() -> None:
    main_source = _source("apps/remote_runner/main.py")
    control_source = _source("apps/remote_runner/control_service.py")
    service_source = _source("apps/remote_runner/health_service.py")
    pipeline_source = _source("apps/remote_runner/pipeline.py")

    assert "from .health_service import (" not in main_source
    assert "build_health_ready_payload" not in main_source
    assert "build_health_ready_payload" in control_source
    assert "ensure_submission_ready(" in service_source
    assert "inspect_workflow_runtime" not in main_source
    assert "inspect_pipeline_registry" not in main_source
    assert "workflow.get(" not in main_source
    assert "registry.get(" not in main_source

    assert "class WorkflowRuntimeInspection(BaseModel)" in service_source
    assert "class PipelineRegistryInspection(BaseModel)" in service_source
    assert "def build_health_ready_payload(" in service_source
    assert "def ensure_submission_ready(" in service_source
    assert "except Exception" not in pipeline_source
    assert "Pipeline registry is invalid" not in pipeline_source


def test_upload_route_delegates_request_field_mapping_to_service() -> None:
    route_source = _source("apps/remote_runner/main.py")
    control_source = _source("apps/remote_runner/control_service.py")
    service_source = _source("apps/remote_runner/upload_service.py")

    assert "from .upload_service import persist_upload_from_request" not in route_source
    assert "persist_upload_from_request(cfg, payload)" not in route_source
    assert "run_sync(persist_upload_from_request, cfg, payload)" in control_source
    assert "payload.filename" not in route_source
    assert "payload.contentBase64" not in route_source
    assert "payload.mimeType" not in route_source

    assert "def persist_upload_from_request(" in service_source
    assert "request.contentBase64" in service_source


def test_remote_runner_main_delegates_control_plane_work_to_service() -> None:
    main_source = _source("apps/remote_runner/main.py")
    health_route_source = _source("apps/remote_runner/health_routes.py")
    pipeline_route_source = _source("apps/remote_runner/pipeline_routes.py")
    submission_route_source = _source("apps/remote_runner/submission_routes.py")
    execution_query_route_source = _source("apps/remote_runner/execution_query_routes.py")
    control_source = _source("apps/remote_runner/control_service.py")

    assert "from .health_routes import router as health_router" in main_source
    assert "app.include_router(health_router)" in main_source
    assert "from .pipeline_routes import router as pipeline_router" in main_source
    assert "app.include_router(pipeline_router)" in main_source
    assert "from .submission_routes import router as submission_router" in main_source
    assert "app.include_router(submission_router)" in main_source
    assert "from .execution_query_routes import router as execution_query_router" in main_source
    assert "app.include_router(execution_query_router)" in main_source
    assert "Literal" not in main_source
    assert "Header" not in main_source
    assert "RunCreateRequest" not in main_source
    assert "UploadCreateRequest" not in main_source
    assert "health_startup_from_request" not in main_source
    assert "health_live_from_request" not in main_source
    assert "health_ready_from_request" not in main_source
    assert "health_meta_from_request" not in main_source
    assert "health_workers_from_request" not in main_source
    assert "execution_diagnostics_from_request" not in main_source
    assert "list_pipelines_from_request" not in main_source
    assert "get_pipeline_from_request" not in main_source
    assert "create_upload_from_request" not in main_source
    assert "create_run_from_request" not in main_source
    assert "cancel_run_from_request" not in main_source
    assert "list_runs_from_request" not in main_source
    assert "get_run_from_request" not in main_source
    assert "get_run_events_from_request" not in main_source
    assert "get_run_logs_from_request" not in main_source
    assert "get_run_results_from_request" not in main_source
    assert "get_run_rules_from_request" not in main_source
    assert "list_results_from_request" not in main_source
    assert "get_result_from_request" not in main_source
    assert "get_result_preview_from_request" not in main_source
    assert "from .config import" not in main_source
    assert "from .pipeline import" not in main_source
    assert "from .route_utils import" not in main_source
    assert "from .storage import" not in main_source
    assert "load_remote_runner_config" not in main_source
    assert "_require_auth" not in main_source
    assert "authorized_config(" not in main_source
    assert '@app.get("/health/startup")' not in main_source
    assert '@app.get("/health/live")' not in main_source
    assert '@app.get("/health/ready")' not in main_source
    assert '@app.get("/health/meta")' not in main_source
    assert '@app.get("/health/workers")' not in main_source
    assert '@app.get("/api/v1/pipelines")' not in main_source
    assert '@app.get("/api/v1/pipelines/{pipeline_id}")' not in main_source
    assert '@app.post("/api/v1/uploads")' not in main_source
    assert '@app.post("/api/v1/runs", status_code=202)' not in main_source
    assert '@app.post("/api/v1/runs/{run_id}/cancel")' not in main_source
    assert '@app.get("/api/v1/runs")' not in main_source
    assert '@app.get("/api/v1/runs/{run_id}")' not in main_source
    assert '@app.get("/api/v1/results")' not in main_source

    assert "router = APIRouter()" in health_route_source
    assert '@router.get("/health/startup")' in health_route_source
    assert '@router.get("/health/live")' in health_route_source
    assert '@router.get("/health/ready")' in health_route_source
    assert '@router.get("/health/meta")' in health_route_source
    assert '@router.get("/health/workers")' in health_route_source
    assert '@router.get("/health/execution-diagnostics")' in health_route_source
    assert "health_startup_from_request" in health_route_source
    assert "health_live_from_request" in health_route_source
    assert "health_ready_from_request" in health_route_source
    assert "health_meta_from_request" in health_route_source
    assert "health_workers_from_request" in health_route_source
    assert "execution_diagnostics_from_request" in health_route_source

    assert "router = APIRouter()" in pipeline_route_source
    assert '@router.get("/api/v1/pipelines")' in pipeline_route_source
    assert '@router.get("/api/v1/pipelines/{pipeline_id}")' in pipeline_route_source
    assert "list_pipelines_from_request" in pipeline_route_source
    assert "get_pipeline_from_request" in pipeline_route_source

    assert "router = APIRouter()" in submission_route_source
    assert '@router.post("/api/v1/uploads")' in submission_route_source
    assert '@router.post("/api/v1/runs", status_code=202)' in submission_route_source
    assert "create_upload_from_request" in submission_route_source
    assert "create_run_from_request" in submission_route_source

    assert "router = APIRouter()" in execution_query_route_source
    assert '@router.get("/api/v1/runs")' in execution_query_route_source
    assert '@router.get("/api/v1/runs/{run_id}")' in execution_query_route_source
    assert '@router.post("/api/v1/runs/{run_id}/cancel")' in execution_query_route_source
    assert '@router.post("/api/v1/runs/{run_id}/retry", status_code=202)' in execution_query_route_source
    assert '@router.get("/api/v1/runs/{run_id}/events")' in execution_query_route_source
    assert '@router.get("/api/v1/runs/{run_id}/execution-context")' in execution_query_route_source
    assert '@router.get("/api/v1/runs/{run_id}/logs")' in execution_query_route_source
    assert '@router.get("/api/v1/runs/{run_id}/results")' in execution_query_route_source
    assert '@router.get("/api/v1/results")' in execution_query_route_source
    assert '@router.get("/api/v1/results/{result_id}")' in execution_query_route_source
    assert '@router.get("/api/v1/results/{result_id}/preview")' in execution_query_route_source
    assert '@router.get("/api/v1/results/{result_id}/audit")' in execution_query_route_source
    assert '@router.post("/api/v1/results/{result_id}/export")' in execution_query_route_source
    assert '@router.get("/api/v1/results/{result_id}/exports/{package_export_id}/download")' in execution_query_route_source
    assert "list_runs_from_request" in execution_query_route_source
    assert "get_run_from_request" in execution_query_route_source
    assert "cancel_run_from_request" in execution_query_route_source
    assert "retry_run_from_request" in execution_query_route_source
    assert "get_run_events_from_request" in execution_query_route_source
    assert "get_run_execution_context_from_request" in execution_query_route_source
    assert "get_run_logs_from_request" in execution_query_route_source
    assert "get_run_results_from_request" in execution_query_route_source
    assert "get_run_rules_from_request" in execution_query_route_source
    assert "list_results_from_request" in execution_query_route_source
    assert "get_result_from_request" in execution_query_route_source
    assert "get_result_preview_from_request" in execution_query_route_source
    assert "get_result_audit_from_request" in execution_query_route_source
    assert "export_result_package_from_request" in execution_query_route_source
    assert "download_result_package_from_request" in execution_query_route_source

    for name in (
        "health_startup_from_request",
        "health_live_from_request",
        "health_ready_from_request",
        "health_meta_from_request",
        "health_workers_from_request",
        "execution_diagnostics_from_request",
        "list_pipelines_from_request",
        "get_pipeline_from_request",
        "create_upload_from_request",
        "create_run_from_request",
        "cancel_run_from_request",
        "retry_run_from_request",
        "list_runs_from_request",
        "get_run_from_request",
        "get_run_events_from_request",
        "get_run_execution_context_from_request",
        "get_run_logs_from_request",
        "get_run_results_from_request",
        "get_run_rules_from_request",
        "list_results_from_request",
        "get_result_from_request",
        "get_result_preview_from_request",
        "get_result_audit_from_request",
        "export_result_package_from_request",
        "download_result_package_from_request",
    ):
        assert f"async def {name}(" in control_source
