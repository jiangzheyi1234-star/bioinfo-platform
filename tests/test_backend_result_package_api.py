from __future__ import annotations

import asyncio

from apps.api.models import (
    ResultPackageByteDeleteRequest,
    ResultPackageByteGcRunRequest,
    ResultPackageByteGcPreviewRequest,
    ResultPackageExportRequest,
    ResultPackageRetireRequest,
)
from apps.api.execution_query_routes import (
    delete_result_package_bytes,
    download_result_package,
    export_result_package,
    get_result_audit,
    list_result_package_exports,
    preview_result_package_byte_gc,
    run_result_package_byte_gc,
    retire_result_package,
)


def test_result_package_routes_preserve_runtime_wrappers(monkeypatch) -> None:
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: FakeResultPackageRuntime())

    audit = asyncio.run(get_result_audit("res_run_demo"))
    package = asyncio.run(
        export_result_package(
            "res_run_demo",
            ResultPackageExportRequest(includeArtifacts=False, actor="operator"),
        )
    )

    assert audit == {
        "data": {
            "resultId": "res_run_demo",
            "status": "passed",
            "artifacts": [
                {
                    "artifactId": "art_demo",
                    "storageBackend": "file",
                    "status": "passed",
                }
            ],
        }
    }
    assert package == {
        "data": {
            "resultId": "res_run_demo",
            "packageExportId": "rpex_demo",
            "lifecycleState": "active",
            "packageBytesState": "available",
            "includeArtifacts": False,
            "artifactPayloadMode": "metadata-only",
            "sha256": "a" * 64,
            "download": {
                "href": "/api/v1/results/res_run_demo/exports/rpex_demo/download",
                "filename": "rpex_demo.zip",
            },
        }
    }


def test_result_package_route_passes_server_id_outside_export_payload(monkeypatch) -> None:
    runtime = FakeResultPackageRuntimeWithServerId()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    package = asyncio.run(
        export_result_package(
            "res_run_demo",
            ResultPackageExportRequest(serverId="srv_remote", includeArtifacts=True, actor="operator"),
        )
    )

    assert runtime.calls == [
        (
            "res_run_demo",
            {"includeArtifacts": True, "actor": "operator"},
            "srv_remote",
        )
    ]
    assert package["data"]["packageExportId"] == "rpex_demo"


def test_result_package_download_route_streams_runtime_payload(monkeypatch) -> None:
    runtime = FakeResultPackageDownloadRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    response = asyncio.run(
        download_result_package(
            "res_run_demo",
            "rpex_demo",
            serverId="srv_remote",
        )
    )

    assert runtime.calls == [("res_run_demo", "rpex_demo", "srv_remote")]
    assert response.body == b"package-bytes"
    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="res_run_demo.zip"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-h2ometa-sha256"] == "b" * 64


def test_result_package_list_route_sanitizes_runtime_inventory(monkeypatch) -> None:
    runtime = FakeResultPackageListRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        list_result_package_exports(
            "res_run_demo",
            serverId="srv_remote",
            lifecycleState="retired",
            limit=25,
        )
    )

    assert runtime.calls == [("res_run_demo", "srv_remote", "retired", 25)]
    assert result == {
        "data": {
            "schemaVersion": "h2ometa.result-package-export-list.v1",
            "resultId": "res_run_demo",
            "items": [
                {
                    "resultId": "res_run_demo",
                    "packageExportId": "rpex_active",
                    "lifecycleState": "active",
                    "packageBytesState": "available",
                    "evidenceId": "ev_active",
                    "download": {
                        "href": "/api/v1/results/res_run_demo/exports/rpex_active/download",
                        "filename": "rpex_active.zip",
                    },
                },
                {
                    "resultId": "res_run_demo",
                    "packageExportId": "rpex_retired",
                    "lifecycleState": "retired",
                    "packageBytesState": "available",
                    "evidenceId": "ev_retired",
                },
                {
                    "resultId": "res_run_demo",
                    "packageExportId": "rpex_bytes_deleted",
                    "lifecycleState": "active",
                    "packageBytesState": "deleted",
                    "evidenceId": "ev_bytes_deleted",
                },
                {
                    "resultId": "res_run_demo",
                    "packageExportId": "rpex_missing_byte_state",
                    "lifecycleState": "active",
                    "evidenceId": "ev_missing_byte_state",
                },
            ],
        }
    }


