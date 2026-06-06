from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_tool_capability_route_uses_query_constraints_for_pagination() -> None:
    source = _source("apps/api/tool_capability_routes.py")
    service_path = ROOT / "apps/api/tool_capability_service.py"

    assert service_path.exists()
    service_source = service_path.read_text(encoding="utf-8")

    assert "from fastapi import APIRouter, Query" in source
    assert 'page: int = Query(default=1, ge=1)' in source
    assert 'pageSize: int | None = Query(default=None, ge=1, le=50)' in source
    assert 'limit: int = Query(default=20, ge=1, le=50)' in source
    assert "from apps.api.route_utils" not in source
    assert "search_tool_capabilities(" not in source
    assert "bioconda_index_status(" not in source
    assert "refresh_bioconda_index(" not in source
    assert "page_size =" not in source
    assert "bounded_page" not in source
    assert "bounded_page_size" not in source
    assert "search_tool_capabilities_from_request" in source
    assert "search_tool_candidates_from_request" in source
    assert "recommend_tool_candidates_from_request" in source
    assert "get_tool_candidate_target_acceptance_from_request" in source
    assert "list_snakemake_wrapper_catalog_from_request" in source
    assert "list_tool_profile_catalog_from_request" in source
    assert "get_tool_capabilities_index_status_from_request" in source
    assert "refresh_tool_capabilities_index_from_request" in source

    assert "def search_tool_capabilities_from_request(" in service_source
    assert "def search_tool_candidates_from_request(" in service_source
    assert "def recommend_tool_candidates_from_request(" in service_source
    assert "def get_tool_candidate_target_acceptance_from_request(" in service_source
    assert "def list_snakemake_wrapper_catalog_from_request(" in service_source
    assert "def list_tool_profile_catalog_from_request(" in service_source
    assert "def get_tool_capabilities_index_status_from_request(" in service_source
    assert "def refresh_tool_capabilities_index_from_request(" in service_source
    assert '@router.get("/api/v1/tool-capabilities/snakemake-wrappers", operation_id="listSnakemakeWrapperCatalog")' in source
    assert '@router.get("/api/v1/tool-capabilities/tool-profiles", operation_id="listToolProfileCatalog")' in source
    assert '@router.get("/api/v1/tool-capabilities/candidates", operation_id="searchToolCandidates")' in source
    assert '@router.get("/api/v1/tool-capabilities/candidate-recommendations", operation_id="recommendToolCandidates")' in source
    assert '@router.get("/api/v1/tool-capabilities/target-acceptance", operation_id="getToolCandidateTargetAcceptance")' in source
    assert 'outputKind: str = ""' in source
    assert 'outputMimeType: str = ""' in source
    assert 'outputData: str = ""' in source
    assert 'outputFormat: str = ""' in source
    assert 'pageSize: int = Query(default=50, ge=1, le=100)' in source


def test_local_api_routes_pin_openapi_operation_ids() -> None:
    tool_source = _source("apps/api/tool_capability_routes.py")
    system_source = _source("apps/api/system_routes.py")

    for operation_id in [
        "searchToolCapabilities",
        "searchToolCandidates",
        "recommendToolCandidates",
        "getToolCandidateTargetAcceptance",
        "listSnakemakeWrapperCatalog",
        "listToolProfileCatalog",
        "getToolCapabilitiesIndexStatus",
        "refreshToolCapabilitiesIndex",
    ]:
        assert f'operation_id="{operation_id}"' in tool_source

    for operation_id in [
        "health",
        "getVersion",
        "getServiceInfo",
    ]:
        assert f'operation_id="{operation_id}"' in system_source


def test_tool_capability_anaconda_parsing_lives_outside_search_orchestrator() -> None:
    source = _source("apps/api/tool_capabilities.py")
    parser_source = _source("apps/api/tool_capability_anaconda.py")

    assert len(source.splitlines()) <= 360
    assert "from apps.api.tool_capability_anaconda import (" in source
    assert "class CondaPackageHit" not in source
    assert "from dataclasses import dataclass" not in source
    for helper in [
        "_parse_search_item",
        "_latest_version",
        "_versions",
        "_package_spec",
        "_platforms",
        "_normalize_target_platform",
        "_platform_supported",
        "_remaining_timeout",
    ]:
        assert f"def {helper}(" not in source

    assert "class CondaPackageHit" in parser_source
    for helper in [
        "parse_search_item",
        "latest_version",
        "versions",
        "package_spec",
        "platforms",
        "normalize_target_platform",
        "platform_supported",
        "remaining_timeout",
    ]:
        assert f"def {helper}(" in parser_source


