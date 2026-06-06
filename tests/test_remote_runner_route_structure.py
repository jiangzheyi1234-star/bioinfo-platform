from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_workflow_design_plan_and_compile_paths_live_in_service() -> None:
    route_source = _source("apps/remote_runner/workflow_design_routes.py")
    service_source = _source("apps/remote_runner/workflow_design_service.py")

    assert "compile_workflow_design_draft_export" not in route_source
    assert "plan_workflow_design_draft_preview" not in route_source
    assert "plan_workflow_design_draft_from_request" in route_source
    assert "compile_workflow_design_draft_from_request" in route_source
    assert "Path(" not in route_source
    assert "preview_root=" not in route_source
    assert "export_dir=" not in route_source

    assert "def plan_workflow_design_draft_from_request(" in service_source
    assert "def compile_workflow_design_draft_from_request(" in service_source
    assert "def plan_workflow_design_draft_preview(" in service_source
    assert "def compile_workflow_design_draft_export(" in service_source
    assert 'Path(cfg.work_dir) / "workflow-design-previews" / draft_id' in service_source
    assert 'Path(cfg.work_dir) / "workflow-design-exports" / draft_id' in service_source


def test_workflow_design_routes_delegate_request_dumping_to_services() -> None:
    route_source = _source("apps/remote_runner/workflow_design_routes.py")
    service_source = _source("apps/remote_runner/workflow_design_service.py")
    shared_contract_source = _source("core/contracts/workflow_design.py")
    route_utils_source = _source("apps/remote_runner/route_utils.py")

    assert "from starlette.concurrency import run_in_threadpool" not in route_source
    assert "from .route_utils import" not in route_source
    assert "from .workflow_design_storage import" not in route_source
    assert "authorized_config(" not in route_source
    assert "data_response(" not in route_source
    assert "payload.draft.model_dump(" not in route_source
    assert "payload.expectedRevision" not in route_source
    assert "payload.name" not in route_source
    assert "create_workflow_design_draft_response_from_request" in route_source
    assert "update_workflow_design_draft_response_from_request" in route_source
    assert "fork_workflow_design_draft_response_from_request" in route_source
    assert "delete_workflow_design_draft_from_request" in route_source
    assert "get_workflow_design_draft_from_request" in route_source
    assert "list_workflow_design_drafts_from_request" in route_source

    assert "def create_workflow_design_draft_response_from_request(" in service_source
    assert "def update_workflow_design_draft_response_from_request(" in service_source
    assert "def fork_workflow_design_draft_response_from_request(" in service_source
    assert "def delete_workflow_design_draft_from_request(" in service_source
    assert "def get_workflow_design_draft_from_request(" in service_source
    assert "def list_workflow_design_drafts_from_request(" in service_source
    assert "def create_workflow_design_draft_from_request(" in service_source
    assert "def update_workflow_design_draft_from_request(" in service_source
    assert "def fork_workflow_design_draft_from_request(" in service_source
    assert "from .route_utils import authorized_config, data_response, request_payload, run_sync" in service_source
    assert "from starlette.concurrency import run_in_threadpool" not in service_source
    assert "run_in_threadpool(" not in service_source
    assert "await run_sync(" in service_source
    assert "request.draft.model_dump(" not in service_source
    assert "by_alias=True" not in service_source
    assert "request_payload(request.draft)" in service_source
    assert not (ROOT / "apps" / "remote_runner" / "workflow_design_contract.py").exists()
    assert "def runtime_payload(self) -> dict[str, Any]:" in shared_contract_source
    assert "from core.async_boundary import run_sync" in route_utils_source
    assert "from core.api_responses import data_response" in route_utils_source
    assert "from core.api_payloads import request_payload" in route_utils_source
    assert "def data_response(" not in route_utils_source
    assert "def run_sync(" not in route_utils_source
    assert "run_in_threadpool" not in route_utils_source
    assert "request.runtime_payload()" not in route_utils_source