def test_result_package_retire_route_passes_server_id_outside_payload(monkeypatch) -> None:
    runtime = FakeResultPackageRetireRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        retire_result_package(
            "res_run_demo",
            "rpex_demo",
            ResultPackageRetireRequest(
                serverId="srv_remote",
                confirmation="retire-result-package-export",
                actor="operator",
                reason="superseded",
            ),
        )
    )

    assert runtime.calls == [
        (
            "res_run_demo",
            "rpex_demo",
            {
                "confirmation": "retire-result-package-export",
                "actor": "operator",
                "reason": "superseded",
            },
            "srv_remote",
        )
    ]
    assert result == {
        "data": {
            "schemaVersion": "h2ometa.result-package-retire.v1",
            "resultId": "res_run_demo",
            "packageExportId": "rpex_demo",
            "lifecycleState": "retired",
        }
    }


def test_result_package_byte_delete_route_passes_server_id_outside_payload(monkeypatch) -> None:
    runtime = FakeResultPackageByteDeleteRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        delete_result_package_bytes(
            "res_run_demo",
            "rpex_demo",
            ResultPackageByteDeleteRequest(
                serverId="srv_remote",
                confirmation="delete-result-package-export-bytes",
                actor="operator",
                reason="quota",
            ),
        )
    )

    assert runtime.calls == [
        (
            "res_run_demo",
            "rpex_demo",
            {
                "confirmation": "delete-result-package-export-bytes",
                "actor": "operator",
                "reason": "quota",
            },
            "srv_remote",
        )
    ]
    assert result == {
        "data": {
            "schemaVersion": "h2ometa.result-package-bytes-delete.v1",
            "resultId": "res_run_demo",
            "packageExportId": "rpex_demo",
            "lifecycleState": "retired",
            "packageBytesState": "deleted",
        }
    }


def test_result_package_byte_gc_preview_route_passes_server_id_and_sanitizes_projection(monkeypatch) -> None:
    runtime = FakeResultPackageByteGcPreviewRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        preview_result_package_byte_gc(
            ResultPackageByteGcPreviewRequest(
                serverId="srv_remote",
                retentionDays=14,
                maxDeleteBytes=4096,
                scanLimit=50,
                actor="operator",
                reason="quota",
            )
        )
    )

    assert runtime.calls == [
        (
            {
                "retentionDays": 14,
                "maxDeleteBytes": 4096,
                "scanLimit": 50,
                "actor": "operator",
                "reason": "quota",
            },
            "srv_remote",
        )
    ]
    assert result == {
        "data": {
            "schemaVersion": "h2ometa.result-package-byte-gc-preview.v1",
            "candidateCount": 1,
            "protectedCount": 1,
            "candidates": [
                {
                    "itemIndex": 0,
                    "reason": "retired_bytes_eligible",
                    "nested": {},
                }
            ],
            "protected": [
                {
                    "itemIndex": 0,
                    "reason": "retired_time_missing",
                    "nested": {},
                }
            ],
            "redactionPolicy": {"pathsExposed": False, "sha256Exposed": False},
        }
    }


def test_result_package_byte_gc_run_route_passes_server_id_and_sanitizes_projection(monkeypatch) -> None:
    runtime = FakeResultPackageByteGcRunRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        run_result_package_byte_gc(
            ResultPackageByteGcRunRequest(
                serverId="srv_remote",
                retentionDays=14,
                maxDeleteBytes=4096,
                scanLimit=50,
                actor="operator",
                reason="quota",
                confirmation="run-result-package-byte-gc",
                planFingerprint="fp_current",
            )
        )
    )

    assert runtime.calls == [
        (
            {
                "retentionDays": 14,
                "maxDeleteBytes": 4096,
                "scanLimit": 50,
                "actor": "operator",
                "reason": "quota",
                "confirmation": "run-result-package-byte-gc",
                "planFingerprint": "fp_current",
            },
            "srv_remote",
        )
    ]
    assert result == {
        "data": {
            "schemaVersion": "h2ometa.result-package-byte-gc-run.v1",
            "status": "completed",
            "deletedCount": 1,
            "deleted": [{"itemIndex": 0, "nested": {}}],
            "plan": {"candidates": [{"itemIndex": 0}]},
        }
    }