def test_remote_file_route_uses_query_constraints_for_bounds() -> None:
    source = _source("apps/api/ssh_routes.py")

    assert 'limit: int = Query(default=500, ge=1, le=5000)' in source
    assert 'offset: int = Query(default=0, ge=0)' in source
    assert 'cursor: int = Query(default=0, ge=0)' in source
    assert "bounded_limit" not in source
    assert "bounded_offset" not in source


def test_terminal_stream_helper_receives_validated_cursor() -> None:
    source = _source("apps/api/ssh_terminal_service.py")

    assert "current_cursor = cursor" in source
    assert "current_cursor = max(0, int(cursor or 0))" not in source


def test_terminal_stream_helper_uses_snapshot_model() -> None:
    source = _source("apps/api/ssh_terminal_service.py")
    models_source = _source("apps/api/models.py")

    assert "TerminalSessionSnapshot" in source
    assert "snapshot.get(" not in source
    assert "class TerminalSessionSnapshot(ApiRequest)" in models_source
    assert "def state_key(self) -> tuple[bool, bool, str]" in models_source


def test_terminal_stream_helper_does_not_swallow_protocol_failures() -> None:
    source = _source("apps/api/ssh_terminal_service.py")

    assert "except Exception" not in source
    assert '"type": "error"' not in source
    assert "terminal stream failed" not in source


def test_terminal_stream_helper_uses_runtime_thread_infrastructure() -> None:
    source = _source("apps/api/ssh_terminal_service.py")

    assert "from apps.api.route_utils import run_sync" in source
    assert "asyncio.to_thread" not in source
    assert "await run_sync(" in source


def test_run_sync_thread_dispatch_lives_in_core_helper() -> None:
    route_utils_source = _source("apps/api/route_utils.py")
    remote_route_utils_source = _source("apps/remote_runner/route_utils.py")
    helper_source = _source("core/async_boundary.py")

    assert "from core.async_boundary import run_sync" in route_utils_source
    assert "from core.async_boundary import run_sync" in remote_route_utils_source
    assert "def run_sync(" not in route_utils_source
    assert "def run_sync(" not in remote_route_utils_source
    assert "asyncio.to_thread" not in route_utils_source
    assert "run_in_threadpool" not in remote_route_utils_source
    assert "def run_sync(" in helper_source
    assert "asyncio.to_thread(func, *args, **kwargs)" in helper_source


def test_run_sync_supports_positional_and_keyword_arguments() -> None:
    import asyncio

    from core.async_boundary import run_sync

    def add(left: int, *, right: int) -> int:
        return left + right

    assert asyncio.run(run_sync(add, 2, right=3)) == 5


def test_terminal_stream_helper_lets_session_lookup_errors_propagate() -> None:
    source = _source("apps/api/ssh_terminal_service.py")

    assert "RuntimeServiceError" not in source
    assert "session is None" not in source
    assert "终端会话不存在" not in source
    assert "终端会话已关闭" not in source


def test_local_route_utils_use_deterministic_response_wrapping() -> None:
    source = _source("apps/api/route_utils.py")
    helper_source = _source("core/api_responses.py")

    assert '"data" in value' not in source
    assert '"item" in value' not in source
    assert '"items" in value' not in source
    assert "value.get(" not in source
    assert "from core.api_responses import wrapped_response" in source
    assert "return wrapped_response(value, wrapper=wrapper)" in source
    assert "return {\"data\": value}" not in source
    assert "return {\"item\": value}" not in source
    assert "return {\"data\": {\"items\": value}}" not in source
    assert "def wrapped_response(" in helper_source
    assert "def data_response(" in helper_source
    assert "def item_response(" in helper_source
    assert "def items_response(" in helper_source


