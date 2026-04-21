from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import Response

from apps.api.main import (
    accept_server_host_key,
    app,
    bootstrap_server,
    get_project,
    get_run,
    get_run_events,
    get_run_results,
    get_result,
    get_result_preview,
    get_server_health,
    list_results,
    list_servers,
    refresh_server_health,
    rotate_server_token,
    submit_run,
    upload_file,
)
from apps.api.models import RunSubmitRequest, UploadSubmitRequest
from core.app_runtime.service import RuntimeService, ServiceLocator
from core.data.project_manager import ProjectManager


def make_service(tmp_path: Path) -> RuntimeService:
    manager = ProjectManager(
        projects_root=tmp_path / "projects",
        index_path=tmp_path / "projects.json",
    )
    service = RuntimeService(project_manager=manager, service_locator=ServiceLocator())
    service._initialized = True
    return service


def test_get_project_contract(monkeypatch, tmp_path: Path) -> None:
    service = make_service(tmp_path)
    created = service.create_project("Project Alpha", "omics batch", open_after_create=False)
    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    payload = asyncio.run(get_project(created["project_id"]))
    assert payload["data"]["project_id"] == created["project_id"]
    assert payload["data"]["name"] == "Project Alpha"


def test_servers_health_contract_exposes_reason_code(monkeypatch, tmp_path: Path) -> None:
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "core.app_runtime.service.get_config",
        lambda: {
            "ssh": {
                "host": "192.168.0.10",
                "port": 22,
                "user": "tester",
                "auth_mode": "key_file",
                "identity_ref": "C:/keys/id_ed25519",
                "timeout_sec": 5,
            }
        },
    )
    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    servers_payload = asyncio.run(list_servers())
    server = servers_payload["data"]["items"][0]
    assert server["serverId"].startswith("srv_")
    assert server["reasonCode"] == "SSH_NOT_CONNECTED"

    health_payload = asyncio.run(get_server_health(server["serverId"]))
    health = health_payload["data"]
    assert health["reasonCode"] == "SSH_NOT_CONNECTED"
    assert set(health.keys()) >= {"startup", "live", "ready", "reasonCode", "checkedAt"}


