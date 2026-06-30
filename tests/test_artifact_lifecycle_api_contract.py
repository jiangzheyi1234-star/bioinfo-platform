from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_artifact_lifecycle_gc_is_exposed_through_remote_local_and_runtime_layers() -> None:
    endpoint_contracts = _read("core/contracts/remote_endpoints.py")
    remote_routes = _read("apps/remote_runner/execution_query_routes.py")
    remote_service = _read("apps/remote_runner/control_service.py")
    remote_controller_control = _read("apps/remote_runner/artifact_lifecycle_controller_control.py")
    remote_controller_control_api = _read("apps/remote_runner/artifact_lifecycle_controller_control_route_service.py")
    remote_controller_read_api = _read("apps/remote_runner/artifact_lifecycle_controller_read_api.py")
    remote_controller_read_model = _read("apps/remote_runner/artifact_lifecycle_controller_read_model.py")
    local_routes = _read("apps/api/execution_query_routes.py")
    local_service = _read("apps/api/execution_query_service.py")
    remote_models = _read("apps/remote_runner/api_models.py")
    local_models = _read("apps/api/models.py")
    lifecycle_model = _read("apps/web/app/components/workflow-artifact-lifecycle-model.ts")
    execution_manager = _read("core/app_runtime/managers/execution.py")
    runner_ops = _read("core/app_runtime/runner_execution_ops.py")
    proxy = _read("core/remote_runner/proxy.py")
    client = _read("core/remote_runner/client.py")
    manager = _read("core/remote_runner/manager.py")

    assert '"/api/v1/artifacts/lifecycle/usage"' in remote_routes
    assert '"/api/v1/artifacts/lifecycle/controller/ticks"' in remote_routes
    assert '"/api/v1/artifacts/lifecycle/controller/run-once"' in remote_routes
    assert '"/api/v1/artifacts/lifecycle/gc/preview"' in remote_routes
    assert '"/api/v1/artifacts/lifecycle/gc/run"' in remote_routes
    assert '"/api/v1/artifacts/cache/entries"' in remote_routes
    assert '"/api/v1/artifacts/cache/pins"' in remote_routes
    assert '"/api/v1/artifacts/cache/entries/{cache_entry_id}/retain"' in remote_routes
    assert '"/api/v1/artifacts/cache/pins/{cache_pin_id}/release"' in remote_routes
    assert '"/api/v1/artifacts/cache/lookup"' in remote_routes
    assert '"/api/v1/artifacts/storage/readiness"' in remote_routes
    assert '"/api/v1/artifacts/storage/readiness/smoke"' in remote_routes
    assert "list_artifact_lifecycle_controller_ticks_from_request" in remote_controller_read_api
    assert 'action="artifact.lifecycle.controller_ticks.read"' in remote_controller_read_api
    assert "run_artifact_lifecycle_controller_once_request" in remote_controller_control_api
    assert 'action="artifact.lifecycle.controller.run_once"' in remote_controller_control_api
    assert "run_governed_artifact_lifecycle_controller_once" in remote_controller_control
    assert "ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE_CONFIRMATION" in remote_controller_control
    assert "deleteExecutionAuthorized" in remote_controller_control
    assert "controlsExposed" in remote_controller_control
    assert "ARTIFACT_LIFECYCLE_CONTROLLER_TICK_PLAN_ID_REQUIRED" in remote_controller_control
    assert "ARTIFACT_LIFECYCLE_CONTROLLER_TICK_PLAN_FINGERPRINT_REQUIRED" in remote_controller_control
    assert "ARTIFACT_LIFECYCLE_CONTROLLER_TICK_PLAN_ID_REQUIRED" in remote_controller_read_model
    assert "ARTIFACT_LIFECYCLE_CONTROLLER_TICK_PLAN_FINGERPRINT_REQUIRED" in remote_controller_read_model
    assert "get_artifact_lifecycle_usage_from_request" in remote_service
    assert 'action="artifact.lifecycle.usage.read"' in remote_service
    assert "build_governed_artifact_lifecycle_usage" in remote_service
    assert "preview_artifact_gc_from_request" in remote_service
    assert "run_artifact_gc_from_request" in remote_service
    assert "public_artifact_gc_plan" in remote_service
    assert "public_artifact_gc_run_result" in remote_service
    assert "list_artifact_cache_entries_from_request" in remote_service
    assert "list_artifact_cache_pins_from_request" in remote_service
    assert "retain_artifact_cache_pin_from_request" in remote_service
    assert "release_artifact_cache_pin_from_request" in remote_service
    assert "lookup_artifact_cache_from_request" in remote_service
    assert "public_artifact_cache_record(pin)" in remote_service
    assert "artifact_storage_readiness_from_request" in remote_service
    assert "artifact_storage_readiness_smoke_from_request" in remote_service
    assert "build_governed_artifact_storage_readiness" in remote_service
    assert "run_governed_artifact_storage_readiness_smoke" in remote_service
    assert 'action="artifact.storage_readiness.read"' in remote_service
    assert 'action="artifact.storage_readiness.smoke"' in remote_service
    assert "planFingerprint" in remote_models
    assert "planFingerprint" in local_models
    assert "planFingerprint" in lifecycle_model

    assert '"/api/v1/artifacts/lifecycle/usage"' in local_routes
    assert '"/api/v1/artifacts/lifecycle/controller/ticks"' in local_routes
    assert '"/api/v1/artifacts/lifecycle/controller/run-once"' in local_routes
    assert '"/api/v1/artifacts/lifecycle/gc/preview"' in local_routes
    assert '"/api/v1/artifacts/lifecycle/gc/run"' in local_routes
    assert '"/api/v1/artifacts/cache/entries"' in local_routes
    assert '"/api/v1/artifacts/cache/pins"' in local_routes
    assert '"/api/v1/artifacts/cache/entries/{cache_entry_id}/retain"' in local_routes
    assert '"/api/v1/artifacts/cache/pins/{cache_pin_id}/release"' in local_routes
    assert '"/api/v1/artifacts/cache/lookup"' in local_routes
    assert '"/api/v1/artifacts/storage/readiness"' in local_routes
    assert '"/api/v1/artifacts/storage/readiness/smoke"' in local_routes
    assert "runtime_service().get_artifact_lifecycle_usage" in local_service
    assert "runtime_service().list_artifact_lifecycle_controller_ticks" in local_service
    assert "runtime_service().run_artifact_lifecycle_controller_once" in local_service
    assert "runtime_service().preview_artifact_gc" in local_service
    assert "runtime_service().run_artifact_gc" in local_service
    assert "runtime_service().list_artifact_cache_entries" in local_service
    assert "runtime_service().list_artifact_cache_pins" in local_service
    assert "runtime_service().retain_artifact_cache_pin" in local_service
    assert "runtime_service().release_artifact_cache_pin" in local_service
    assert "runtime_service().lookup_artifact_cache" in local_service
    assert "runtime_service().get_artifact_storage_readiness" in local_service
    assert "runtime_service().run_artifact_storage_readiness_smoke" in local_service

    assert "def get_artifact_lifecycle_usage" in execution_manager
    assert "def list_artifact_lifecycle_controller_ticks" in execution_manager
    assert "def run_artifact_lifecycle_controller_once" in execution_manager
    assert "def preview_artifact_gc" in execution_manager
    assert "def run_artifact_gc" in execution_manager
    assert "def list_artifact_cache_entries" in execution_manager
    assert "def list_artifact_cache_pins" in execution_manager
    assert "def retain_artifact_cache_pin" in execution_manager
    assert "def release_artifact_cache_pin" in execution_manager
    assert "def lookup_artifact_cache" in execution_manager
    assert "def get_artifact_storage_readiness" in execution_manager
    assert "def run_artifact_storage_readiness_smoke" in execution_manager
    assert "def get_artifact_lifecycle_usage" in runner_ops
    assert "def list_artifact_lifecycle_controller_ticks" in runner_ops
    assert "def run_artifact_lifecycle_controller_once" in runner_ops
    assert "def preview_artifact_gc" in runner_ops
    assert "def run_artifact_gc" in runner_ops
    assert "def list_artifact_cache_entries" in runner_ops
    assert "def list_artifact_cache_pins" in runner_ops
    assert "def retain_artifact_cache_pin" in runner_ops
    assert "def release_artifact_cache_pin" in runner_ops
    assert "def lookup_artifact_cache" in runner_ops
    assert "def get_artifact_storage_readiness" in runner_ops
    assert "def run_artifact_storage_readiness_smoke" in runner_ops
    assert "ARTIFACT_LIFECYCLE_USAGE_READ" in execution_manager
    assert "ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ" in execution_manager
    assert "ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE" in execution_manager
    assert "ARTIFACT_LIFECYCLE_GC_PREVIEW" in execution_manager
    assert "ARTIFACT_LIFECYCLE_GC_RUN" in execution_manager
    assert "ARTIFACT_CACHE_ENTRIES_READ" in execution_manager
    assert "ARTIFACT_CACHE_PINS_READ" in execution_manager
    assert "ARTIFACT_CACHE_PIN_RETAIN" in execution_manager
    assert "ARTIFACT_CACHE_PIN_RELEASE" in execution_manager
    assert "ARTIFACT_CACHE_LOOKUP" in execution_manager
    assert "ARTIFACT_STORAGE_READINESS_READ" in execution_manager
    assert "ARTIFACT_STORAGE_READINESS_SMOKE_RUN" in execution_manager
    assert "/api/v1/artifacts/lifecycle/usage" not in proxy
    assert "RemoteRunnerArtifactLifecycleProxyMixin" not in manager
    assert "artifact_lifecycle_proxy" not in manager
    assert "/api/v1/artifacts/lifecycle/controller/run-once" not in proxy
    assert "/api/v1/artifacts/lifecycle/controller/ticks" not in proxy
    assert "/api/v1/artifacts/lifecycle/gc/preview" not in proxy
    assert "/api/v1/artifacts/lifecycle/gc/run" not in proxy
    assert "/api/v1/artifacts/cache/entries?" not in proxy
    assert "/api/v1/artifacts/cache/pins?" not in proxy
    assert "/api/v1/artifacts/cache/entries/" not in proxy
    assert "/api/v1/artifacts/cache/pins/" not in proxy
    assert "/api/v1/artifacts/cache/lookup" not in proxy
    assert "/api/v1/artifacts/storage/readiness" not in proxy
    assert "/api/v1/artifacts/storage/readiness/smoke" not in proxy
    assert "/api/v1/artifacts/lifecycle/usage" not in client
    assert "/api/v1/artifacts/lifecycle/controller/ticks" not in client
    assert "/api/v1/artifacts/lifecycle/controller/run-once" not in client
    assert "/api/v1/artifacts/lifecycle/gc/preview" not in client
    assert "/api/v1/artifacts/lifecycle/gc/run" not in client
    assert "/api/v1/artifacts/cache/entries?" not in client
    assert "/api/v1/artifacts/cache/pins?" not in client
    assert "/api/v1/artifacts/cache/entries/" not in client
    assert "/api/v1/artifacts/cache/pins/" not in client
    assert "/api/v1/artifacts/cache/lookup" not in client
    assert "/api/v1/artifacts/storage/readiness" not in client
    assert "/api/v1/artifacts/storage/readiness/smoke" not in client
    assert 'path_template="/api/v1/artifacts/lifecycle/controller/run-once"' in endpoint_contracts
    assert 'path_template="/api/v1/artifacts/lifecycle/gc/preview"' in endpoint_contracts
    assert 'path_template="/api/v1/artifacts/lifecycle/gc/run"' in endpoint_contracts
    assert 'path_template="/api/v1/artifacts/cache/entries/{cache_entry_id}/retain"' in endpoint_contracts
    assert 'path_template="/api/v1/artifacts/cache/pins/{cache_pin_id}/release"' in endpoint_contracts
    assert 'path_template="/api/v1/artifacts/cache/lookup"' in endpoint_contracts
    assert 'path_template="/api/v1/artifacts/storage/readiness"' in endpoint_contracts
    assert 'path_template="/api/v1/artifacts/storage/readiness/smoke"' in endpoint_contracts
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE].operation_id" in remote_routes
    assert "remote_endpoint_success_status(ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE)" in remote_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_LIFECYCLE_GC_PREVIEW].operation_id" in remote_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_LIFECYCLE_GC_RUN].operation_id" in remote_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_PIN_RETAIN].operation_id" in remote_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_PIN_RELEASE].operation_id" in remote_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_LOOKUP].operation_id" in remote_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_STORAGE_READINESS_READ].operation_id" in remote_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_STORAGE_READINESS_SMOKE_RUN].operation_id" in remote_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE].operation_id" in local_routes
    assert "remote_endpoint_success_status(ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE)" in local_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_LIFECYCLE_GC_PREVIEW].operation_id" in local_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_LIFECYCLE_GC_RUN].operation_id" in local_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_PIN_RETAIN].operation_id" in local_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_PIN_RELEASE].operation_id" in local_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_CACHE_LOOKUP].operation_id" in local_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_STORAGE_READINESS_READ].operation_id" in local_routes
    assert "operation_id=REMOTE_ENDPOINTS[ARTIFACT_STORAGE_READINESS_SMOKE_RUN].operation_id" in local_routes


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")