def test_api_response_envelopes_live_in_core_helper() -> None:
    from core.api_responses import wrapped_response

    value = {"ok": True}

    assert wrapped_response(value, wrapper="raw") is value
    assert wrapped_response(value, wrapper="data") == {"data": value}
    assert wrapped_response(value, wrapper="item") == {"item": value}
    assert wrapped_response(value, wrapper="items") == {"items": value}
    assert wrapped_response(value, wrapper="data_items") == {"data": {"items": value}}


def test_response_cache_cleans_in_flight_without_broad_exception_handler() -> None:
    source = _source("apps/api/response_cache.py")

    assert "except Exception" not in source
    assert "finally:" in source
    assert "_in_flight.pop(key, None)" in source


def test_submit_run_route_fails_loudly_when_request_id_is_missing() -> None:
    service_path = ROOT / "apps/api/submission_service.py"

    assert service_path.exists()
    source = service_path.read_text(encoding="utf-8")

    assert '"X-Request-Id": str(result["requestId"])' in source
    assert 'result.get("requestId")' not in source


def test_local_api_main_delegates_system_routes() -> None:
    main_source = _source("apps/api/main.py")
    route_source = _source("apps/api/system_routes.py")
    service_path = ROOT / "apps/api/system_service.py"

    assert service_path.exists()
    service_source = service_path.read_text(encoding="utf-8")

    assert "from apps.api.system_routes import router as system_router" in main_source
    assert "app.include_router(system_router)" in main_source
    assert '@app.get("/health")' not in main_source
    assert '@app.get("/api/v1/version")' not in main_source
    assert "TERMINAL_RUNTIME_BUILD_ID" not in main_source
    assert "os.environ" not in main_source

    assert "router = APIRouter()" in route_source
    assert '@router.get("/health", operation_id="health")' in route_source
    assert '@router.get("/api/v1/version", operation_id="getVersion")' in route_source
    assert '@router.get("/api/v1/service-info", operation_id="getServiceInfo")' in route_source
    assert "service_info_from_request" in route_source
    assert "return await health_from_request()" in route_source
    assert "return await version_from_request()" in route_source
    assert "return await service_info_from_request()" in route_source
    assert "TERMINAL_RUNTIME_BUILD_ID" not in route_source
    assert "os.environ" not in route_source

    assert "TERMINAL_RUNTIME_BUILD_ID" in service_source
    assert "os.environ.get(" in service_source
    assert "async def health_from_request(" in service_source
    assert "async def version_from_request(" in service_source
    assert "async def service_info_from_request(" in service_source


def test_local_api_lifespan_lives_outside_app_composition_module() -> None:
    main_source = _source("apps/api/main.py")
    lifespan_source = _source("apps/api/lifespan.py")

    assert "from apps.api.lifespan import lifespan" in main_source
    assert "try:" not in main_source
    assert "finally:" not in main_source
    assert "async def lifespan(" in lifespan_source
    assert "runtime.shutdown()" in lifespan_source
    assert "get_runtime_service.cache_clear()" in lifespan_source


def test_workflow_design_routes_delegate_request_dumping_to_service() -> None:
    route_source = _source("apps/api/workflow_design_routes.py")
    service_source = _source("apps/api/workflow_design_service.py")
    models_source = _source("apps/api/models.py")
    route_utils_source = _source("apps/api/route_utils.py")

    assert "from apps.api.route_utils" not in route_source
    assert "runtime_service()" not in route_source
    assert "run_runtime_payload" not in route_source
    assert "cached_runtime_payload" not in route_source
    assert "payload.model_dump(" not in route_source
    assert "body = payload.model_dump" not in route_source
    assert "list_workflow_design_drafts_from_request" in route_source
    assert "get_workflow_design_draft_from_request" in route_source
    assert "create_workflow_design_draft_from_request" in route_source
    assert "update_workflow_design_draft_from_request" in route_source
    assert "fork_workflow_design_draft_from_request" in route_source
    assert "delete_workflow_design_draft_from_request" in route_source
    assert "plan_workflow_design_draft_from_request" in route_source
    assert "compile_workflow_design_draft_from_request" in route_source
    assert "invalidate_response_cache" not in route_source

    assert "def list_workflow_design_drafts_from_request(" in service_source
    assert "def get_workflow_design_draft_from_request(" in service_source
    assert "def create_workflow_design_draft_from_request(" in service_source
    assert "def update_workflow_design_draft_from_request(" in service_source
    assert "def fork_workflow_design_draft_from_request(" in service_source
    assert "def delete_workflow_design_draft_from_request(" in service_source
    assert "def plan_workflow_design_draft_from_request(" in service_source
    assert "def compile_workflow_design_draft_from_request(" in service_source
    assert ".model_dump(" not in service_source
    assert "by_alias=True" not in service_source
    assert "request_payload(" in service_source
    assert "def runtime_payload(self) -> dict[str, Any]:" in models_source
    assert "from core.api_payloads import request_payload" in route_utils_source
    assert "request.runtime_payload()" not in route_utils_source