def test_workflow_design_revision_conflicts_are_domain_errors() -> None:
    storage_source = _source("apps/remote_runner/workflow_design_storage.py")
    errors_source = _source("apps/remote_runner/errors.py")
    remote_route_errors_source = _source("apps/remote_runner/route_errors.py")
    local_route_errors_source = _source("apps/api/route_errors.py")

    assert "class WorkflowDesignRevisionConflictError(ValueError)" in errors_source
    assert "WorkflowDesignRevisionConflictError(ValueError):\n    status_code = 409" in errors_source
    assert "WorkflowDesignRevisionConflictError" in storage_source
    assert 'raise WorkflowDesignRevisionConflictError("WORKFLOW_DESIGN_REVISION_CONFLICT")' in storage_source
    assert "register_status_detail_exception_handlers(" in remote_route_errors_source
    assert "WorkflowDesignRevisionConflictError," in remote_route_errors_source
    assert "status_detail_response(exc)" not in remote_route_errors_source
    assert "detail_response(exc.status_code, str(exc))" not in remote_route_errors_source
    assert "detail_response(409, str(exc))" not in remote_route_errors_source
    assert "WORKFLOW_DESIGN_REVISION_CONFLICT" not in remote_route_errors_source
    assert "WORKFLOW_DESIGN_REVISION_CONFLICT" not in local_route_errors_source


def test_run_preflight_status_codes_live_on_domain_errors() -> None:
    errors_source = _source("apps/remote_runner/errors.py")
    preflight_source = _source("apps/remote_runner/preflight.py")
    route_errors_source = _source("apps/remote_runner/route_errors.py")
    generated_plan_source = _source("apps/remote_runner/generated_workflow_plan.py")

    assert "class WorkflowToolNotReadyError(ValueError)" in errors_source
    assert "raise WorkflowToolNotReadyError(" in generated_plan_source
    assert "def run_preflight_status_code(" not in route_errors_source
    assert "WORKFLOW_TOOL_NOT_READY" not in route_errors_source
    assert "RunPreflightError," in route_errors_source
    assert "status_detail_response(exc)" not in route_errors_source
    assert "RunPreflightError.from_value_error" in preflight_source
    assert 'getattr(exc, "status_code"' not in preflight_source
    assert "isinstance(exc, WorkflowToolNotReadyError)" in preflight_source


def test_generated_workflow_plan_delegates_binding_and_output_resolution() -> None:
    plan_source = _source("apps/remote_runner/generated_workflow_plan.py")
    steps_path = ROOT / "apps" / "remote_runner" / "generated_workflow_steps.py"
    ports_path = ROOT / "apps" / "remote_runner" / "generated_workflow_ports.py"
    outputs_path = ROOT / "apps" / "remote_runner" / "generated_workflow_outputs.py"
    names_path = ROOT / "apps" / "remote_runner" / "generated_workflow_names.py"

    assert len(plan_source.splitlines()) <= 230
    assert "from .generated_workflow_steps import" in plan_source
    assert "from .generated_workflow_ports import" in plan_source
    assert "from .generated_workflow_outputs import resolve_exposed_outputs" not in plan_source
    assert "from .generated_workflow_names import" in plan_source

    for helper_name in (
        "resolve_requested_steps",
        "topologically_order_steps",
        "step_input_dependencies",
        "resolve_step_params",
        "resolve_step_inputs",
        "resolve_outputs",
        "resolve_exposed_outputs",
        "safe_identifier",
        "safe_snakemake_name",
        "safe_relative_output_path",
    ):
        assert f"def {helper_name}(" not in plan_source

    assert steps_path.exists()
    assert ports_path.exists()
    assert outputs_path.exists()
    assert names_path.exists()

    steps_source = steps_path.read_text(encoding="utf-8")
    ports_source = ports_path.read_text(encoding="utf-8")
    outputs_source = outputs_path.read_text(encoding="utf-8")
    names_source = names_path.read_text(encoding="utf-8")

    assert "def topologically_order_steps(" in steps_source
    assert "def resolve_step_inputs(" in ports_source
    assert "def resolve_outputs(" in ports_source
    assert "def resolve_exposed_outputs(" in outputs_source
    assert "def safe_identifier(" in names_source
    assert "def safe_snakemake_name(" in names_source


