from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner.artifact_cache_storage import lookup_artifact_cache_entry
from apps.remote_runner.artifact_cache_adoption import try_adopt_cached_outputs
from apps.remote_runner.artifact_ledger_storage import list_artifact_materializations
from apps.remote_runner.artifact_io import artifact_payload_stats
from apps.remote_runner.artifact_product_service import build_result_artifact_audit, export_result_package
from apps.remote_runner.candidate_output_storage import (
    adopt_verified_candidate_outputs,
    record_candidate_output,
    verify_candidate_outputs,
)
from apps.remote_runner.config import (
    RemoteRunnerConfig,
    apply_artifact_storage_env_overrides,
    dump_public_config,
)
from apps.remote_runner.execution_query_storage import fetch_run_results
from apps.remote_runner.result_preview_service import build_result_preview_data
from apps.remote_runner.run_execution_storage import claim_next_run_job
from apps.remote_runner.storage import create_run_record, persist_artifact
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_revision_storage import create_or_fetch_workflow_revision
from tests.helpers.reference_database import make_configured_remote_runner


class FakeS3Object(io.BytesIO):
    def release_conn(self) -> None:
        return None


class FakeS3Stat:
    def __init__(self, size: int, metadata: dict[str, str]) -> None:
        self.size = size
        self.metadata = metadata


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.get_object_calls = 0

    def fput_object(
        self,
        bucket: str,
        object_name: str,
        file_path: str,
        *,
        content_type: str,
        metadata: dict[str, str],
    ):
        payload = Path(file_path).read_bytes()
        self.objects[(bucket, object_name)] = {
            "payload": payload,
            "contentType": content_type,
            "metadata": dict(metadata),
        }
        return type("Result", (), {"bucket_name": bucket, "object_name": object_name})()

    def stat_object(self, bucket: str, object_name: str) -> FakeS3Stat:
        item = self.objects[(bucket, object_name)]
        return FakeS3Stat(size=len(item["payload"]), metadata=dict(item["metadata"]))

    def get_object(self, bucket: str, object_name: str) -> FakeS3Object:
        self.get_object_calls += 1
        return FakeS3Object(self.objects[(bucket, object_name)]["payload"])


def test_s3_artifact_round_trips_through_preview_audit_and_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_io._build_s3_client", lambda _cfg: fake)
    cfg = _s3_config(tmp_path)
    _create_run(cfg, "run_s3")
    artifact_path = tmp_path / "report.txt"
    artifact_path.write_bytes(b"accepted\n")

    artifact = persist_artifact(
        cfg,
        run_id="run_s3",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
        artifact_key="report",
    )
    bucket, object_name = _bucket_and_object(artifact["storageUri"])
    materialization = list_artifact_materializations(cfg, artifact["artifactBlobId"])[0]
    preview = build_result_preview_data(cfg, "res_run_s3")
    audit = build_result_artifact_audit(cfg, "res_run_s3")
    package = export_result_package(cfg, "res_run_s3", include_artifacts=True)

    assert artifact["storageBackend"] == "s3"
    assert artifact["storageUri"] == f"s3://h2ometa-artifacts/{object_name}"
    assert object_name.startswith(f"tenant-a/artifacts/sha256/{artifact['sha256'][:2]}/")
    assert fake.objects[(bucket, object_name)]["metadata"]["X-Amz-Meta-H2OMeta-Sha256"] == artifact["sha256"]
    assert materialization["storageBackend"] == "s3"
    assert materialization["storageUri"] == artifact["storageUri"]
    assert materialization["localPath"] is None
    assert preview["preview"] == {"kind": "text", "content": "accepted\n", "truncated": False}
    assert audit["status"] == "passed"
    assert audit["artifacts"][0]["checksumOk"] is True
    with zipfile.ZipFile(package["packagePath"]) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        payload = archive.read(f"artifacts/{artifact['artifactId']}/report.txt")
    assert manifest["artifacts"][0]["storageBackend"] == "s3"
    assert payload == b"accepted\n"

    fake.objects[(bucket, object_name)]["payload"] = b"tampered\n"
    failed = build_result_artifact_audit(cfg, "res_run_s3")
    assert failed["status"] == "failed"
    assert failed["artifacts"][0]["checksumOk"] is False
    with pytest.raises(ValueError, match="RESULT_ARTIFACT_CHECKSUM_AUDIT_FAILED"):
        build_result_preview_data(cfg, "res_run_s3", artifact["artifactId"])