class FakeResultPackageRuntime:
    def get_result_audit(self, result_id):
        assert result_id == "res_run_demo"
        return {
            "data": {
                "resultId": result_id,
                "status": "passed",
                "artifacts": [
                    {
                        "artifactId": "art_demo",
                        "path": "C:/secret/artifact.txt",
                        "storageBackend": "file",
                        "storageUri": "file:///C:/secret/artifact.txt",
                        "externalUri": "file:///C:/secret/artifact.txt",
                        "status": "passed",
                    }
                ],
            }
        }

    def export_result_package(self, result_id, *, payload, server_id=None):
        assert result_id == "res_run_demo"
        assert payload == {"includeArtifacts": False, "actor": "operator"}
        assert server_id is None
        return {
            "data": {
                "resultId": result_id,
                "includeArtifacts": False,
                "artifactPayloadMode": "metadata-only",
                "packageExportId": "rpex_demo",
                "lifecycleState": "active",
                "packageBytesState": "available",
                "packagePath": "C:/secret/rpex_demo.zip",
                "packageUri": "file:///C:/secret/rpex_demo.zip",
                "sha256": "a" * 64,
                "manifest": {
                    "artifacts": [
                        {
                            "storageUri": "file:///C:/secret/artifact.txt",
                            "externalUri": "file:///C:/secret/artifact.txt",
                        }
                    ]
                },
            }
        }


class FakeResultPackageRuntimeWithServerId:
    def __init__(self) -> None:
        self.calls = []

    def export_result_package(self, result_id, *, payload, server_id=None):
        self.calls.append((result_id, payload, server_id))
        return {
            "data": {
                "packageExportId": "rpex_demo",
                "resultId": result_id,
                "lifecycleState": "active",
                "packageBytesState": "available",
                "includeArtifacts": True,
                "artifactPayloadMode": "included",
            }
        }


class FakeResultPackageDownloadRuntime:
    def __init__(self) -> None:
        self.calls = []

    def download_result_package(self, result_id, package_export_id, server_id=None):
        self.calls.append((result_id, package_export_id, server_id))
        return {
            "content": b"package-bytes",
            "headers": {
                "content-disposition": 'attachment; filename="res_run_demo.zip"',
                "content-type": "application/zip",
                "x-content-type-options": "nosniff",
                "x-h2ometa-sha256": "b" * 64,
            },
        }


class FakeResultPackageListRuntime:
    def __init__(self) -> None:
        self.calls = []

    def list_result_package_exports(
        self,
        result_id,
        *,
        server_id=None,
        lifecycle_state=None,
        limit=100,
    ):
        self.calls.append((result_id, server_id, lifecycle_state, limit))
        return {
            "data": {
                "schemaVersion": "h2ometa.result-package-export-list.v1",
                "resultId": result_id,
                "items": [
                    {
                        "resultId": result_id,
                        "packageExportId": "rpex_active",
                        "lifecycleState": "active",
                        "packageBytesState": "available",
                        "evidenceEventId": "ev_active",
                        "manifest": {
                            "artifacts": [
                                {
                                    "storageUri": "file:///C:/secret/artifact.txt",
                                    "externalUri": "file:///C:/secret/artifact.txt",
                                }
                            ]
                        },
                        "packagePath": "C:/secret/rpex_active.zip",
                        "packageUri": "file:///C:/secret/rpex_active.zip",
                    },
                    {
                        "resultId": result_id,
                        "packageExportId": "rpex_retired",
                        "lifecycleState": "retired",
                        "packageBytesState": "available",
                        "evidenceEventId": "ev_retired",
                        "download": {
                            "href": "/api/v1/results/res_run_demo/exports/rpex_retired/download",
                            "filename": "rpex_retired.zip",
                        },
                        "packagePath": "C:/secret/retired.zip",
                        "packageUri": "file:///C:/secret/retired.zip",
                    },
                    {
                        "resultId": result_id,
                        "packageExportId": "rpex_bytes_deleted",
                        "lifecycleState": "active",
                        "packageBytesState": "deleted",
                        "evidenceEventId": "ev_bytes_deleted",
                        "download": {
                            "href": "/api/v1/results/res_run_demo/exports/rpex_bytes_deleted/download",
                            "filename": "rpex_bytes_deleted.zip",
                        },
                        "packagePath": "C:/secret/deleted.zip",
                        "packageUri": "file:///C:/secret/deleted.zip",
                    },
                    {
                        "resultId": result_id,
                        "packageExportId": "rpex_missing_byte_state",
                        "lifecycleState": "active",
                        "evidenceEventId": "ev_missing_byte_state",
                        "download": {
                            "href": "/api/v1/results/res_run_demo/exports/rpex_missing_byte_state/download",
                            "filename": "rpex_missing_byte_state.zip",
                        },
                        "packagePath": "C:/secret/missing-byte.zip",
                        "packageUri": "file:///C:/secret/missing-byte.zip",
                    },
                ],
            }
        }