def test_value_error_status_classification_lives_outside_remote_route_errors() -> None:
    route_errors_source = _source("apps/remote_runner/route_errors.py")
    api_route_errors_source = _source("apps/api/route_errors.py")
    response_helper = _source("core/problem_responses.py")
    shared_errors = _source("core/problem_status.py")

    assert "def value_error_status_code(" not in route_errors_source
    assert "detail.startswith(" not in route_errors_source
    assert "problem_value_error_status_code(" not in route_errors_source
    assert "problem_value_error_status_code(" not in api_route_errors_source
    assert "value_error_response(exc)" in route_errors_source
    assert "value_error_response(exc)" in api_route_errors_source
    assert "problem_value_error_status_code(detail)" in response_helper
    assert "def value_error_response(" in response_helper
    assert "def problem_value_error_status_code(" in shared_errors


def test_idempotency_reuse_status_code_lives_on_domain_error() -> None:
    errors_source = _source("apps/remote_runner/errors.py")
    storage_source = _source("apps/remote_runner/workflow_run_storage.py")
    route_errors_source = _source("apps/remote_runner/route_errors.py")

    assert "class IdempotencyKeyReusedError(ValueError)" in errors_source
    assert "IdempotencyKeyReusedError" in storage_source
    assert 'raise IdempotencyKeyReusedError("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD")' in storage_source
    assert "IdempotencyKeyReusedError," in route_errors_source
    assert "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD" not in route_errors_source


def test_upload_size_status_code_lives_on_domain_error() -> None:
    errors_source = _source("apps/remote_runner/errors.py")
    storage_source = _source("apps/remote_runner/upload_storage.py")
    route_errors_source = _source("apps/remote_runner/route_errors.py")

    assert "class UploadTooLargeError(ValueError)" in errors_source
    assert "UploadTooLargeError" in storage_source
    assert 'raise UploadTooLargeError("UPLOAD_TOO_LARGE")' in storage_source
    assert "UploadTooLargeError," in route_errors_source
    assert "UPLOAD_TOO_LARGE" not in route_errors_source


def test_pipeline_not_found_status_lives_on_domain_error() -> None:
    pipeline_source = _source("apps/remote_runner/pipeline.py")
    shared_pipeline_source = _source("core/contracts/pipeline_manifest.py")
    route_errors_source = _source("apps/remote_runner/route_errors.py")

    assert "from core.contracts.pipeline_manifest import (" in pipeline_source
    assert "class PipelineRegistryError(ValueError):\n    status_code = 400" in shared_pipeline_source
    assert "class PipelineNotFoundError(PipelineRegistryError)" in pipeline_source
    assert "def validate_pipeline_manifest(" not in pipeline_source
    assert 'raise PipelineNotFoundError("PIPELINE_NOT_FOUND")' in pipeline_source
    assert "def pipeline_registry_status_code(" not in route_errors_source
    assert "PIPELINE_NOT_FOUND" not in route_errors_source
    assert "getattr(exc, \"status_code\", 400)" not in route_errors_source
    assert "PipelineRegistryError," in route_errors_source
    assert "status_detail_response(exc)" not in route_errors_source
    assert "detail_response(exc.status_code, detail)" not in route_errors_source


def test_auth_errors_are_domain_errors_handled_by_problem_layer() -> None:
    helper_source = _source("apps/remote_runner/route_utils.py")
    errors_source = _source("apps/remote_runner/errors.py")
    route_errors_source = _source("apps/remote_runner/route_errors.py")
    lifecycle_source = _source("tests/test_remote_runner_api_lifecycle.py")

    assert "HTTPException" not in helper_source
    assert "RemoteRunnerAuthError" in helper_source
    assert "class RemoteRunnerAuthError(ValueError)" in errors_source
    assert "RemoteRunnerAuthError(ValueError):\n    status_code = 401" in errors_source
    assert "RemoteRunnerAuthError," in route_errors_source
    assert "detail_response(401, str(exc))" not in route_errors_source
    assert "from fastapi import HTTPException" not in lifecycle_source
    assert "except HTTPException" not in lifecycle_source
    assert "pytest.raises(RemoteRunnerAuthError" in lifecycle_source