def test_database_routes_delegate_request_dumping_to_service() -> None:
    route_source = _source("apps/api/database_routes.py")
    service_source = _source("apps/api/database_service.py")

    assert "from apps.api.route_utils" not in route_source
    assert "runtime_service()" not in route_source
    assert "run_runtime_payload" not in route_source
    assert "cached_runtime_payload" not in route_source
    assert "payload.model_dump(" not in route_source
    assert "invalidate_response_cache" not in route_source
    assert "list_databases_from_request" in route_source
    assert "list_database_templates_from_request" in route_source
    assert "add_database_from_request" in route_source
    assert "update_database_from_request" in route_source
    assert "delete_database_from_request" in route_source
    assert "check_database_from_request" in route_source

    assert "def list_databases_from_request(" in service_source
    assert "def list_database_templates_from_request(" in service_source
    assert "def add_database_from_request(" in service_source
    assert "def update_database_from_request(" in service_source
    assert "def delete_database_from_request(" in service_source
    assert "def check_database_from_request(" in service_source
    assert ".model_dump(" not in service_source
    assert "request_payload(" in service_source


def test_database_candidate_conflicts_are_not_parsed_in_api_route_errors() -> None:
    source = _source("apps/api/route_errors.py")

    assert "RuntimeConflictError" in source
    assert "DATABASE_CANDIDATES" not in source
    assert "json.loads" not in source


def test_api_route_error_status_codes_live_on_domain_errors() -> None:
    route_errors = _source("apps/api/route_errors.py")
    runtime_errors = _source("core/app_runtime/errors.py")
    sample_service = _source("apps/api/workflow_sample_data_service.py")

    assert "RuntimeConflictError(RuntimeServiceError):\n    status_code = 409" in runtime_errors
    assert "WorkflowSampleDataUnavailableError(ValueError):\n    status_code = 404" in sample_service
    assert "detail_response(409," not in route_errors
    assert "detail_response(404, str(exc))" not in route_errors
    assert "status_payload_response(exc)" in route_errors
    assert "status_detail_response(exc)" in route_errors
    assert "detail_response(exc.status_code, exc.payload if exc.payload is not None else str(exc))" not in route_errors
    assert "detail_response(exc.status_code, str(exc))" not in route_errors


def test_detail_response_shape_lives_in_shared_problem_response_helper() -> None:
    route_errors = _source("apps/api/route_errors.py")
    remote_route_errors = _source("apps/remote_runner/route_errors.py")
    helper_source = _source("core/problem_responses.py")

    assert "from core.problem_responses import (" in route_errors
    assert "from core.problem_responses import (" in remote_route_errors
    assert "def _detail_response(" not in route_errors
    assert "def _detail_response(" not in remote_route_errors
    assert "def detail_response(" in helper_source
    assert "def status_detail_response(" in helper_source
    assert "def status_payload_response(" in helper_source
    assert "def fixed_status_response(" in helper_source
    assert 'content={"detail": detail}' in helper_source