def test_s3_metadata_only_result_package_does_not_fetch_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_io._build_s3_client", lambda _cfg: fake)
    cfg = _s3_config(tmp_path)
    _create_run(cfg, "run_s3_metadata_only")
    artifact_path = tmp_path / "report.txt"
    artifact_path.write_bytes(b"accepted\n")

    artifact = persist_artifact(
        cfg,
        run_id="run_s3_metadata_only",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
        artifact_key="report",
    )
    fake.get_object_calls = 0

    package = export_result_package(cfg, "res_run_s3_metadata_only", include_artifacts=False)

    assert fake.get_object_calls == 0
    assert package["artifactPayloadMode"] == "metadata-only"
    with zipfile.ZipFile(package["packagePath"]) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert f"artifacts/{artifact['artifactId']}/report.txt" not in names
    assert manifest["artifacts"][0]["externalUri"] == artifact["storageUri"]
    assert manifest["audit"]["verificationMode"] == "metadata-only"


def test_s3_result_preview_rejects_unmanaged_object_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_io._build_s3_client", lambda _cfg: fake)
    cfg = _s3_config(tmp_path)
    _create_run(cfg, "run_s3_unmanaged_preview")
    artifact_path = tmp_path / "report.txt"
    artifact_path.write_bytes(b"accepted\n")
    artifact = persist_artifact(
        cfg,
        run_id="run_s3_unmanaged_preview",
        kind="report",
        path=artifact_path,
        mime_type="text/plain",
        artifact_key="report",
    )
    unmanaged_uri = "s3://h2ometa-artifacts/tenant-a/unmanaged/report.txt"
    with get_connection(cfg) as connection:
        connection.execute(
            "UPDATE artifacts SET storage_uri = ? WHERE artifact_id = ?",
            (unmanaged_uri, artifact["artifactId"]),
        )
        connection.commit()

    with pytest.raises(ValueError, match="RESULT_ARTIFACT_STORAGE_UNMANAGED: unmanaged_s3_object"):
        build_result_preview_data(cfg, "res_run_s3_unmanaged_preview", artifact["artifactId"])


def test_s3_directory_artifact_round_trips_as_manifest_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_io._build_s3_client", lambda _cfg: fake)
    cfg = _s3_config(tmp_path)
    _create_run(cfg, "run_s3_dir")
    artifact_dir = tmp_path / "artifact-dir"
    artifact_dir.mkdir()
    nested = artifact_dir / "nested"
    nested.mkdir()
    (nested / "report.txt").write_bytes(b"accepted\n")
    expected_size, expected_sha = artifact_payload_stats(artifact_dir)

    artifact = persist_artifact(
        cfg,
        run_id="run_s3_dir",
        kind="report",
        path=artifact_dir,
        mime_type="inode/directory",
        artifact_key="report",
    )
    bucket, object_name = _bucket_and_object(artifact["storageUri"])
    package_payload = fake.objects[(bucket, object_name)]["payload"]
    materialization = list_artifact_materializations(cfg, artifact["artifactBlobId"])[0]
    preview = build_result_preview_data(cfg, "res_run_s3_dir", artifact["artifactId"])
    audit = build_result_artifact_audit(cfg, "res_run_s3_dir")
    workflow_revision_id = _workflow_revision_id(cfg, "run_s3_dir")
    lookup = lookup_artifact_cache_entry(
        cfg,
        {
            "workflowRevisionId": workflow_revision_id,
            "artifactKey": "report",
            "role": "output",
            "inputs": [],
            "params": {},
            "resourceBindings": {},
            "execution": {},
        },
    )
    package = export_result_package(cfg, "res_run_s3_dir", include_artifacts=True)

    assert artifact["storageBackend"] == "s3"
    assert artifact["sizeBytes"] == expected_size
    assert artifact["sha256"] == expected_sha
    assert fake.objects[(bucket, object_name)]["contentType"] == "application/zip"
    assert fake.objects[(bucket, object_name)]["metadata"]["X-Amz-Meta-H2OMeta-Package-Type"] == "h2ometa.directory-artifact-package.v1"
    assert materialization["localPath"] is None
    assert preview["preview"]["kind"] == "directory"
    assert preview["preview"]["logicalSha256"] == expected_sha
    assert {"path": "nested/report.txt", "kind": "file", "sizeBytes": 9, "sha256": hashlib.sha256(b"accepted\n").hexdigest()} in preview["preview"]["entries"]
    assert audit["status"] == "passed"
    assert audit["artifacts"][0]["checksumOk"] is True
    assert lookup["hit"] is True
    assert lookup["entry"]["sha256"] == expected_sha
    with zipfile.ZipFile(io.BytesIO(package_payload)) as archive:
        assert archive.read("bagit.txt") == b"BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n"
        manifest = json.loads(archive.read("h2ometa-directory-manifest.json").decode("utf-8"))
    assert manifest["logicalSha256"] == expected_sha
    with zipfile.ZipFile(package["packagePath"]) as archive:
        payload = archive.read(f"artifacts/{artifact['artifactId']}/nested/report.txt")
    assert payload == b"accepted\n"

    fake.objects[(bucket, object_name)]["payload"] = b"not-a-valid-directory-package"
    failed = build_result_artifact_audit(cfg, "res_run_s3_dir")
    assert failed["status"] == "failed"
    assert failed["artifacts"][0]["checksumOk"] is False
    with pytest.raises(ValueError, match="RESULT_ARTIFACT_CHECKSUM_AUDIT_FAILED"):
        build_result_preview_data(cfg, "res_run_s3_dir", artifact["artifactId"])


