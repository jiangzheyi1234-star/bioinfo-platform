from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_artifact_lifecycle_gc_is_exposed_through_remote_local_and_runtime_layers() -> None:
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
    artifact_lifecycle_proxy = _read("core/remote_runner/artifact_lifecycle_proxy.py")
    client = _read("core/remote_runner/client.py")
    manager = _read("core/remote_runner/manager.py")

    assert '@router.get("/api/v1/artifacts/lifecycle/usage")' in remote_routes
    assert '@router.get("/api/v1/artifacts/lifecycle/controller/ticks")' in remote_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/controller/run-once", status_code=202)' in remote_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/gc/preview")' in remote_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/gc/run")' in remote_routes
    assert '@router.get("/api/v1/artifacts/cache/entries")' in remote_routes
    assert '@router.get("/api/v1/artifacts/cache/pins")' in remote_routes
    assert '@router.post("/api/v1/artifacts/cache/entries/{cache_entry_id}/retain")' in remote_routes
    assert '@router.post("/api/v1/artifacts/cache/pins/{cache_pin_id}/release")' in remote_routes
    assert '@router.post("/api/v1/artifacts/cache/lookup")' in remote_routes
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
    assert "planFingerprint" in remote_models
    assert "planFingerprint" in local_models
    assert "planFingerprint" in lifecycle_model

    assert '@router.get("/api/v1/artifacts/lifecycle/usage")' in local_routes
    assert '@router.get("/api/v1/artifacts/lifecycle/controller/ticks")' in local_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/controller/run-once", status_code=202)' in local_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/gc/preview")' in local_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/gc/run")' in local_routes
    assert '@router.get("/api/v1/artifacts/cache/entries")' in local_routes
    assert '@router.get("/api/v1/artifacts/cache/pins")' in local_routes
    assert '@router.post("/api/v1/artifacts/cache/entries/{cache_entry_id}/retain")' in local_routes
    assert '@router.post("/api/v1/artifacts/cache/pins/{cache_pin_id}/release")' in local_routes
    assert '@router.post("/api/v1/artifacts/cache/lookup")' in local_routes
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
    assert "/api/v1/artifacts/lifecycle/usage" in proxy
    assert "RemoteRunnerArtifactLifecycleProxyMixin" in manager
    assert "/api/v1/artifacts/lifecycle/controller/ticks" in artifact_lifecycle_proxy
    assert "/api/v1/artifacts/lifecycle/controller/run-once" in artifact_lifecycle_proxy
    assert "/api/v1/artifacts/lifecycle/gc/preview" in proxy
    assert "/api/v1/artifacts/lifecycle/gc/run" in proxy
    assert "/api/v1/artifacts/cache/entries" in proxy
    assert "/api/v1/artifacts/cache/pins" in proxy
    assert "/api/v1/artifacts/cache/entries/" in proxy and "/retain" in proxy
    assert "/api/v1/artifacts/cache/pins/" in proxy and "/release" in proxy
    assert "/api/v1/artifacts/cache/lookup" in proxy
    assert "/api/v1/artifacts/lifecycle/usage" in client
    assert "/api/v1/artifacts/lifecycle/controller/ticks" in client
    assert "/api/v1/artifacts/lifecycle/controller/run-once" in client
    assert "/api/v1/artifacts/lifecycle/gc/preview" in client
    assert "/api/v1/artifacts/lifecycle/gc/run" in client
    assert "/api/v1/artifacts/cache/entries" in client
    assert "/api/v1/artifacts/cache/pins" in client
    assert "/api/v1/artifacts/cache/entries/{entry_part}/retain" in client
    assert "/api/v1/artifacts/cache/pins/{pin_part}/release" in client
    assert "/api/v1/artifacts/cache/lookup" in client


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")