def test_fixed_status_exception_responses_live_in_shared_helper() -> None:
    route_errors = _source("apps/api/route_errors.py")
    response_helper = _source("core/problem_responses.py")

    assert "detail_response(400, str(exc))" not in route_errors
    assert "detail_response(502, str(exc))" not in route_errors
    assert "fixed_status_response(exc, status_code=400)" not in route_errors
    assert "fixed_status_response(exc, status_code=502)" not in route_errors
    assert "@app.exception_handler(TypeError)" not in route_errors
    assert "@app.exception_handler(KeyError)" not in route_errors
    assert "@app.exception_handler(OSError)" not in route_errors
    assert "@app.exception_handler(TimeoutError)" not in route_errors
    assert "register_fixed_status_exception_handlers(" in route_errors
    assert "TypeError" in route_errors
    assert "KeyError" in route_errors
    assert "OSError" in route_errors
    assert "TimeoutError" in route_errors
    assert "def fixed_status_response(" in response_helper
    assert "def register_fixed_status_exception_handlers(" in response_helper
    assert "return detail_response(status_code, str(error))" in response_helper


def test_fixed_status_exception_registration_lives_in_shared_helper() -> None:
    import asyncio

    from core.problem_responses import register_fixed_status_exception_handlers

    class FirstError(Exception):
        pass

    class SecondError(Exception):
        pass

    class FakeApp:
        def __init__(self) -> None:
            self.handlers: dict[type[Exception], object] = {}

        def exception_handler(self, error_type):
            def register(handler):
                self.handlers[error_type] = handler
                return handler

            return register

    app = FakeApp()

    register_fixed_status_exception_handlers(app, 499, FirstError, SecondError)

    assert set(app.handlers) == {FirstError, SecondError}
    first_response = asyncio.run(app.handlers[FirstError](None, FirstError("first")))
    second_response = asyncio.run(app.handlers[SecondError](None, SecondError("second")))
    assert first_response.status_code == 499
    assert second_response.status_code == 499


def test_status_detail_exception_registration_lives_in_shared_helper() -> None:
    import asyncio

    from core.problem_responses import register_status_detail_exception_handlers

    class FirstError(Exception):
        status_code = 409

    class SecondError(Exception):
        status_code = 503

    class FakeApp:
        def __init__(self) -> None:
            self.handlers: dict[type[Exception], object] = {}

        def exception_handler(self, error_type):
            def register(handler):
                self.handlers[error_type] = handler
                return handler

            return register

    app = FakeApp()

    register_status_detail_exception_handlers(app, FirstError, SecondError)

    assert set(app.handlers) == {FirstError, SecondError}
    first_response = asyncio.run(app.handlers[FirstError](None, FirstError("first")))
    second_response = asyncio.run(app.handlers[SecondError](None, SecondError("second")))
    assert first_response.status_code == 409
    assert second_response.status_code == 503


def test_api_value_error_status_classification_lives_outside_route_errors() -> None:
    route_errors = _source("apps/api/route_errors.py")
    remote_route_errors = _source("apps/remote_runner/route_errors.py")
    response_helper = _source("core/problem_responses.py")
    shared_errors = _source("core/problem_status.py")

    assert "def value_error_status_code(" not in route_errors
    assert "detail.startswith(" not in route_errors
    assert "problem_value_error_status_code(" not in route_errors
    assert "problem_value_error_status_code(" not in remote_route_errors
    assert "value_error_response(exc)" in route_errors
    assert "value_error_response(exc)" in remote_route_errors
    assert "problem_value_error_status_code(detail)" in response_helper
    assert "def value_error_response(" in response_helper
    assert "def problem_value_error_status_code(" in shared_errors


def test_runtime_service_http_status_is_not_parsed_in_api_route_errors() -> None:
    source = _source("apps/api/route_errors.py")

    assert "import re" not in source
    assert "runner http error" not in source
    assert "def _remote_http_status_code(" not in source
    assert "def _remote_http_detail(" not in source
    assert "runtime_service_status_code(exc)" in source
    assert "runtime_service_detail(exc)" in source


def test_runtime_service_status_classifier_lives_in_app_runtime_error_layer() -> None:
    api_source = _source("apps/api/run_submission_status.py")
    core_source = _source("core/app_runtime/errors.py")

    assert "def classify_runtime_service_status(" in core_source
    assert "readiness_markers" not in api_source
    assert "from core.app_runtime.errors import classify_runtime_service_status" in api_source


