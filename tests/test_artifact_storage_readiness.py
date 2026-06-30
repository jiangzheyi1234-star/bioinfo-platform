from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from apps.remote_runner import artifact_storage_readiness
from apps.remote_runner import control_service, route_utils
from apps.remote_runner.artifact_storage_readiness import (
    build_artifact_storage_readiness,
    run_artifact_storage_readiness_smoke,
)
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from tests.helpers.reference_database import make_configured_remote_runner


class FakeS3Object(io.BytesIO):
    def release_conn(self) -> None:
        return None


class FakeS3Stat:
    def __init__(self, size: int) -> None:
        self.size = size
        self.metadata = {}


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.removed: list[tuple[str, str]] = []

    def bucket_exists(self, bucket: str) -> bool:
        return bucket == "h2ometa-artifacts"

    def fput_object(
        self,
        bucket: str,
        object_name: str,
        file_path: str,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> object:
        self.objects[(bucket, object_name)] = Path(file_path).read_bytes()
        return object()

    def stat_object(self, bucket: str, object_name: str) -> FakeS3Stat:
        return FakeS3Stat(len(self.objects[(bucket, object_name)]))

    def get_object(self, bucket: str, object_name: str) -> FakeS3Object:
        return FakeS3Object(self.objects[(bucket, object_name)])

    def remove_object(self, bucket: str, object_name: str) -> None:
        self.removed.append((bucket, object_name))
        self.objects.pop((bucket, object_name), None)


def test_local_artifact_storage_readiness_reports_safe_probe_without_paths(tmp_path) -> None:
    cfg = make_configured_remote_runner(tmp_path)

    readiness = build_artifact_storage_readiness(cfg)

    assert readiness["schemaVersion"] == "artifact-storage-readiness.v1"
    assert readiness["backend"] == "local"
    assert readiness["status"] == "ready"
    assert readiness["local"] == {
        "rootCount": 2,
        "writableRootCount": 2,
        "smokeRequested": False,
        "smokeRootCount": 0,
    }
    assert {check["rootKind"] for check in readiness["checks"]} == {"results", "work"}
    assert readiness["redactionPolicy"] == {
        "endpointExposed": False,
        "bucketExposed": False,
        "objectKeyExposed": False,
        "credentialsExposed": False,
        "localPathsExposed": False,
    }
    serialized = str(readiness)
    assert str(tmp_path) not in serialized


def test_s3_artifact_storage_readiness_passive_checks_bucket_without_writing(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_storage_readiness._build_s3_client", lambda _cfg: fake)
    cfg = make_configured_remote_runner(tmp_path)
    cfg.artifact_storage_backend = "s3"
    cfg.artifact_s3_endpoint = "minio.internal:9000"
    cfg.artifact_s3_bucket = "h2ometa-artifacts"
    cfg.artifact_s3_access_key = "access-secret-value"
    cfg.artifact_s3_secret_key = "s3-secret-value"
    cfg.artifact_s3_prefix = "tenant-a"
    cfg.artifact_s3_secure = True

    readiness = build_artifact_storage_readiness(cfg)

    assert readiness["backend"] == "s3"
    assert readiness["status"] == "ready"
    assert readiness["s3"]["smokeRequested"] is False
    assert any(check["name"] == "s3-bucket-access" and check["status"] == "passed" for check in readiness["checks"])
    assert fake.objects == {}


def test_s3_artifact_storage_readiness_smoke_redacts_storage_secrets(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_storage_readiness._build_s3_client", lambda _cfg: fake)
    cfg = make_configured_remote_runner(tmp_path)
    cfg.artifact_storage_backend = "s3"
    cfg.artifact_s3_endpoint = "minio.internal:9000"
    cfg.artifact_s3_bucket = "h2ometa-artifacts"
    cfg.artifact_s3_access_key = "access-secret-value"
    cfg.artifact_s3_secret_key = "s3-secret-value"
    cfg.artifact_s3_prefix = "tenant-a"
    cfg.artifact_s3_secure = True

    readiness = run_artifact_storage_readiness_smoke(cfg)

    assert readiness["backend"] == "s3"
    assert readiness["status"] == "ready"
    assert readiness["s3"]["endpointConfigured"] is True
    assert readiness["s3"]["bucketConfigured"] is True
    assert readiness["s3"]["accessKeyConfigured"] is True
    assert readiness["s3"]["secretKeyConfigured"] is True
    assert readiness["s3"]["smokeRequested"] is True
    assert any(check["name"] == "s3-write-read-delete-smoke" and check["status"] == "passed" for check in readiness["checks"])
    assert fake.objects == {}
    assert fake.removed
    serialized = str(readiness)
    for secret in (
        "minio.internal",
        "h2ometa-artifacts",
        "tenant-a/readiness",
        "access-secret-value",
        "s3-secret-value",
    ):
        assert secret not in serialized


def test_artifact_storage_readiness_route_requires_auditor_or_curator_before_read(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_readiness(*_args, **_kwargs):
        raise AssertionError("artifact storage readiness must not run before authorization")

    monkeypatch.setattr(control_service, "build_governed_artifact_storage_readiness", fail_readiness)

    response = TestClient(app).get(
        "/api/v1/artifacts/storage/readiness",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 403
    events = list_governance_audit_events(cfg, action="artifact.storage_readiness.read")["items"]
    assert events[-1]["decision"] == "deny"
    assert events[-1]["subjectKind"] == "artifact_storage_readiness"


def test_artifact_storage_readiness_route_records_safe_allow_audit(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(
        artifact_storage_readiness,
        "build_artifact_storage_readiness",
        lambda *_args, **_kwargs: {
            "schemaVersion": "artifact-storage-readiness.v1",
            "checkedAt": "2099-06-07T10:00:00Z",
            "backend": "s3",
            "status": "ready",
            "reasonCode": "",
            "checks": [],
            "s3": {
                "endpointConfigured": True,
                "bucketConfigured": True,
                "accessKeyConfigured": True,
                "secretKeyConfigured": True,
                "managedPrefixConfigured": True,
                "secureTransport": True,
                "smokeRequested": False,
                "endpoint": "minio.internal:9000",
            },
            "redactionPolicy": {"credentialsExposed": False},
        },
    )

    response = TestClient(app).get(
        "/api/v1/artifacts/storage/readiness",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["schemaVersion"] == "artifact-storage-readiness.v1"
    audit = list_governance_audit_events(cfg, action="artifact.storage_readiness.read")["items"]
    assert audit[-1]["decision"] == "allow"
    assert audit[-1]["details"] == {
        "backend": "s3",
        "status": "ready",
        "reasonCode": "",
        "smokeRequested": False,
    }
    assert "minio.internal" not in str(audit[-1])


def test_artifact_storage_smoke_route_requires_curator_before_probe(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_smoke(*_args, **_kwargs):
        raise AssertionError("artifact storage smoke must not run before authorization")

    monkeypatch.setattr(control_service, "run_governed_artifact_storage_readiness_smoke", fail_smoke)

    response = TestClient(app).post(
        "/api/v1/artifacts/storage/readiness/smoke",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 403
    events = list_governance_audit_events(cfg, action="artifact.storage_readiness.smoke")["items"]
    assert events[-1]["decision"] == "deny"
    assert events[-1]["subjectKind"] == "artifact_storage_readiness"


def test_artifact_storage_smoke_route_records_safe_allow_audit(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(
        artifact_storage_readiness,
        "run_artifact_storage_readiness_smoke",
        lambda *_args, **_kwargs: {
            "schemaVersion": "artifact-storage-readiness.v1",
            "checkedAt": "2099-06-07T10:00:00Z",
            "backend": "s3",
            "status": "ready",
            "reasonCode": "",
            "checks": [],
            "s3": {
                "endpointConfigured": True,
                "bucketConfigured": True,
                "accessKeyConfigured": True,
                "secretKeyConfigured": True,
                "managedPrefixConfigured": True,
                "secureTransport": True,
                "smokeRequested": True,
                "objectKey": "tenant-a/readiness/probe.txt",
            },
            "redactionPolicy": {"credentialsExposed": False},
        },
    )

    response = TestClient(app).post(
        "/api/v1/artifacts/storage/readiness/smoke",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 200
    audit = list_governance_audit_events(cfg, action="artifact.storage_readiness.smoke")["items"]
    assert audit[-1]["decision"] == "allow"
    assert audit[-1]["details"] == {
        "backend": "s3",
        "status": "ready",
        "reasonCode": "",
        "smokeRequested": True,
    }
    assert "tenant-a/readiness" not in str(audit[-1])