def test_server_actions_update_server_state(monkeypatch, tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = {
        "ssh": {
            "host": "192.168.0.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {},
    }

    class FakeRemoteRunnerManager:
        def bootstrap(self, **kwargs):
            return {
                "bootstrap_version": "phase1-test",
                "runner_mode": "background_process",
                "tunnel_port": 18765,
                "service_port": 8876,
                "token_ref": "runner://srv_test",
                "health": {
                    "startup": {"ok": True, "message": "Remote runner config loaded."},
                    "live": {"ok": True, "message": "Remote runner process is alive."},
                    "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                    "reasonCode": "",
                    "checkedAt": "2026-04-21T12:00:00Z",
                },
            }

        def rotate_token(self, **kwargs):
            return {"token_ref": "runner://srv_test_rotated"}

        def get_health(self, **kwargs):
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-21T12:00:00Z",
            }

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        cfg.clear()
        cfg.update(snapshot)

    monkeypatch.setattr("core.app_runtime.service.get_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.service.save_config", save_capture)
    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    server = asyncio.run(list_servers())["data"]["items"][0]
    server_id = server["serverId"]

    accepted = asyncio.run(accept_server_host_key(server_id))
    assert accepted["data"]["hostKeyTrusted"] is True

    rotated = asyncio.run(rotate_server_token(server_id))
    assert rotated["data"]["tokenRotated"] is True

    bootstrapped = asyncio.run(bootstrap_server(server_id))
    assert bootstrapped["data"]["ready"]["ok"] is True
    assert bootstrapped["data"]["reasonCode"] == ""

    refreshed = asyncio.run(refresh_server_health(server_id))
    assert refreshed["data"]["ready"]["ok"] is True


def test_connected_server_health_requires_runner_bootstrap(monkeypatch, tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    monkeypatch.setattr(
        "core.app_runtime.service.get_config",
        lambda: {
            "ssh": {
                "host": "192.168.0.10",
                "port": 22,
                "user": "tester",
                "auth_mode": "key_file",
                "identity_ref": "C:/keys/id_ed25519",
                "timeout_sec": 5,
            }
        },
    )

    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    server = asyncio.run(list_servers())["data"]["items"][0]
    assert server["connected"] is True
    assert server["ready"] is False
    assert server["reasonCode"] == "RUNNER_NOT_READY"


def test_bootstrap_server_uses_remote_runner_manager_and_persists_server_registry(
    monkeypatch, tmp_path: Path
) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = {
        "ssh": {
            "host": "192.168.0.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {},
    }

    class FakeRemoteRunnerManager:
        def __init__(self) -> None:
            self.bootstrap_calls: list[dict[str, object]] = []

        def bootstrap(self, **kwargs):
            self.bootstrap_calls.append(kwargs)
            return {
                "bootstrap_version": "phase1-test",
                "runner_mode": "background_process",
                "tunnel_port": 18765,
                "service_port": 8876,
                "token_ref": "runner://srv_test",
                "health": {
                    "startup": {"ok": True, "message": "Remote runner config loaded."},
                    "live": {"ok": True, "message": "Remote runner process is alive."},
                    "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                    "reasonCode": "",
                    "checkedAt": "2026-04-21T12:00:00Z",
                },
            }

    fake_manager = FakeRemoteRunnerManager()
    service._service_locator.remote_runner_manager = fake_manager

    def save_capture(next_cfg: dict) -> None:
        snapshot = dict(next_cfg)
        cfg.clear()
        cfg.update(snapshot)

    monkeypatch.setattr("core.app_runtime.service.get_config", lambda: cfg)
    monkeypatch.setattr("core.app_runtime.service.save_config", save_capture)
    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    server_id = asyncio.run(list_servers())["data"]["items"][0]["serverId"]
    result = asyncio.run(bootstrap_server(server_id))

    assert len(fake_manager.bootstrap_calls) == 1
    assert cfg["servers"][server_id]["bootstrap_version"] == "phase1-test"
    assert cfg["servers"][server_id]["runner_mode"] == "background_process"
    assert cfg["servers"][server_id]["tunnel_port"] == 18765
    assert result["data"]["ready"]["ok"] is True
    assert result["data"]["reasonCode"] == ""


def test_run_detail_and_results_contract(monkeypatch, tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = {
        "ssh": {
            "host": "192.168.0.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {
            "srv_8ab95fcf95a7": {
                "bootstrap_version": "phase2-test",
                "runner_mode": "background_process",
                "service_port": 8876,
                "token_ref": "runner://srv_test",
            }
        },
    }

    class FakeRemoteRunnerManager:
        def get_run(self, **kwargs):
            return {
                "runId": "run_2026_0419_001",
                "stateVersion": 7,
                "requestId": "req_f2b8f4f0",
                "runSpec": {"pipelineId": "taxonomy-v1"},
            }

        def get_health(self, **kwargs):
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-21T12:00:00Z",
            }

        def get_run_events(self, **kwargs):
            return {"items": [{"runId": "run_2026_0419_001", "stateVersion": 7}]}

        def get_run_results(self, **kwargs):
            return {"runId": "run_2026_0419_001", "artifacts": [{"artifactId": "art_001"}], "resultDir": "/srv/results"}

        def list_results(self, **kwargs):
            return [{"resultId": "res_run_2026_0419_001", "runId": "run_2026_0419_001", "title": "taxonomy result", "pipelineId": "taxonomy-v1", "artifactCount": 1, "producedAt": "2026-04-21T12:00:00Z"}]

        def get_result(self, **kwargs):
            return {"runId": "run_2026_0419_001"}

        def get_result_preview(self, **kwargs):
            return {"artifactId": "art_002", "preview": {"kind": "table"}}

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.service.get_config", lambda: cfg)
    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    run_payload = asyncio.run(get_run("run_2026_0419_001"))
    run = run_payload["data"]
    assert run["runId"] == "run_2026_0419_001"
    assert run["stateVersion"] == 7
    assert run["requestId"] == "req_f2b8f4f0"
    assert run["runSpec"]["pipelineId"] == "taxonomy-v1"

    events_payload = asyncio.run(get_run_events("run_2026_0419_001"))
    events = events_payload["data"]["items"]
    assert events[0]["runId"] == "run_2026_0419_001"
    assert "stateVersion" in events[0]

    results_payload = asyncio.run(get_run_results("run_2026_0419_001"))
    results = results_payload["data"]
    assert results["runId"] == "run_2026_0419_001"
    assert results["artifacts"][0]["artifactId"] == "art_001"

    list_results_payload = asyncio.run(list_results())
    assert list_results_payload["data"]["items"][0]["resultId"].startswith("res_run_")

    result_payload = asyncio.run(get_result("res_run_2026_0419_001"))
    assert result_payload["data"]["runId"] == "run_2026_0419_001"

    preview_payload = asyncio.run(get_result_preview("res_run_2026_0419_001", artifact_id="art_002"))
    assert preview_payload["data"]["artifactId"] == "art_002"
    assert preview_payload["data"]["preview"]["kind"] == "table"


def test_submit_run_returns_async_headers(monkeypatch, tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = {
        "ssh": {
            "host": "192.168.0.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {
            "srv_8ab95fcf95a7": {
                "bootstrap_version": "phase2-test",
                "runner_mode": "background_process",
                "service_port": 8876,
                "token_ref": "runner://srv_test",
            }
        },
    }

    class FakeRemoteRunnerManager:
        def submit_run(self, **kwargs):
            return {
                "data": {
                    "runId": "run_2026_phase2",
                    "status": "queued",
                    "stage": "submitted",
                    "requestId": "req_submit_001",
                },
                "location": "/api/v1/runs/run_2026_phase2",
                "retryAfter": 2,
                "requestId": "req_submit_001",
            }

        def get_health(self, **kwargs):
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-21T12:00:00Z",
            }

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.service.get_config", lambda: cfg)
    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    response = Response()
    payload = asyncio.run(
        submit_run(
            RunSubmitRequest(pipelineId="taxonomy-v1", requestId="req_submit_001"),
            response,
        )
    )

    assert response.headers["Location"].startswith("/api/v1/runs/run_")
    assert response.headers["Retry-After"] == "2"
    assert response.headers["X-Request-Id"] == "req_submit_001"
    assert payload["data"]["status"] == "queued"
    assert payload["data"]["requestId"] == "req_submit_001"


def test_submit_run_persists_run_spec_for_followup_detail(monkeypatch, tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = {
        "ssh": {
            "host": "192.168.0.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {
            "srv_8ab95fcf95a7": {
                "bootstrap_version": "phase2-test",
                "runner_mode": "background_process",
                "service_port": 8876,
                "token_ref": "runner://srv_test",
            }
        },
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
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-21T12:00:00Z",
            }

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.service.get_config", lambda: cfg)
    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    response = Response()
    submitted = asyncio.run(
        submit_run(
            RunSubmitRequest(
                runId="run_contract_submit",
                requestId="req_submit_002",
                pipelineId="assembly-v3",
                runSpec={
                    "projectId": "proj_contract",
                    "pipelineId": "assembly-v3",
                    "inputs": [{"sampleId": "sample_alpha", "uploadId": "upl_alpha", "kind": "fastq_pair"}],
                },
            ),
            response,
        )
    )

    detail = asyncio.run(get_run(submitted["data"]["runId"]))
    run = detail["data"]
    assert run["runId"] == "run_contract_submit"
    assert run["projectId"] == "proj_contract"
    assert run["runSpec"]["projectId"] == "proj_contract"
    assert run["runSpec"]["pipelineId"] == "assembly-v3"
    assert run["runSpec"]["inputs"][0]["sampleId"] == "sample_alpha"


def test_upload_file_routes_to_remote_runner_manager(monkeypatch, tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._service_locator.ssh_service = SimpleNamespace(is_connected=True, close=lambda: None)
    cfg = {
        "ssh": {
            "host": "192.168.0.10",
            "port": 22,
            "user": "tester",
            "auth_mode": "key_file",
            "identity_ref": "C:/keys/id_ed25519",
            "timeout_sec": 5,
        },
        "servers": {
            "srv_8ab95fcf95a7": {
                "bootstrap_version": "phase2-test",
                "runner_mode": "background_process",
                "service_port": 8876,
                "token_ref": "runner://srv_test",
            }
        },
    }

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
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-21T12:00:00Z",
            }

    service._service_locator.remote_runner_manager = FakeRemoteRunnerManager()
    monkeypatch.setattr("core.app_runtime.service.get_config", lambda: cfg)
    monkeypatch.setattr("apps.api.main._runtime", lambda: service)

    payload = asyncio.run(
        upload_file(
            UploadSubmitRequest(
                serverId="srv_8ab95fcf95a7",
                filename="reads.fastq",
                contentBase64="QEdPQgo=",
                mimeType="text/plain",
            )
        )
    )

    assert payload["data"]["uploadId"] == "upl_test"
    assert payload["data"]["sha256"] == "abc123"


def test_local_api_keeps_removed_remote_environment_routes_absent() -> None:
    paths = {route.path for route in app.routes}
    removed_paths = (
        "/api/v1/remote/environment",
        "/api/v1/remote/environment/check",
        "/api/v1/remote/environment/discover",
        "/api/v1/remote/environment/profiles",
        "/api/v1/remote/environment/effective",
        "/api/v1/remote/environment/setup",
        "/api/v1/remote/environment/validate",
        "/api/v1/projects/{project_id}/environment",
    )

    for path in removed_paths:
        assert path not in paths