def test_api_services_centralize_request_dumping_in_route_utils() -> None:
    route_utils_source = _source("apps/api/route_utils.py")
    service_sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (ROOT / "apps" / "api").glob("*_service.py")
    }

    offenders = [
        name
        for name, source in sorted(service_sources.items())
        if ".model_dump(" in source
    ]

    assert "from core.api_payloads import request_payload" in route_utils_source
    assert "def request_payload(" not in route_utils_source
    assert "request.model_dump(" not in route_utils_source
    assert offenders == []


def test_request_payload_serialization_policy_lives_in_core_helper() -> None:
    core_source = _source("core/api_payloads.py")
    api_route_utils_source = _source("apps/api/route_utils.py")
    remote_route_utils_source = _source("apps/remote_runner/route_utils.py")

    assert "from core.api_payloads import request_payload" in api_route_utils_source
    assert "from core.api_payloads import request_payload" in remote_route_utils_source
    assert "def request_payload(" not in api_route_utils_source
    assert "def request_payload(" not in remote_route_utils_source
    assert "request.model_dump(" not in api_route_utils_source
    assert "request.model_dump(" not in remote_route_utils_source
    assert "def request_payload(" in core_source
    assert "request.runtime_payload()" in core_source
    assert 'request.model_dump(by_alias=by_alias, exclude_none=True, mode="json")' in core_source


def test_request_payload_uses_runtime_payload_before_model_dump() -> None:
    from core.api_payloads import request_payload

    class RuntimePayloadRequest:
        def runtime_payload(self):
            return {"aliasName": "kept"}

    class ModelDumpRequest:
        def __init__(self) -> None:
            self.call: dict[str, object] | None = None

        def model_dump(self, *, by_alias: bool, exclude_none: bool, mode: str):
            self.call = {
                "by_alias": by_alias,
                "exclude_none": exclude_none,
                "mode": mode,
            }
            return {"dumped": True}

    dumped = ModelDumpRequest()

    assert request_payload(None) == {}
    assert request_payload(RuntimePayloadRequest()) == {"aliasName": "kept"}
    assert request_payload(dumped, by_alias=True) == {"dumped": True}
    assert dumped.call == {
        "by_alias": True,
        "exclude_none": True,
        "mode": "json",
    }


def test_workflow_catalog_routes_delegate_cache_to_service() -> None:
    route_source = _source("apps/api/workflow_catalog_routes.py")
    service_source = _source("apps/api/workflow_catalog_service.py")

    assert "from apps.api.response_cache" not in route_source
    assert "cached_response(" not in route_source
    assert "load_workflow_catalog" not in route_source
    assert "load_run_detail" not in route_source
    assert "lambda:" not in route_source
    assert "get_workflow_catalog_from_request" in route_source
    assert "get_run_detail_from_request" in route_source

    assert "def get_workflow_catalog_from_request(" in service_source
    assert "def get_run_detail_from_request(" in service_source
    assert "from apps.api.runtime import get_runtime_service" not in service_source
    assert "from apps.api.route_utils import run_sync, runtime_service" in service_source
    assert "asyncio.to_thread" not in service_source
    assert "runtime = runtime_service()" in service_source
    assert "await run_sync(" in service_source


def test_workflow_sample_data_service_uses_runtime_infrastructure() -> None:
    service_source = _source("apps/api/workflow_sample_data_service.py")

    assert "from apps.api.runtime import get_runtime_service" not in service_source
    assert "from apps.api.route_utils import run_sync, runtime_service" in service_source
    assert "asyncio.to_thread" not in service_source
    assert "await run_sync(_download_and_upload_moving_pictures)" in service_source
    assert "runtime = runtime_service()" in service_source


def test_workflow_catalog_service_fails_loudly_on_invalid_manifests() -> None:
    service_source = _source("apps/api/workflow_catalog_service.py")

    assert "from core.contracts.pipeline_manifest import validate_pipeline_manifest" in service_source
    assert "PipelineRegistryError" not in service_source
    assert "json.JSONDecodeError" not in service_source
    assert "errors = []" not in service_source
    assert "pipelineError" not in service_source
    assert "return items, errors" not in service_source
    assert "RuntimeServiceError" not in service_source
    assert "except RuntimeServiceError" not in service_source