def test_authorization_header_binding_lives_in_shared_route_type() -> None:
    header_path = ROOT / "apps/remote_runner/route_headers.py"
    route_paths = (
        "apps/remote_runner/health_routes.py",
        "apps/remote_runner/pipeline_routes.py",
        "apps/remote_runner/submission_routes.py",
        "apps/remote_runner/execution_query_routes.py",
        "apps/remote_runner/database_routes.py",
        "apps/remote_runner/workflow_design_routes.py",
        "apps/remote_runner/tool_routes.py",
    )

    assert header_path.exists()
    header_source = header_path.read_text(encoding="utf-8")

    assert "AuthorizationHeader =" in header_source
    assert "IdempotencyKeyHeader =" in header_source
    assert "RequestIdHeader =" in header_source
    assert "Header()" in header_source
    assert 'alias="Idempotency-Key"' in header_source
    assert 'alias="X-Request-Id"' in header_source

    for path in route_paths:
        route_source = _source(path)

        assert "from .route_headers import AuthorizationHeader" in route_source
        assert "from fastapi import APIRouter, Header" not in route_source
        assert "from fastapi import APIRouter, BackgroundTasks, Header" not in route_source
        assert "Header(default=None)" not in route_source
        assert "authorization: str | None = Header" not in route_source
        assert "authorization: AuthorizationHeader = None" in route_source

    submission_source = _source("apps/remote_runner/submission_routes.py")

    assert "IdempotencyKeyHeader" in submission_source
    assert "RequestIdHeader" in submission_source
    assert "idempotency_key: IdempotencyKeyHeader = None" in submission_source
    assert "x_request_id: RequestIdHeader = None" in submission_source


def test_remote_runner_control_status_codes_live_on_domain_errors() -> None:
    errors_source = _source("apps/remote_runner/errors.py")
    route_errors_source = _source("apps/remote_runner/route_errors.py")

    assert "RemoteRunnerNotFoundError(ValueError):\n    status_code = 404" in errors_source
    assert "RemoteRunnerReadinessError(ValueError):\n    status_code = 503" in errors_source
    assert "detail_response(503, str(exc))" not in route_errors_source
    assert "detail_response(404, str(exc))" not in route_errors_source
    assert "register_status_detail_exception_handlers(" in route_errors_source
    assert "RemoteRunnerNotFoundError," in route_errors_source
    assert "RemoteRunnerReadinessError," in route_errors_source
    assert "status_detail_response(exc)" not in route_errors_source
    assert "detail_response(exc.status_code, str(exc))" not in route_errors_source


def test_remote_runner_direct_call_tests_do_not_import_fastapi_http_exceptions() -> None:
    for path in (
        "tests/test_remote_runner_api_lifecycle.py",
        "tests/test_remote_runner_bootstrap_deploy.py",
        "tests/test_remote_runner_bootstrap_workflow_runtime.py",
        "tests/test_remote_runner_executor.py",
        "tests/test_remote_runner_reuse_lock_manager.py",
    ):
        source = _source(path)

        assert "from fastapi import HTTPException" not in source
        assert "except HTTPException" not in source
        assert "pytest.raises(HTTPException" not in source


