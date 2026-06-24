from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_run_submission_routes_delegate_request_assembly_to_service() -> None:
    main_source = _source("apps/api/main.py")
    route_source = _source("apps/api/submission_routes.py")
    service_path = ROOT / "apps/api/submission_service.py"

    assert service_path.exists()
    service_source = service_path.read_text(encoding="utf-8")

    assert "from apps.api.submission_routes import router as submission_router" in main_source
    assert "app.include_router(submission_router)" in main_source
    assert '@app.post("/api/v1/uploads")' not in main_source
    assert '@app.post("/api/v1/runs", status_code=202)' not in main_source

    route_start = route_source.index('@router.post("/api/v1/uploads")')
    route_end = len(route_source)
    submission_routes = route_source[route_start:route_end]

    assert "payload.model_dump(" not in submission_routes
    assert "ensure_request_id" not in submission_routes
    assert "invalidate_response_cache" not in submission_routes
    assert "response.headers" not in submission_routes
    assert 'response.headers["Location"]' not in submission_routes
    assert 'response.headers["Retry-After"]' not in submission_routes
    assert 'response.headers["X-Request-Id"]' not in submission_routes
    assert "upload_file_from_request" in submission_routes
    assert "submit_run_response_from_request" in submission_routes

    assert "def submit_run_response_from_request(" in service_source
    assert "def upload_file_from_request(" in service_source
    assert "def submit_run_from_request(" in service_source
    assert "from fastapi import Response" not in service_source
    assert "class ResponseWithHeaders(Protocol)" in service_source


def test_run_result_routes_delegate_runtime_calls_to_service() -> None:
    main_source = _source("apps/api/main.py")
    route_source = _source("apps/api/execution_query_routes.py")
    service_path = ROOT / "apps/api/execution_query_service.py"

    assert service_path.exists()
    service_source = service_path.read_text(encoding="utf-8")

    assert "from apps.api.execution_query_routes import router as execution_query_router" in main_source
    assert "app.include_router(execution_query_router)" in main_source
    assert '@app.get("/api/v1/runs")' not in main_source
    assert '@app.get("/api/v1/runs/{run_id}")' not in main_source
    assert '@app.get("/api/v1/results")' not in main_source

    list_route_start = route_source.index('@router.get("/api/v1/runs")')
    list_route_end = route_source.index('@router.get("/api/v1/runs/{run_id}")')
    list_route = route_source[list_route_start:list_route_end]
    detail_route_start = route_source.index('@router.get("/api/v1/runs/{run_id}")')
    detail_routes = route_source[detail_route_start:]

    for routes in (list_route, detail_routes):
        assert "_runtime()" not in routes
        assert "_run_runtime_payload" not in routes
        assert "_cached_runtime_payload" not in routes

    assert "router = APIRouter()" in route_source
    assert "from apps.api.route_utils" not in route_source
    assert "runtime_service()" not in route_source
    assert "list_runs_from_request" in list_route
    assert "get_run_from_request" in detail_routes
    assert "cancel_run_from_request" in detail_routes
    assert "retry_run_from_request" in detail_routes
    assert "get_run_events_from_request" in detail_routes
    assert "get_run_execution_context_from_request" in detail_routes
    assert "get_run_logs_from_request" in detail_routes
    assert "get_run_results_from_request" in detail_routes
    assert "get_run_rules_from_request" in detail_routes
    assert "list_results_from_request" in detail_routes
    assert "get_result_from_request" in detail_routes
    assert "get_result_preview_from_request" in detail_routes
    assert "get_result_audit_from_request" in detail_routes
    assert "export_result_package_from_request" in detail_routes
    assert "list_result_package_exports_from_request" in detail_routes
    assert "download_result_package_from_request" in detail_routes
    assert "retire_result_package_from_request" in detail_routes
    assert "delete_result_package_bytes_from_request" in detail_routes

    assert "def list_runs_from_request(" in service_source
    assert "def get_run_from_request(" in service_source
    assert "def cancel_run_from_request(" in service_source
    assert "def retry_run_from_request(" in service_source
    assert "def get_run_events_from_request(" in service_source
    assert "def get_run_execution_context_from_request(" in service_source
    assert "def get_run_logs_from_request(" in service_source
    assert "def get_run_results_from_request(" in service_source
    assert "def get_run_rules_from_request(" in service_source
    assert "def list_results_from_request(" in service_source
    assert "def get_result_from_request(" in service_source
    assert "def get_result_preview_from_request(" in service_source
    assert "def get_result_audit_from_request(" in service_source
    assert "def export_result_package_from_request(" in service_source
    assert "def list_result_package_exports_from_request(" in service_source
    assert "def download_result_package_from_request(" in service_source
    assert "def retire_result_package_from_request(" in service_source
    assert "def delete_result_package_bytes_from_request(" in service_source
    assert "runtime_service().get_result_audit(" in service_source
    assert "runtime_service().export_result_package(" in service_source
    assert "runtime_service().list_result_package_exports(" in service_source
    assert "runtime_service().download_result_package(" in service_source
    assert "runtime_service().retire_result_package(" in service_source
    assert "runtime_service().delete_result_package_bytes(" in service_source
    assert "from fastapi import Response" not in service_source