def test_tool_routes_delegate_request_dumping_to_service() -> None:
    main_source = _source("apps/api/main.py")
    route_source = _source("apps/api/tool_routes.py")
    service_source = _source("apps/api/tool_service.py")

    assert "from apps.api.tool_routes import router as tool_router" in main_source
    assert "app.include_router(tool_router)" in main_source
    assert '@app.get("/api/v1/tools")' not in main_source
    assert '@app.post("/api/v1/tools", status_code=201)' not in main_source

    tool_list_start = route_source.index('@router.get("/api/v1/tools")')
    tool_list_end = route_source.index('@router.post("/api/v1/tools", status_code=201)')
    tool_list_route = route_source[tool_list_start:tool_list_end]
    tool_route_start = route_source.index('@router.post("/api/v1/tools", status_code=201)')
    tool_route_end = len(route_source)
    tool_routes = route_source[tool_route_start:tool_route_end]

    for routes in (tool_list_route, tool_routes):
        assert "_runtime()" not in routes
        assert "_run_runtime_payload" not in routes
        assert "_cached_runtime_payload" not in routes

    assert "router = APIRouter()" in route_source
    assert "from apps.api.route_utils" not in route_source
    assert "runtime_service()" not in route_source
    assert "payload.model_dump(" not in tool_routes
    assert "invalidate_response_cache" not in tool_routes
    assert "list_tools_from_request" in tool_list_route
    assert "add_tool_from_request" in tool_routes
    assert "create_tool_prepare_job_from_request" in tool_routes
    assert "get_tool_prepare_job_from_request" in tool_routes
    assert "cancel_tool_prepare_job_from_request" in tool_routes
    assert "update_tool_rule_template_from_request" in tool_routes
    assert "delete_tool_from_request" in tool_routes

    assert "def list_tools_from_request(" in service_source
    assert "def add_tool_from_request(" in service_source
    assert "def create_tool_prepare_job_from_request(" in service_source
    assert "def get_tool_prepare_job_from_request(" in service_source
    assert "def cancel_tool_prepare_job_from_request(" in service_source
    assert "def update_tool_rule_template_from_request(" in service_source
    assert "def delete_tool_from_request(" in service_source


def test_tool_contract_routes_delegate_request_dumping_to_service() -> None:
    route_source = _source("apps/api/tool_contract_routes.py")
    service_path = ROOT / "apps/api/tool_contract_service.py"

    assert service_path.exists()
    service_source = service_path.read_text(encoding="utf-8")

    assert "payload.model_dump(" not in route_source
    assert "body = payload.model_dump" not in route_source
    assert "invalidate_response_cache" not in route_source
    assert "mark_tool_production_from_request" in route_source

    assert "def mark_tool_production_from_request(" in service_source


