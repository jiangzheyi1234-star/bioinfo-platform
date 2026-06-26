from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_result_package_file_io_lives_in_remote_service_not_routes() -> None:
    route_source = _source("apps/remote_runner/execution_query_routes.py")
    product_source = _source("apps/remote_runner/artifact_product_service.py")
    control_source = _source("apps/remote_runner/control_service.py")
    download_source = _source("apps/remote_runner/result_package_download_service.py")
    listing_source = _source("apps/remote_runner/result_package_listing_service.py")
    lifecycle_source = _source("apps/remote_runner/result_package_lifecycle_service.py")
    byte_gc_source = _source("apps/remote_runner/result_package_byte_gc_service.py")
    byte_gc_preview_source = _source("apps/remote_runner/result_package_byte_gc_preview_service.py")
    byte_gc_run_source = _source("apps/remote_runner/result_package_byte_gc_run_service.py")
    result_package_storage_source = _source("apps/remote_runner/result_package_storage.py")
    proxy_source = _source("core/remote_runner/proxy.py")
    result_package_proxy_source = _source("core/remote_runner/result_package_proxy.py")
    client_source = _source("core/remote_runner/client.py")
    manager_source = _source("core/remote_runner/manager.py")

    assert "zipfile" not in route_source
    assert "Path(" not in route_source
    assert "build_result_artifact_audit" not in route_source
    assert "from .artifact_product_service" not in route_source
    assert "export_result_package(" not in route_source
    assert "get_result_audit_from_request" in route_source
    assert "export_result_package_from_request" in route_source
    assert "list_result_package_exports_from_request" in route_source
    assert "download_result_package_from_request" in route_source
    assert "retire_result_package_from_request" in route_source
    assert "delete_result_package_bytes_from_request" in route_source
    assert "preview_result_package_byte_gc_from_request" in route_source
    assert '"/api/v1/result-package-exports/bytes/gc/preview"' in route_source
    assert "run_result_package_byte_gc_from_request" in route_source
    assert '"/api/v1/result-package-exports/bytes/gc/run"' in route_source
    assert "FileResponse(" in route_source

    assert "def build_result_artifact_audit(" in product_source
    assert "def export_result_package(" in product_source
    assert "zipfile.ZipFile(" in product_source
    assert "RESULT_ARTIFACT_AUDIT_FAILED" in product_source
    assert 'RESULT_PACKAGE_SCHEMA_VERSION = "h2ometa.result-package.v2"' in product_source
    assert 'RESULT_PACKAGE_PROFILE = "h2ometa.result-evidence-package.v1"' in product_source
    assert '"ro-crate-metadata.json"' in product_source
    assert "RESULT_WORKFLOW_REVISION_REQUIRED" in product_source
    assert "RESULT_ID_INVALID" in product_source
    assert "RESULT_EXPORT_EVENT_TYPE = \"result.export.v1\"" in product_source
    assert "ensure_result_package_export_recordable(" in product_source
    assert "def build_result_package_download(" in download_source
    assert "fetch_result_package_export(" in download_source
    assert "RESULT_PACKAGE_PATH_UNMANAGED" in download_source
    assert "RESULT_PACKAGE_SIZE_MISMATCH" in download_source
    assert "RESULT_PACKAGE_CHECKSUM_MISMATCH" in download_source
    assert "def list_result_package_exports(" in listing_source
    assert "list_result_package_export_records(" in listing_source
    assert "result_package_download_url(" in listing_source
    assert 'public.pop("packagePath", None)' in listing_source
    assert 'public.pop("packageUri", None)' in listing_source
    assert "def retire_result_package_export(" in lifecycle_source
    assert "build_result_package_download(" in lifecycle_source
    assert "mark_result_package_export_retired(" in lifecycle_source
    assert "RESULT_PACKAGE_RETIRE_CONFIRMATION_REQUIRED" in lifecycle_source
    assert "package_path.unlink" not in lifecycle_source
    assert "def delete_retired_result_package_bytes(" in byte_gc_source
    assert "fetch_result_package_export(" in byte_gc_source
    assert "mark_result_package_export_bytes_deleting(" in byte_gc_source
    assert "mark_result_package_export_bytes_deleted(" in byte_gc_source
    assert "RESULT_PACKAGE_BYTE_GC_CONFIRMATION_REQUIRED" in byte_gc_source
    assert "_reserve_package_file_for_deletion(" in byte_gc_source
    assert "_restore_reserved_package_file(" in byte_gc_source
    assert "_delete_reserved_package_file(" in byte_gc_source
    assert "package[\"path\"].unlink()" not in byte_gc_source
    assert "RESULT_PACKAGE_PATH_UNMANAGED" in byte_gc_source
    assert "RESULT_PACKAGE_CHECKSUM_MISMATCH" in byte_gc_source
    assert "def preview_result_package_byte_gc(" in byte_gc_preview_source
    assert "list_result_package_exports_for_byte_gc(" in byte_gc_preview_source
    assert "RESULT_PACKAGE_BYTE_GC_PREVIEW_SCHEMA" in byte_gc_preview_source
    assert "retired_time_missing" in byte_gc_preview_source
    assert "package_checksum_mismatch" in byte_gc_preview_source
    assert '"packageExportIdsExposed": False' in byte_gc_preview_source
    assert "def run_result_package_byte_gc(" in byte_gc_run_source
    assert "RESULT_PACKAGE_BYTE_GC_RUN_CONFIRMATION" in byte_gc_run_source
    assert "planFingerprint" in byte_gc_run_source
    assert "RESULT_PACKAGE_BYTE_GC_PLAN_FINGERPRINT_MISMATCH" in byte_gc_run_source
    assert "delete_retired_result_package_bytes(" in byte_gc_run_source
    assert "AND package_bytes_state = 'available'" in result_package_storage_source
    assert "AND package_bytes_state = 'deleting'" in result_package_storage_source
    assert "_raise_result_package_byte_state_conflict(" in result_package_storage_source
    assert "def list_result_package_exports_for_byte_gc(" in result_package_storage_source
    assert "retired_at" in result_package_storage_source
    assert "def _public_result_package_export(" in control_source
    assert 'package.get("lifecycleState") == "active"' in control_source
    assert 'package.get("packageBytesState") == "available"' in control_source
    assert 'public.pop("manifest", None)' in control_source
    assert "def preview_result_package_byte_gc_from_request(" in control_source
    assert 'action="result.package.bytes.preview"' in control_source
    assert "def run_result_package_byte_gc_from_request(" in control_source
    assert 'action="result.package.bytes.run"' in control_source
    assert "def _public_result_artifact_audit(" in control_source
    assert 'public.pop("storageUri", None)' in control_source

    assert "def get_result_audit(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def export_result_package(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def download_result_package(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert "def list_result_package_exports(self, **kwargs) -> dict[str, Any]:" in result_package_proxy_source
    assert "def retire_result_package(self, **kwargs) -> dict[str, Any]:" in result_package_proxy_source
    assert "def delete_result_package_bytes(self, **kwargs) -> dict[str, Any]:" in result_package_proxy_source
    assert "def preview_result_package_byte_gc(self, **kwargs) -> dict[str, Any]:" in result_package_proxy_source
    assert "def run_result_package_byte_gc(self, **kwargs) -> dict[str, Any]:" in result_package_proxy_source
    assert "RemoteRunnerResultPackageProxyMixin" in manager_source
    assert 'client.get_json(f"/api/v1/results/{kwargs[\'result_id\']}/audit")["data"]' in proxy_source
    assert "dict(kwargs.get(\"payload\") or {})" in proxy_source
    assert "client.list_result_package_exports(" in result_package_proxy_source
    assert "client.retire_result_package(" in result_package_proxy_source
    assert "client.delete_result_package_bytes(" in result_package_proxy_source
    assert "client.preview_result_package_byte_gc(" in result_package_proxy_source
    assert "client.run_result_package_byte_gc(" in result_package_proxy_source
    assert 'self.post_json(f"/api/v1/results/{result_id}/export", dict(payload or {}))["data"]' in client_source
    assert "def list_result_package_exports(" in client_source
    assert "def _request_bytes(" in client_source
    assert "def download_result_package(self, result_id: str, package_export_id: str)" in client_source
    assert "def retire_result_package(" in client_source
    assert "def delete_result_package_bytes(" in client_source
    assert "def preview_result_package_byte_gc(" in client_source
    assert "def run_result_package_byte_gc(" in client_source

    assert "def get_result_audit(self, result_id: str) -> dict[str, Any]:" in client_source
    assert "def export_result_package(" in client_source
    assert "payload: dict[str, Any] | None = None" in client_source