def test_workflow_trigger_routes_delegate_runtime_calls_to_service() -> None:
    main_source = _source("apps/api/main.py")
    route_source = _source("apps/api/workflow_trigger_routes.py")
    service_path = ROOT / "apps/api/workflow_trigger_service.py"

    assert service_path.exists()
    service_source = service_path.read_text(encoding="utf-8")

    assert "from apps.api.workflow_trigger_routes import router as workflow_trigger_router" in main_source
    assert "app.include_router(workflow_trigger_router)" in main_source
    assert '@app.get("/api/v1/workflow-triggers")' not in main_source
    assert '@app.post("/api/v1/workflow-triggers", status_code=201)' not in main_source

    assert "from apps.api.route_utils" not in route_source
    assert "runtime_service()" not in route_source
    assert "response.headers" not in route_source
    assert "list_workflow_triggers_from_request" in route_source
    assert "create_workflow_trigger_from_request" in route_source
    assert "list_workflow_trigger_events_from_request" in route_source
    assert "list_workflow_trigger_inbox_events_from_request" in route_source
    assert "list_workflow_backfill_launches_from_request" in route_source
    assert "get_workflow_backfill_launch_from_request" in route_source
    assert "cancel_workflow_backfill_launch_from_request" in route_source
    assert "launch_workflow_trigger_backfill_from_request" in route_source
    assert "preview_workflow_trigger_backfill_from_request" in route_source
    assert "submit_workflow_trigger_event_response_from_request" in route_source
    assert "submit_workflow_trigger_inbox_event_response_from_raw_request" in route_source
    assert "replay_workflow_trigger_inbox_event_response_from_request" in route_source
    assert "submit_workflow_trigger_readiness_event_response_from_request" in route_source

    for name in (
        "list_workflow_triggers_from_request",
        "create_workflow_trigger_from_request",
        "list_workflow_trigger_events_from_request",
        "list_workflow_trigger_inbox_events_from_request",
        "list_workflow_backfill_launches_from_request",
        "get_workflow_backfill_launch_from_request",
        "cancel_workflow_backfill_launch_from_request",
        "launch_workflow_trigger_backfill_from_request",
        "preview_workflow_trigger_backfill_from_request",
        "submit_workflow_trigger_event_from_request",
        "submit_workflow_trigger_event_response_from_request",
        "submit_workflow_trigger_inbox_event_from_request",
        "submit_workflow_trigger_inbox_event_response_from_request",
        "submit_workflow_trigger_inbox_event_from_raw_request",
        "submit_workflow_trigger_inbox_event_response_from_raw_request",
        "replay_workflow_trigger_inbox_event_from_request",
        "replay_workflow_trigger_inbox_event_response_from_request",
        "submit_workflow_trigger_readiness_event_from_request",
        "submit_workflow_trigger_readiness_event_response_from_request",
    ):
        assert f"def {name}(" in service_source

    assert "runtime_service().create_workflow_trigger(" in service_source
    assert "runtime_service().list_workflow_backfill_launches(" in service_source
    assert "runtime_service().get_workflow_backfill_launch(" in service_source
    assert "runtime_service().cancel_workflow_backfill_launch(" in service_source
    assert "runtime_service().launch_workflow_trigger_backfill(" in service_source
    assert "runtime_service().preview_workflow_trigger_backfill(" in service_source
    assert "runtime_service().submit_workflow_trigger_event(" in service_source
    assert "runtime_service().submit_workflow_trigger_inbox_event(" in service_source
    assert "_webhook_inbox_forward_headers(raw_headers)" in service_source
    assert "runtime_service().replay_workflow_trigger_inbox_event(" in service_source
    assert "runtime_service().list_workflow_trigger_inbox_events(" in service_source
    assert "runtime_service().submit_workflow_trigger_readiness_event(" in service_source
    assert 'prefixes=("workflow_trigger_events", "workflow_trigger_inbox")' in service_source
    assert 'prefixes=("workflow_trigger_events", "workflow_backfill_launches", "workflow_backfill_launch")' in service_source