def test_tool_manifest_routes_delegate_request_dumping_to_services() -> None:
    route_source = _source("apps/remote_runner/tool_routes.py")
    service_source = _source("apps/remote_runner/tool_service.py")
    tools_source = _source("apps/remote_runner/tools.py")
    prepare_source = _source("apps/remote_runner/tool_prepare_job_storage.py")

    assert "from starlette.concurrency import run_in_threadpool" not in route_source
    assert "from .route_utils import" not in route_source
    assert "from .tools import" not in route_source
    assert "from .tool_prepare_job_storage import" not in route_source
    assert "from .tool_prepare_jobs import" not in route_source
    assert "authorized_config(" not in route_source
    assert "data_response(" not in route_source
    assert "payload.model_dump(exclude_none=True)" not in route_source
    assert "payload.ruleTemplate" not in route_source
    assert "background_tasks.add_task(" not in route_source
    assert "list_tools_from_request" in route_source
    assert "list_tool_index_from_request" in route_source
    assert "add_tool_from_request" in route_source
    assert "create_tool_prepare_job_response_from_request" in route_source
    assert "get_tool_prepare_job_from_request" in route_source
    assert "cancel_tool_prepare_job_from_request" in route_source
    assert "update_tool_rule_template_from_request" in route_source
    assert "delete_tool_from_request" in route_source
    assert "mark_tool_production_from_request" in route_source

    assert "def list_tools_from_request(" in service_source
    assert "def list_tool_index_from_request(" in service_source
    assert "def add_tool_from_request(" in service_source
    assert "def create_tool_prepare_job_response_from_request(" in service_source
    assert "def get_tool_prepare_job_from_request(" in service_source
    assert "def cancel_tool_prepare_job_from_request(" in service_source
    assert "def update_tool_rule_template_from_request(" in service_source
    assert "def delete_tool_from_request(" in service_source
    assert "def mark_tool_production_from_request(" in service_source
    assert "run_tool_prepare_job" in service_source
    assert "from fastapi import BackgroundTasks" not in service_source
    assert "class BackgroundTaskScheduler(Protocol)" in service_source
    assert "def add_registered_tool_from_request(" not in tools_source
    assert "def mark_registered_tool_production_enabled_from_request(" not in tools_source
    assert "from .route_utils import authorized_config, data_response, request_payload, run_sync" in service_source
    assert "from starlette.concurrency import run_in_threadpool" not in service_source
    assert "run_in_threadpool(" not in service_source
    assert "await run_sync(" in service_source
    assert "payload.model_dump(exclude_none=True)" not in service_source
    assert "request_payload(payload)" in service_source
    assert "create_tool_prepare_job, cfg, request_payload(payload)" in service_source
    assert "ToolManifestRequest" not in prepare_source
    assert "request.model_dump(" not in prepare_source
    assert "def create_tool_prepare_job_from_request(" not in prepare_source


def test_remote_runner_main_import_does_not_depend_on_tool_model_cycle() -> None:
    import importlib

    tools_source = _source("apps/remote_runner/tools.py")
    databases_source = _source("apps/remote_runner/databases.py")

    assert "ToolManifestRequest" not in tools_source
    assert "ToolProductionEvidenceRequest" not in tools_source
    assert "DatabaseManifestRequest" not in databases_source
    assert "DatabaseUpdateRequest" not in databases_source
    assert "from .api_models import" not in databases_source
    main_module = importlib.import_module("apps.remote_runner.main")
    assert callable(main_module.app.include_router)


def test_remote_runner_tool_registry_stays_below_source_line_budget() -> None:
    tools_source = _source("apps/remote_runner/tools.py")
    capability_source = _source("apps/remote_runner/tool_capability_normalization.py")
    rule_template_source = _source("apps/remote_runner/tool_rule_template_normalization.py")
    rule_resources_path = ROOT / "apps" / "remote_runner" / "tool_rule_resources.py"
    rule_environment_path = ROOT / "apps" / "remote_runner" / "tool_rule_environment.py"
    rule_tokens_path = ROOT / "apps" / "remote_runner" / "tool_rule_command_tokens.py"
    rule_names_path = ROOT / "apps" / "remote_runner" / "tool_rule_names.py"

    assert len(tools_source.splitlines()) <= 260
    assert len(rule_template_source.splitlines()) <= 390
    assert "from .tool_capability_normalization import normalize_tool_capabilities" in tools_source
    assert "from .tool_rule_template_normalization import normalize_rule_template" in tools_source
    assert "def normalize_tool_capabilities(" not in tools_source
    assert "def normalize_rule_template(" not in tools_source
    assert "def _normalize_rule_resources(" not in tools_source
    assert "RULE_TOKEN_RE" not in tools_source
    assert "def normalize_tool_capabilities(" in capability_source
    assert "def normalize_rule_template(" in rule_template_source
    assert "from .tool_rule_command_tokens import validate_command_tokens" in rule_template_source
    assert "from .tool_rule_environment import normalize_rule_environment" in rule_template_source
    assert "from .tool_rule_resources import (" in rule_template_source
    assert "from .tool_rule_names import (" in rule_template_source
    assert "def _normalize_rule_resources(" not in rule_template_source
    assert "def _normalize_scheduler_resources(" not in rule_template_source
    assert "def _normalize_rule_environment(" not in rule_template_source
    assert "def _validate_command_tokens(" not in rule_template_source
    assert "RULE_TOKEN_RE" not in rule_template_source

    assert rule_resources_path.exists()
    assert rule_environment_path.exists()
    assert rule_tokens_path.exists()
    assert rule_names_path.exists()
    rule_resources_source = rule_resources_path.read_text(encoding="utf-8")
    rule_environment_source = rule_environment_path.read_text(encoding="utf-8")
    rule_tokens_source = rule_tokens_path.read_text(encoding="utf-8")
    rule_names_source = rule_names_path.read_text(encoding="utf-8")

    assert "def normalize_rule_resources(" in rule_resources_source
    assert "def normalize_scheduler_resources(" in rule_resources_source
    assert "def normalize_rule_threads(" in rule_resources_source
    assert "def normalize_rule_environment(" in rule_environment_source
    assert "def validate_command_tokens(" in rule_tokens_source
    assert "RULE_TOKEN_RE" in rule_tokens_source
    assert "def normalize_io_name(" in rule_names_source
    assert "def validate_relative_output_path(" in rule_names_source