def test_s3_directory_cache_hit_restores_declared_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_io._build_s3_client", lambda _cfg: fake)
    cfg = _s3_config(tmp_path)
    revision = _create_revision(cfg, "shared_s3_dir_cache")
    _create_run(cfg, "run_s3_dir_cache_source", revision=revision)
    artifact_dir = tmp_path / "artifact-dir-cache-source"
    artifact_dir.mkdir()
    nested = artifact_dir / "nested"
    nested.mkdir()
    (nested / "report.txt").write_bytes(b"cached directory\n")
    source = persist_artifact(
        cfg,
        run_id="run_s3_dir_cache_source",
        kind="directory",
        path=artifact_dir,
        mime_type="inode/directory",
        artifact_key="report",
        step_id="summarize",
    )
    target_spec = _run_spec("run_s3_dir_cache_target", revision["workflowRevisionId"])
    claim = _create_attempt(cfg, target_spec)
    restored_dir = Path(cfg.results_dir) / "run_s3_dir_cache_target" / "report-dir"

    adopted = try_adopt_cached_outputs(
        cfg,
        run_id="run_s3_dir_cache_target",
        request_id="req_run_s3_dir_cache_target",
        run_spec=target_spec,
        output_schema=_output_schema("inode/directory"),
        outputs={"report": str(restored_dir)},
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        result_dir=str(Path(cfg.results_dir) / "run_s3_dir_cache_target"),
    )

    results = fetch_run_results(cfg, "run_s3_dir_cache_target")
    materializations = list_artifact_materializations(cfg, source["artifactBlobId"])

    assert adopted["adopted"] is True
    assert (restored_dir / "nested" / "report.txt").read_bytes() == b"cached directory\n"
    assert results["artifacts"][0]["storageBackend"] == "local"
    assert results["artifacts"][0]["storageUri"] == restored_dir.resolve().as_uri()
    assert results["artifacts"][0]["sha256"] == source["sha256"]
    assert any(item["localPath"] == str(restored_dir.resolve()) for item in materializations)


def test_candidate_output_adoption_uses_s3_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeS3Client()
    monkeypatch.setattr("apps.remote_runner.artifact_io._build_s3_client", lambda _cfg: fake)
    cfg = _s3_config(tmp_path)
    claim = _create_attempt(cfg, "run_candidate_s3")
    output = tmp_path / "candidate.txt"
    output.write_bytes(b"candidate output\n")
    candidate = record_candidate_output(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        output_key="report",
        path=output,
    )
    expected = {
        "report": {
            "path": str(output),
            "kind": "report",
            "mimeType": "text/plain",
            "sha256": candidate["sha256"],
        }
    }

    verify_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
    )
    adopted = adopt_verified_candidate_outputs(
        cfg,
        run_id=claim["runId"],
        attempt_id=claim["attemptId"],
        lease_generation=claim["leaseGeneration"],
        expected_outputs=expected,
    )
    artifact = fetch_run_results(cfg, claim["runId"])["artifacts"][0]

    assert adopted["artifactIds"] == [artifact["artifactId"]]
    assert artifact["storageBackend"] == "s3"
    assert artifact["storageUri"].startswith("s3://h2ometa-artifacts/tenant-a/artifacts/sha256/")
    bucket, object_name = _bucket_and_object(artifact["storageUri"])
    assert fake.objects[(bucket, object_name)]["payload"] == b"candidate output\n"


def test_public_config_redacts_s3_credentials() -> None:
    cfg = RemoteRunnerConfig(
        token="runner-token",
        artifact_s3_access_key="access-key",
        artifact_s3_secret_key="secret-key",
    )
    public = dump_public_config(cfg)

    assert "token" not in public
    assert "artifact_s3_access_key" not in public
    assert "artifact_s3_secret_key" not in public