class FakeResultPackageRetireRuntime:
    def __init__(self) -> None:
        self.calls = []

    def retire_result_package(self, result_id, package_export_id, *, payload, server_id=None):
        self.calls.append((result_id, package_export_id, payload, server_id))
        return {
            "data": {
                "schemaVersion": "h2ometa.result-package-retire.v1",
                "resultId": result_id,
                "packageExportId": package_export_id,
                "lifecycleState": "retired",
                "manifest": {"artifacts": [{"storageUri": "file:///C:/secret/artifact.txt"}]},
                "packagePath": "C:/secret/package.zip",
                "packageUri": "file:///C:/secret/package.zip",
            }
        }


class FakeResultPackageByteDeleteRuntime:
    def __init__(self) -> None:
        self.calls = []

    def delete_result_package_bytes(self, result_id, package_export_id, *, payload, server_id=None):
        self.calls.append((result_id, package_export_id, payload, server_id))
        return {
            "data": {
                "schemaVersion": "h2ometa.result-package-bytes-delete.v1",
                "resultId": result_id,
                "packageExportId": package_export_id,
                "lifecycleState": "retired",
                "packageBytesState": "deleted",
                "manifest": {"artifacts": [{"storageUri": "file:///C:/secret/artifact.txt"}]},
                "packagePath": "C:/secret/package.zip",
                "packageUri": "file:///C:/secret/package.zip",
            }
        }


class FakeResultPackageByteGcPreviewRuntime:
    def __init__(self) -> None:
        self.calls = []

    def preview_result_package_byte_gc(self, payload, *, server_id=None):
        self.calls.append((payload, server_id))
        return {
            "data": {
                "schemaVersion": "h2ometa.result-package-byte-gc-preview.v1",
                "candidateCount": 1,
                "protectedCount": 1,
                "resultId": "res_hidden",
                "runId": "run_hidden",
                "packageExportId": "rpex_hidden",
                "packagePath": "C:/secret/package.zip",
                "packageUri": "file:///C:/secret/package.zip",
                "sha256": "a" * 64,
                "candidates": [
                    {
                        "itemIndex": 0,
                        "reason": "retired_bytes_eligible",
                        "resultId": "res_hidden",
                        "runId": "run_hidden",
                        "packageExportId": "rpex_hidden",
                        "nested": {
                            "packagePath": "C:/secret/package.zip",
                            "packageUri": "file:///C:/secret/package.zip",
                            "sha256": "b" * 64,
                        },
                    }
                ],
                "protected": [
                    {
                        "itemIndex": 0,
                        "reason": "retired_time_missing",
                        "nested": {
                            "manifest": {"packageUri": "file:///C:/secret/package.zip"},
                            "manifestSha256": "c" * 64,
                        },
                    }
                ],
                "redactionPolicy": {"pathsExposed": False, "sha256Exposed": False},
            }
        }


class FakeResultPackageByteGcRunRuntime:
    def __init__(self) -> None:
        self.calls = []

    def run_result_package_byte_gc(self, payload, *, server_id=None):
        self.calls.append((payload, server_id))
        return {
            "data": {
                "schemaVersion": "h2ometa.result-package-byte-gc-run.v1",
                "status": "completed",
                "deletedCount": 1,
                "resultId": "res_hidden",
                "runId": "run_hidden",
                "packageExportId": "rpex_hidden",
                "packagePath": "C:/secret/package.zip",
                "packageUri": "file:///C:/secret/package.zip",
                "sha256": "a" * 64,
                "deleted": [
                    {
                        "itemIndex": 0,
                        "resultId": "res_hidden",
                        "runId": "run_hidden",
                        "packageExportId": "rpex_hidden",
                        "nested": {
                            "packagePath": "C:/secret/package.zip",
                            "storageUri": "file:///C:/secret/package.zip",
                            "packageSha256": "b" * 64,
                        },
                    }
                ],
                "plan": {
                    "candidates": [
                        {
                            "itemIndex": 0,
                            "packageExportId": "rpex_hidden",
                            "resultId": "res_hidden",
                        }
                    ]
                },
            }
        }
