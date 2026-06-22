from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_artifact_lifecycle_gc_is_exposed_through_remote_local_and_runtime_layers() -> None:
    remote_routes = _read("apps/remote_runner/execution_query_routes.py")
    remote_service = _read("apps/remote_runner/control_service.py")
    local_routes = _read("apps/api/execution_query_routes.py")
    local_service = _read("apps/api/execution_query_service.py")
    execution_manager = _read("core/app_runtime/managers/execution.py")
    runner_ops = _read("core/app_runtime/runner_execution_ops.py")
    proxy = _read("core/remote_runner/proxy.py")
    client = _read("core/remote_runner/client.py")

    assert '@router.get("/api/v1/artifacts/lifecycle/usage")' in remote_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/gc/preview")' in remote_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/gc/run")' in remote_routes
    assert '@router.get("/api/v1/artifacts/cache/entries")' in remote_routes
    assert '@router.post("/api/v1/artifacts/cache/lookup")' in remote_routes
    assert "get_artifact_lifecycle_usage_from_request" in remote_service
    assert "preview_artifact_gc_from_request" in remote_service
    assert "run_artifact_gc_from_request" in remote_service
    assert "list_artifact_cache_entries_from_request" in remote_service
    assert "lookup_artifact_cache_from_request" in remote_service

    assert '@router.get("/api/v1/artifacts/lifecycle/usage")' in local_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/gc/preview")' in local_routes
    assert '@router.post("/api/v1/artifacts/lifecycle/gc/run")' in local_routes
    assert '@router.get("/api/v1/artifacts/cache/entries")' in local_routes
    assert '@router.post("/api/v1/artifacts/cache/lookup")' in local_routes
    assert "runtime_service().get_artifact_lifecycle_usage" in local_service
    assert "runtime_service().preview_artifact_gc" in local_service
    assert "runtime_service().run_artifact_gc" in local_service
    assert "runtime_service().list_artifact_cache_entries" in local_service
    assert "runtime_service().lookup_artifact_cache" in local_service

    assert "def get_artifact_lifecycle_usage" in execution_manager
    assert "def preview_artifact_gc" in execution_manager
    assert "def run_artifact_gc" in execution_manager
    assert "def list_artifact_cache_entries" in execution_manager
    assert "def lookup_artifact_cache" in execution_manager
    assert "def get_artifact_lifecycle_usage" in runner_ops
    assert "def preview_artifact_gc" in runner_ops
    assert "def run_artifact_gc" in runner_ops
    assert "def list_artifact_cache_entries" in runner_ops
    assert "def lookup_artifact_cache" in runner_ops
    assert "/api/v1/artifacts/lifecycle/usage" in proxy
    assert "/api/v1/artifacts/lifecycle/gc/preview" in proxy
    assert "/api/v1/artifacts/lifecycle/gc/run" in proxy
    assert "/api/v1/artifacts/cache/entries" in proxy
    assert "/api/v1/artifacts/cache/lookup" in proxy
    assert "/api/v1/artifacts/lifecycle/usage" in client
    assert "/api/v1/artifacts/lifecycle/gc/preview" in client
    assert "/api/v1/artifacts/lifecycle/gc/run" in client
    assert "/api/v1/artifacts/cache/entries" in client
    assert "/api/v1/artifacts/cache/lookup" in client


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")
