from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Response

from apps.api.execution_query_routes import get_run
from apps.api.ssh_routes import list_servers
from apps.api.submission_routes import submit_run, upload_file
from apps.api.models import RunSubmitRequest, UploadSubmitRequest
from core.app_runtime.errors import RuntimeServiceError
from tests.test_backend_contract_api import make_service, patch_runtime_service


def test_submit_run_persists_run_spec_for_followup_detail(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {},
    }

    class FakeRemoteRunnerManager:
        def submit_run(self, **kwargs):
            return {
                "data": {
                    "runId": "run_contract_submit",
                    "status": "queued",
                    "stage": "submitted",
                    "requestId": "req_submit_002",
                },
                "location": "/api/v1/runs/run_contract_submit",
                "retryAfter": 2,
                "requestId": "req_submit_002",
            }

        def get_run(self, **kwargs):
            return {
                "runId": "run_contract_submit",
                "projectId": "proj_contract",
                "runSpec": {
                    "projectId": "proj_contract",
                    "pipelineId": "assembly-v3",
                    "inputs": [{"sampleId": "sample_alpha"}],
                },
            }

        def get_health(self, **kwargs):
            return _ready_health()

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    patch_runtime_service(monkeypatch, service)
    server_id = _prepare_ready_server(cfg)

    submitted = asyncio.run(
        submit_run(
            RunSubmitRequest(
                serverId=server_id,
                runId="run_contract_submit",
                requestId="req_submit_002",
                runSpec={
                    "projectId": "proj_contract",
                    "pipelineId": "assembly-v3",
                    "inputs": [
                        {
                            "sampleId": "sample_alpha",
                            "uploadId": "upl_alpha",
                            "kind": "fastq_pair",
                        }
                    ],
                },
            ),
            Response(),
        )
    )

    run = asyncio.run(get_run(submitted["data"]["runId"]))["data"]
    assert run["runId"] == "run_contract_submit"
    assert run["projectId"] == "proj_contract"
    assert run["runSpec"]["projectId"] == "proj_contract"
    assert run["runSpec"]["pipelineId"] == "assembly-v3"
    assert run["runSpec"]["inputs"][0]["sampleId"] == "sample_alpha"


def test_upload_file_routes_to_remote_runner_manager(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _ssh_config()

    class FakeRemoteRunnerManager:
        def upload_content(self, **kwargs):
            return {
                "uploadId": "upl_test",
                "path": "/srv/uploads/upl_test_reads.fastq",
                "sizeBytes": 12,
                "sha256": "abc123",
                "mimeType": "text/plain",
                "uploadedAt": "2026-04-21T12:00:00Z",
            }

        def get_health(self, **kwargs):
            return _ready_health()

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    patch_runtime_service(monkeypatch, service)
    server_id = _prepare_ready_server(cfg)

    payload = asyncio.run(
        upload_file(
            UploadSubmitRequest(
                serverId=server_id,
                filename="reads.fastq",
                contentBase64="QEdPQgo=",
                mimeType="text/plain",
            )
        )
    )

    assert payload["data"]["uploadId"] == "upl_test"
    assert payload["data"]["sha256"] == "abc123"


def test_upload_file_surfaces_runtime_transport_failures_as_service_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = _ssh_config()

    class FakeRemoteRunnerManager:
        def upload_content(self, **kwargs):
            raise RuntimeError("SSH transport is not active")

        def get_health(self, **kwargs):
            return _ready_health()

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.runtime_config.get_runtime_config", lambda: cfg)
    patch_runtime_service(monkeypatch, service)
    server_id = _prepare_ready_server(cfg)

    with pytest.raises(RuntimeServiceError, match="SSH transport is not active"):
        asyncio.run(
            upload_file(
                UploadSubmitRequest(
                    serverId=server_id,
                    filename="reads.fastq",
                    contentBase64="QEdPQgo=",
                    mimeType="text/plain",
                )
            )
        )


def _prepare_ready_server(cfg: dict) -> str:
    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    cfg["servers"][server_id] = {
        "bootstrap_version": "phase2-test",
        "runner_mode": "background_process",
        "service_port": 43127,
        "token_ref": "runner://srv_test",
    }
    return server_id


def _ssh_config() -> dict:
    return {
        "ssh": {
            "host": "192.0.2.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {},
    }


def _ready_health() -> dict:
    return {
        "startup": {"ok": True, "message": "Remote runner config loaded."},
        "live": {"ok": True, "message": "Remote runner process is alive."},
        "ready": {"ok": True, "message": "Remote runner control plane is ready."},
        "reasonCode": "",
        "checkedAt": "2026-04-21T12:00:00Z",
    }
