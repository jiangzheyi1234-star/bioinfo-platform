from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from apps.remote_runner import result_read_service, route_utils
from apps.remote_runner.errors import RemoteRunnerAuthorizationError
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.route_utils import authorize_action
from tests.helpers.reference_database import make_configured_remote_runner


RESULT_READ_ACTIONS = ("run.results.read", "result.list", "result.read")


def test_result_read_actions_allow_auditor_and_artifact_curator_roles(tmp_path) -> None:
    denied = make_configured_remote_runner(tmp_path / "denied", api_token_roles=("workflow-operator",))
    auditor = make_configured_remote_runner(tmp_path / "auditor", api_token_roles=("auditor",))
    curator = make_configured_remote_runner(tmp_path / "curator", api_token_roles=("artifact-curator",))

    for action in RESULT_READ_ACTIONS:
        with pytest.raises(RemoteRunnerAuthorizationError):
            authorize_action(denied, action)
        assert authorize_action(auditor, action).roles == ("auditor",)
        assert authorize_action(curator, action).roles == ("artifact-curator",)


def test_result_read_routes_deny_wrong_role_before_storage_fetch(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("workflow-operator",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("result storage fetch must not run before authorization")

    monkeypatch.setattr(result_read_service, "fetch_run_results", fail_fetch)
    monkeypatch.setattr(result_read_service, "list_results", fail_fetch)
    monkeypatch.setattr(result_read_service, "fetch_result", fail_fetch)

    client = TestClient(app)
    responses = [
        client.get("/api/v1/runs/run_denied/results", headers={"Authorization": "Bearer rbac-token"}),
        client.get("/api/v1/results", headers={"Authorization": "Bearer rbac-token"}),
        client.get("/api/v1/results/res_denied", headers={"Authorization": "Bearer rbac-token"}),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    for response in responses:
        assert response.json()["detail"] == "runner authorization failed"
    for action in RESULT_READ_ACTIONS:
        events = list_governance_audit_events(cfg, action=action)["items"]
        assert len(events) == 1
        assert events[0]["decision"] == "deny"


def test_result_read_routes_return_public_payload_and_record_safe_allow_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(tmp_path, token="rbac-token", api_token_roles=("auditor",))
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(result_read_service, "fetch_run_results", lambda _cfg, run_id: _raw_run_results(run_id))
    monkeypatch.setattr(
        result_read_service,
        "list_results",
        lambda _cfg: [
            {
                "resultId": "res_run_public",
                "runId": "run_public",
                "title": "Public result",
                "pipelineId": "pipe_public",
                "artifactCount": 1,
                "inputArtifactCount": 1,
                "producedAt": "2099-06-07T10:00:00Z",
                "storageUri": "file:///C:/secret/list.txt",
            }
        ],
    )
    monkeypatch.setattr(
        result_read_service,
        "fetch_result",
        lambda _cfg, result_id: {
            **_raw_run_results("run_public"),
            "resultId": result_id,
            "title": "Public result",
            "pipelineId": "pipe_public",
            "producedAt": "2099-06-07T10:00:00Z",
        },
    )

    client = TestClient(app)
    run_results = client.get("/api/v1/runs/run_public/results", headers={"Authorization": "Bearer rbac-token"})
    result_list = client.get("/api/v1/results", headers={"Authorization": "Bearer rbac-token"})
    result_detail = client.get("/api/v1/results/res_run_public", headers={"Authorization": "Bearer rbac-token"})

    assert run_results.status_code == 200
    assert result_list.status_code == 200
    assert result_detail.status_code == 200
    public_payload = json.dumps(
        [run_results.json()["data"], result_list.json()["data"], result_detail.json()["data"]],
        sort_keys=True,
    )
    for forbidden in (
        "resultDir",
        "path",
        "storageUri",
        "externalUri",
        "packagePath",
        "packageUri",
        "localPath",
        "sourceStorageUri",
        "inputStorageUri",
        "lineageEdges",
        "C:/secret",
        "raw_lineage_secret",
    ):
        assert forbidden not in public_payload
    assert run_results.json()["data"]["artifacts"][0]["artifactId"] == "art_public"
    assert result_detail.json()["data"]["inputArtifacts"][0]["ports"][0]["artifactId"] == "art_source"

    events = []
    for action in RESULT_READ_ACTIONS:
        action_events = list_governance_audit_events(cfg, action=action)["items"]
        assert len(action_events) == 1
        assert action_events[0]["decision"] == "allow"
        assert action_events[0]["actorRoles"] == ["auditor"]
        events.extend(action_events)
    serialized_events = json.dumps(events, sort_keys=True)
    assert "C:/secret" not in serialized_events
    assert "storageUri" not in serialized_events
    assert "raw_lineage_secret" not in serialized_events
    assert "rbac-token" not in serialized_events


def _raw_run_results(run_id: str) -> dict[str, object]:
    return {
        "runId": run_id,
        "resultDir": "C:/secret/results/run_public",
        "artifactCount": 1,
        "artifacts": [
            {
                "artifactId": "art_public",
                "runId": run_id,
                "kind": "report",
                "path": "C:/secret/report.txt",
                "storageBackend": "local",
                "storageUri": "file:///C:/secret/report.txt",
                "externalUri": "file:///C:/secret/external.txt",
                "packagePath": "C:/secret/package.zip",
                "packageUri": "file:///C:/secret/package.zip",
                "localPath": "C:/secret/local.txt",
                "sizeBytes": 11,
                "sha256": "a" * 64,
                "mimeType": "text/plain",
            }
        ],
        "inputArtifactCount": 1,
        "inputArtifacts": [
            {
                "artifactBlobId": "ablob_public",
                "sha256": "b" * 64,
                "mimeType": "text/plain",
                "sizeBytes": 11,
                "ports": [
                    {
                        "artifactId": "art_source",
                        "sourceType": "artifact",
                        "sourceStorageUri": "file:///C:/secret/source.txt",
                        "inputStorageUri": "file:///C:/secret/input.txt",
                        "localPath": "C:/secret/input.txt",
                    }
                ],
            }
        ],
        "lineageEdges": [{"payload": {"storageUri": "file:///C:/secret/raw_lineage_secret.txt"}}],
    }
