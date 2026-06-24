from __future__ import annotations

import asyncio

from apps.api.models import (
    ResultPackageByteDeleteRequest,
    ResultPackageExportRequest,
    ResultPackageRetireRequest,
)
from apps.api.execution_query_routes import (
    delete_result_package_bytes,
    download_result_package,
    export_result_package,
    get_result_audit,
    list_result_package_exports,
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
                    "evidenceId": "ev_retired",
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
                        "evidenceEventId": "ev_retired",
                        "download": {
                            "href": "/api/v1/results/res_run_demo/exports/rpex_retired/download",
                            "filename": "rpex_retired.zip",
                        },
                        "packagePath": "C:/secret/retired.zip",
                        "packageUri": "file:///C:/secret/retired.zip",
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