def test_ssh_routes_delegate_request_dumping_and_cache_to_service() -> None:
    main_source = _source("apps/api/main.py")
    route_source = _source("apps/api/ssh_routes.py")
    service_path = ROOT / "apps/api/ssh_control_service.py"

    assert service_path.exists()
    service_source = service_path.read_text(encoding="utf-8")

    assert "from apps.api.ssh_routes import router as ssh_router" in main_source
    assert "app.include_router(ssh_router)" in main_source
    assert '@app.get("/api/v1/ssh/status")' not in main_source
    assert '@app.post("/api/v1/ssh/connect")' not in main_source
    assert '@app.websocket("/api/v1/ssh/terminal/sessions/{session_id}/stream")' not in main_source

    ssh_route_start = route_source.index('@router.post("/api/v1/servers/{server_id}/ensure-runner")')
    ssh_route_end = route_source.index('@router.get("/api/v1/ssh/listening-ports")')
    ssh_routes = route_source[ssh_route_start:ssh_route_end]
    ssh_test_route_start = route_source.index('@router.post("/api/v1/ssh/test")')
    ssh_test_route_end = len(route_source)
    ssh_test_route = route_source[ssh_test_route_start:ssh_test_route_end]

    assert "router = APIRouter()" in route_source
    assert "from apps.api.route_utils" not in route_source
    assert "runtime_service()" not in route_source
    assert "payload.model_dump(" not in ssh_routes
    assert "payload.model_dump(" not in ssh_test_route
    assert "invalidate_response_cache" not in ssh_routes
    assert "ensure_server_runner_from_request" in ssh_routes
    assert "accept_server_host_key_from_request" in ssh_routes
    assert "rotate_server_token_from_request" in ssh_routes
    assert "connect_ssh_from_request" in ssh_routes
    assert "disconnect_ssh_from_request" in ssh_routes
    assert "stop_ssh_remote_service_from_request" in ssh_routes
    assert "test_ssh_connection_from_request" in ssh_test_route

    assert "def ensure_server_runner_from_request(" in service_source
    assert "def accept_server_host_key_from_request(" in service_source
    assert "def rotate_server_token_from_request(" in service_source
    assert "def connect_ssh_from_request(" in service_source
    assert "def disconnect_ssh_from_request(" in service_source
    assert "def stop_ssh_remote_service_from_request(" in service_source
    assert "def test_ssh_connection_from_request(" in service_source


def test_ssh_read_and_terminal_routes_delegate_runtime_calls_to_service() -> None:
    route_source = _source("apps/api/ssh_routes.py")
    service_source = _source("apps/api/ssh_control_service.py")
    terminal_service_source = _source("apps/api/ssh_terminal_service.py")
    websocket_marker = '@router.websocket("/api/v1/ssh/terminal/sessions/{session_id}/stream")'

    status_route_start = route_source.index('@router.get("/api/v1/ssh/status")')
    status_route_end = route_source.index('@router.post("/api/v1/servers/{server_id}/ensure-runner")')
    status_routes = route_source[status_route_start:status_route_end]
    browser_route_start = route_source.index('@router.get("/api/v1/ssh/listening-ports")')
    browser_route_end = route_source.index(websocket_marker)
    browser_routes = route_source[browser_route_start:browser_route_end]
    stream_route_start = route_source.index(websocket_marker)
    stream_route_end = route_source.index('@router.post("/api/v1/ssh/test")')
    stream_route = route_source[stream_route_start:stream_route_end]

    for routes in (status_routes, browser_routes):
        assert "_runtime()" not in routes
        assert "_run_runtime_payload" not in routes
        assert "_cached_runtime_payload" not in routes

    assert "from apps.api.route_utils" not in route_source
    assert "runtime_provider=_runtime" not in stream_route
    assert "get_ssh_status_from_request" in status_routes
    assert "list_servers_from_request" in status_routes
    assert "get_server_from_request" in status_routes
    assert "get_server_health_from_request" in status_routes
    assert "refresh_server_health_from_request" in status_routes
    assert "list_ssh_listening_ports_from_request" in browser_routes
    assert "list_ssh_remote_files_from_request" in browser_routes
    assert "create_terminal_session_from_request" in browser_routes
    assert "close_terminal_session_from_request" in browser_routes
    assert "stream_terminal_session_from_request" in stream_route

    assert "def get_ssh_status_from_request(" in service_source
    assert "def list_servers_from_request(" in service_source
    assert "def get_server_from_request(" in service_source
    assert "def get_server_health_from_request(" in service_source
    assert "def refresh_server_health_from_request(" in service_source
    assert "def list_ssh_listening_ports_from_request(" in service_source
    assert "def list_ssh_remote_files_from_request(" in service_source
    assert "def create_terminal_session_from_request(" in service_source
    assert "def close_terminal_session_from_request(" in service_source
    assert "def stream_terminal_session_from_request(" in service_source
    assert "from fastapi import WebSocket" not in service_source
    assert "TerminalWebSocket" in service_source
    assert "class TerminalWebSocket(Protocol)" in terminal_service_source
    assert "from fastapi import WebSocket, WebSocketDisconnect" not in terminal_service_source
    assert "from fastapi import WebSocketDisconnect" in terminal_service_source