def test_tool_contract_resource_wait_logic_lives_outside_validation_flow() -> None:
    validation_source = _source("apps/remote_runner/tool_contract_validation.py")
    resources_source = _source("apps/remote_runner/tool_contract_resources.py")
    preparation_source = _source("apps/remote_runner/tool_preparation.py")

    assert len(validation_source.splitlines()) <= 700
    assert "from .tool_contract_resources import" in validation_source
    assert "from .database_templates import DATABASE_TEMPLATES" not in validation_source
    assert "from .databases import list_reference_databases" not in validation_source
    assert "WAITING_RESOURCE_CODES" not in validation_source
    assert "def build_resource_wait_details(" not in validation_source
    assert "def _workflow_resource_failure(" not in validation_source
    assert "def _smoke_resource_bindings(" not in validation_source
    assert "def build_resource_wait_details(" in resources_source
    assert "def workflow_resource_failure(" in resources_source
    assert "def smoke_resource_bindings(" in resources_source
    assert "WAITING_RESOURCE_CODES" in resources_source
    assert "from .tool_contract_resources import WAITING_RESOURCE_CODES, build_resource_wait_details" in preparation_source
    assert "from .tool_contract_validation import WAITING_RESOURCE_CODES" not in preparation_source


def test_tool_contract_output_validation_lives_outside_validation_flow() -> None:
    validation_source = _source("apps/remote_runner/tool_contract_validation.py")
    output_path = ROOT / "apps" / "remote_runner" / "tool_output_validation.py"

    assert output_path.exists()
    output_source = output_path.read_text(encoding="utf-8")

    assert len(validation_source.splitlines()) <= 540
    assert "from .tool_output_validation import" in validation_source
    assert "_validate_outputs" in validation_source
    assert "_validated_output_summary" in validation_source
    assert "def _validate_outputs(" not in validation_source
    assert "def _blank_text_output(" not in validation_source
    assert "def _parseable_output_error(" not in validation_source
    assert "def _validated_output_summary(" not in validation_source
    assert "def _validate_outputs(" in output_source
    assert "def _blank_text_output(" in output_source
    assert "def _parseable_output_error(" in output_source
    assert "def _validated_output_summary(" in output_source


def test_remote_runner_process_entrypoint_fails_loudly_on_process_name_errors() -> None:
    source = _source("apps/remote_runner/run.py")

    assert "except Exception" not in source
    assert "failed to set process name" not in source
    assert "raise RuntimeError" in source


