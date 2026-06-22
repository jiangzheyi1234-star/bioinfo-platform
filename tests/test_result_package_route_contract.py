from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_result_package_file_io_lives_in_remote_service_not_routes() -> None:
    route_source = _source("apps/remote_runner/execution_query_routes.py")
    product_source = _source("apps/remote_runner/artifact_product_service.py")
    proxy_source = _source("core/remote_runner/proxy.py")
    client_source = _source("core/remote_runner/client.py")

    assert "zipfile" not in route_source
    assert "Path(" not in route_source
    assert "build_result_artifact_audit" not in route_source
    assert "from .artifact_product_service" not in route_source
    assert "export_result_package(" not in route_source
    assert "get_result_audit_from_request" in route_source
    assert "export_result_package_from_request" in route_source

    assert "def build_result_artifact_audit(" in product_source
    assert "def export_result_package(" in product_source
    assert "zipfile.ZipFile(" in product_source
    assert "RESULT_ARTIFACT_AUDIT_FAILED" in product_source

    assert "def get_result_audit(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def export_result_package(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.get_json(f"/api/v1/results/{kwargs[\'result_id\']}/audit")["data"]' in proxy_source
    assert 'client.post_json(f"/api/v1/results/{kwargs[\'result_id\']}/export", {})["data"]' in proxy_source

    assert "def get_result_audit(self, result_id: str) -> dict[str, Any]:" in client_source
    assert "def export_result_package(self, result_id: str) -> dict[str, Any]:" in client_source