def test_local_api_tests_patch_service_runtime_providers() -> None:
    backend_contract_path = ROOT / "tests/test_backend_contract_api.py"
    generated_tool_snakemake_path = ROOT / "tests/test_generated_tool_snakemake.py"
    generated_tool_snakemake_surface_path = ROOT / "tests/test_generated_tool_snakemake_surface.py"
    tool_contract_path = ROOT / "tests/test_tool_contract_pipeline.py"
    backend_contract_lines = backend_contract_path.read_text(encoding="utf-8").splitlines()
    generated_tool_snakemake_lines = generated_tool_snakemake_path.read_text(encoding="utf-8").splitlines()
    generated_tool_snakemake_surface_lines = generated_tool_snakemake_surface_path.read_text(
        encoding="utf-8"
    ).splitlines()
    tool_contract_lines = tool_contract_path.read_text(encoding="utf-8").splitlines()

    assert len(backend_contract_lines) <= 800
    assert len(generated_tool_snakemake_lines) <= 800
    assert len(generated_tool_snakemake_surface_lines) <= 800
    assert len(tool_contract_lines) <= 800

    for path in (
        "tests/test_backend_contract_api.py",
        "tests/test_backend_submission_upload_api.py",
        "tests/test_remote_runner_stop_service.py",
        "tests/test_workflow_design_local_api.py",
    ):
        source = _source(path)

        assert "from apps.api.main import" not in source
        assert "apps.api.main._runtime" not in source
        assert "apps.api.workflow_design_routes.runtime_service" not in source

    backend_source = _source("tests/test_backend_contract_api.py")
    helper_start = backend_source.index("def patch_runtime_service(")
    helper_end = backend_source.index("\n\nclass FakeTerminalSession:")
    helper_source = backend_source[helper_start:helper_end]

    assert "from apps.api.response_cache import invalidate_response_cache" in backend_source
    assert "invalidate_response_cache(" in helper_source
    assert "asyncio.run(" in helper_source


def test_upload_submission_tests_assert_service_errors_explicitly() -> None:
    source = _source("tests/test_backend_submission_upload_api.py")

    assert "except Exception" not in source
    assert 'getattr(exc, "status_code", None)' not in source
    assert "pytest.raises(RuntimeServiceError" in source


def test_workflow_design_api_tests_use_response_data_helper() -> None:
    source = _source("tests/test_workflow_design_drafts.py")

    assert "." + "json()" not in source
    assert "TestClient" not in source