def test_executor_startup_failure_boundary_uses_declared_runtime_errors() -> None:
    source = _source("apps/remote_runner/executor.py")
    adapter_source = _source("apps/remote_runner/workflow_engine_adapter.py")

    assert "except Exception as exc" not in source
    assert "class WorkflowRuntimeCommandError(RuntimeError):" in adapter_source
    assert 'raise WorkflowRuntimeCommandError("snakemake command not configured")' in adapter_source
    assert "except (WorkflowRuntimeCommandError, OSError, subprocess.SubprocessError) as exc" in source


def test_executor_delegates_snakemake_invocation_to_engine_adapter() -> None:
    source = _source("apps/remote_runner/executor.py")
    adapter_source = _source("apps/remote_runner/workflow_engine_adapter.py")

    assert "from .workflow_engine_adapter import (" in source
    assert "SnakemakeEngineAdapter" in source
    assert "WorkflowEngineAdapter" in adapter_source
    assert "class SnakemakeEngineAdapter:" in adapter_source
    assert "def dry_run(" in adapter_source
    assert "def run(" in adapter_source
    assert "subprocess.run(" not in source
    assert "dry_run = engine.dry_run(" in source
    assert "run_result = engine.run(" in source


def test_executor_artifact_collection_lives_outside_execution_flow() -> None:
    executor_source = _source("apps/remote_runner/executor.py")
    artifact_path = ROOT / "apps" / "remote_runner" / "executor_artifacts.py"
    io_path = ROOT / "apps" / "remote_runner" / "executor_inputs.py"

    assert len(executor_source.splitlines()) <= 350
    assert "from .executor_artifacts import _collect_artifacts" in executor_source
    assert "from .executor_inputs import _build_run_outputs, _resolve_run_inputs" in executor_source
    assert "from .tool_contract_validation import _validate_outputs" not in executor_source
    assert "fetch_upload" not in executor_source
    assert "persist_artifact" not in executor_source
    assert "def _collect_artifacts(" not in executor_source
    assert "def _resolve_run_inputs(" not in executor_source
    assert "def _build_run_outputs(" not in executor_source

    assert artifact_path.exists()
    assert io_path.exists()
    artifact_source = artifact_path.read_text(encoding="utf-8")
    io_source = io_path.read_text(encoding="utf-8")
    assert "def _collect_artifacts(" in artifact_source
    assert "from .tool_contract_validation import _validate_outputs" in artifact_source
    assert "from .storage import persist_artifact" in artifact_source
    assert "def _resolve_run_inputs(" in io_source
    assert "def _build_run_outputs(" in io_source
    assert "from .storage import fetch_upload" in io_source


def test_database_routes_delegate_request_dumping_to_services() -> None:
    route_source = _source("apps/remote_runner/database_routes.py")
    service_source = _source("apps/remote_runner/database_service.py")
    registry_source = _source("apps/remote_runner/databases.py")

    assert "from starlette.concurrency import run_in_threadpool" not in route_source
    assert "from .route_utils import" not in route_source
    assert "from .databases import" not in route_source
    assert "payload.model_dump(exclude_none=True)" not in route_source
    assert "list_databases_from_request" in route_source
    assert "list_database_templates_from_request" in route_source
    assert "add_database_from_request" in route_source
    assert "delete_database_from_request" in route_source
    assert "update_database_from_request" in route_source
    assert "check_database_from_request" in route_source

    assert "def list_databases_from_request(" in service_source
    assert "def list_database_templates_from_request(" in service_source
    assert "def add_database_from_request(" in service_source
    assert "def delete_database_from_request(" in service_source
    assert "def update_database_from_request(" in service_source
    assert "def check_database_from_request(" in service_source
    assert "from .route_utils import authorized_config, data_response, request_payload, run_sync" in service_source
    assert "from starlette.concurrency import run_in_threadpool" not in service_source
    assert "run_in_threadpool(" not in service_source
    assert "await run_sync(" in service_source
    assert "payload.model_dump(exclude_none=True)" not in service_source
    assert "request_payload(payload)" in service_source
    assert "DatabaseManifestRequest" not in registry_source
    assert "DatabaseUpdateRequest" not in registry_source
    assert "def add_verified_reference_database_from_request(" not in registry_source
    assert "def update_reference_database_from_request(" not in registry_source