def test_artifact_s3_env_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = RemoteRunnerConfig()
    monkeypatch.setenv("H2OMETA_ARTIFACT_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_ENDPOINT", "minio.local:9000")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_BUCKET", "h2ometa-artifacts")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_REGION", "us-east-1")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_ACCESS_KEY", "access-key")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_SECRET_KEY", "secret-key")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_PREFIX", "tenant-a")
    monkeypatch.setenv("H2OMETA_ARTIFACT_S3_SECURE", "false")

    apply_artifact_storage_env_overrides(cfg)

    assert cfg.artifact_storage_backend == "s3"
    assert cfg.artifact_s3_endpoint == "minio.local:9000"
    assert cfg.artifact_s3_bucket == "h2ometa-artifacts"
    assert cfg.artifact_s3_region == "us-east-1"
    assert cfg.artifact_s3_access_key == "access-key"
    assert cfg.artifact_s3_secret_key == "secret-key"
    assert cfg.artifact_s3_prefix == "tenant-a"
    assert cfg.artifact_s3_secure is False


def _s3_config(tmp_path: Path) -> RemoteRunnerConfig:
    cfg = make_configured_remote_runner(tmp_path)
    cfg.artifact_storage_backend = "s3"
    cfg.artifact_s3_endpoint = "minio.local:9000"
    cfg.artifact_s3_bucket = "h2ometa-artifacts"
    cfg.artifact_s3_access_key = "access-key"
    cfg.artifact_s3_secret_key = "secret-key"
    cfg.artifact_s3_secure = False
    cfg.artifact_s3_prefix = "tenant-a"
    return cfg


def _create_run(
    cfg: RemoteRunnerConfig,
    run_id: str,
    *,
    complete: bool = True,
    revision: dict[str, object] | None = None,
) -> None:
    selected_revision = revision or _create_revision(cfg, run_id)
    create_run_record(
        cfg,
        server_id="srv_artifact",
        request_id=f"req_{run_id}",
        run_spec={
            "runId": run_id,
            "projectId": "proj_artifact",
            "pipelineId": "pipeline_artifact",
            "pipelineVersion": "0.1.0",
            "runSpecVersion": "2026-04-21",
            "workflowRevisionId": selected_revision["workflowRevisionId"],
        },
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    if complete:
        _mark_run_terminal(cfg, run_id)


def _create_revision(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, object]:
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id=f"draft_{run_id}",
        draft_revision=1,
        manifest={
            "files": [{"path": "workflow/Snakefile", "sha256": "a" * 64}],
            "layout": {"snakefile": "workflow/Snakefile"},
        },
        graph_snapshot={"nodes": ["report"], "edges": [], "runSpec": {"runId": run_id}},
        runtime_lock={"snakemake": "9.23.1"},
        compiler={"name": "h2ometa-test", "version": "0.1.0"},
        created_by="pytest",
    )


def _run_spec(run_id: str, workflow_revision_id: object) -> dict[str, object]:
    return {
        "runId": run_id,
        "projectId": "proj_artifact",
        "pipelineId": "pipeline_artifact",
        "pipelineVersion": "0.1.0",
        "runSpecVersion": "2026-04-21",
        "workflowRevisionId": str(workflow_revision_id),
    }


def _create_attempt(cfg: RemoteRunnerConfig, run_or_spec: str | dict[str, object]):
    if isinstance(run_or_spec, dict):
        create_run_record(
            cfg,
            server_id="srv_artifact",
            request_id=f"req_{run_or_spec['runId']}",
            run_spec=run_or_spec,
            idempotency_key=f"idem_{run_or_spec['runId']}",
            payload_hash=f"hash_{run_or_spec['runId']}",
        )
    else:
        _create_run(cfg, run_or_spec, complete=False)
    claim = claim_next_run_job(
        cfg,
        worker_id="worker_candidate",
        now="2099-06-07T10:00:00Z",
        lease_seconds=30,
    )
    assert claim is not None
    return claim


def _output_schema(mime_type: str = "text/plain") -> dict[str, object]:
    return {
        "artifacts": [
            {
                "key": "report",
                "kind": "report",
                "mimeType": mime_type,
                "stepId": "summarize",
            }
        ]
    }


def _mark_run_terminal(cfg: RemoteRunnerConfig, run_id: str) -> None:
    with get_connection(cfg) as connection:
        connection.execute(
            """
            UPDATE runs
            SET status = 'completed',
                stage = 'complete',
                finished_at = '2099-06-07T10:00:00Z',
                last_updated_at = '2099-06-07T10:00:00Z'
            WHERE run_id = ?
            """,
            (run_id,),
        )
        connection.execute(
            "UPDATE run_jobs SET state = 'completed', updated_at = ? WHERE run_id = ?",
            ("2099-06-07T10:00:00Z", run_id),
        )
        connection.commit()


def _bucket_and_object(storage_uri: str) -> tuple[str, str]:
    _, rest = storage_uri.split("s3://", 1)
    bucket, object_name = rest.split("/", 1)
    return bucket, object_name


def _workflow_revision_id(cfg: RemoteRunnerConfig, run_id: str) -> str:
    with get_connection(cfg) as connection:
        row = connection.execute("SELECT workflow_revision_id FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row is not None
    return str(row["workflow_revision_id"])
