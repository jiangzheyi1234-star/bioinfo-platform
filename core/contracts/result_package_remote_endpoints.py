from __future__ import annotations

from typing import Any


RESULT_PACKAGE_EXPORT_LIST = "result.package_export.list"
RESULT_PACKAGE_EXPORT = "result.package.export"
RESULT_PACKAGE_DOWNLOAD = "result.package.download"
RESULT_PACKAGE_RETIRE = "result.package.retire"
RESULT_PACKAGE_BYTE_GC_PREVIEW = "result.package.byte_gc.preview"
RESULT_PACKAGE_BYTE_GC_RUN = "result.package.byte_gc.run"


RESULT_PACKAGE_REMOTE_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    RESULT_PACKAGE_EXPORT_LIST: {
        "method": "GET",
        "path_template": "/api/v1/results/{result_id}/exports",
        "operation_id": "listResultPackageExports",
        "governance_action": "result.package.list",
        "request_schema": None,
        "response_schema": "result-package-export-list.v1",
        "cache_scope": "result-package-export-read-model",
        "query_params": ("lifecycleState", "limit"),
    },
    RESULT_PACKAGE_EXPORT: {
        "method": "POST",
        "path_template": "/api/v1/results/{result_id}/export",
        "operation_id": "exportResultPackage",
        "governance_action": "result.export",
        "request_schema": "result-package-export-request.v1",
        "response_schema": "h2ometa.result-package.v2",
        "cache_scope": "result-package-export-command",
        "invalidates": ("result-package-export-read-model",),
    },
    RESULT_PACKAGE_DOWNLOAD: {
        "method": "GET",
        "path_template": "/api/v1/results/{result_id}/exports/{package_export_id}/download",
        "operation_id": "downloadResultPackage",
        "governance_action": "result.package.download",
        "request_schema": None,
        "response_schema": "h2ometa.result-package-download.v1",
        "cache_scope": "result-package-download",
    },
    RESULT_PACKAGE_RETIRE: {
        "method": "POST",
        "path_template": "/api/v1/results/{result_id}/exports/{package_export_id}/retire",
        "operation_id": "retireResultPackage",
        "governance_action": "result.package.retire",
        "request_schema": "result-package-retire-request.v1",
        "response_schema": "h2ometa.result-package-retire.v1",
        "cache_scope": "result-package-export-command",
        "invalidates": ("result-package-export-read-model", "artifact-lifecycle-read-model"),
    },
    RESULT_PACKAGE_BYTE_GC_PREVIEW: {
        "method": "POST",
        "path_template": "/api/v1/result-package-exports/bytes/gc/preview",
        "operation_id": "previewResultPackageByteGc",
        "governance_action": "result.package.bytes.preview",
        "request_schema": "result-package-byte-gc-preview-request.v1",
        "response_schema": "h2ometa.result-package-byte-gc-preview.v1",
        "cache_scope": "result-package-byte-gc-command",
    },
    RESULT_PACKAGE_BYTE_GC_RUN: {
        "method": "POST",
        "path_template": "/api/v1/result-package-exports/bytes/gc/run",
        "operation_id": "runResultPackageByteGc",
        "governance_action": "result.package.bytes.run",
        "request_schema": "result-package-byte-gc-run-request.v1",
        "response_schema": "h2ometa.result-package-byte-gc-run.v1",
        "cache_scope": "result-package-byte-gc-command",
        "invalidates": ("result-package-export-read-model", "artifact-lifecycle-read-model"),
    },
}
