from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.remote_runner import control_service
from apps.remote_runner import result_read_service
from apps.remote_runner import route_utils
from apps.remote_runner.errors import RemoteRunnerAuthorizationError
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.route_utils import authorize_action
from tests.helpers.reference_database import make_configured_remote_runner


def test_result_read_actions_allow_auditor_and_artifact_curator_roles(tmp_path) -> None:
    denied = make_configured_remote_runner(
        tmp_path / "denied",
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    auditor = make_configured_remote_runner(
        tmp_path / "auditor",
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    curator = make_configured_remote_runner(
        tmp_path / "curator",
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )

    for action in ("run.results.read", "result.list", "result.read"):
        try:
            authorize_action(denied, action)
        except RemoteRunnerAuthorizationError as exc:
            assert str(exc) == "runner authorization failed"
        else:
            raise AssertionError(f"{action} must require auditor or artifact-curator")
        deny_events = list_governance_audit_events(denied, action=action)["items"]
        assert deny_events[-1]["decision"] == "deny"
        assert deny_events[-1]["details"]["requiredRoles"] == ["artifact-curator", "auditor"]
        assert deny_events[-1]["details"]["providedRoles"] == ["workflow-operator"]
        assert authorize_action(auditor, action).roles == ("auditor",)
        assert authorize_action(curator, action).roles == ("artifact-curator",)


def test_result_read_routes_deny_wrong_role_before_fetch(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_read(*_args, **_kwargs):
        raise AssertionError("result storage read must not run before authorization")

    monkeypatch.setattr(control_service, "governed_fetch_run_results", fail_read)
    monkeypatch.setattr(control_service, "governed_list_results", fail_read)
    monkeypatch.setattr(control_service, "governed_fetch_result", fail_read)

    client = TestClient(app)
    responses = [
        client.get("/api/v1/runs/run_denied/results", headers={"Authorization": "Bearer rbac-token"}),
        client.get("/api/v1/results", headers={"Authorization": "Bearer rbac-token"}),
        client.get("/api/v1/results/res_denied", headers={"Authorization": "Bearer rbac-token"}),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    assert all(response.json()["detail"] == "runner authorization failed" for response in responses)
    for action in ("run.results.read", "result.list", "result.read"):
        events = list_governance_audit_events(cfg, action=action)["items"]
        assert len(events) == 1
        assert events[0]["decision"] == "deny"


def test_result_read_routes_record_safe_allow_audit_and_redact_public_payload(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(result_read_service, "fetch_run_results", lambda _cfg, run_id: _raw_run_results(run_id))
    monkeypatch.setattr(result_read_service, "list_results", lambda _cfg: [_raw_result_summary()])
    monkeypatch.setattr(result_read_service, "fetch_result", lambda _cfg, result_id: _raw_result_detail(result_id))

    client = TestClient(app)
    run_results = client.get(
        "/api/v1/runs/run_result_public/results",
        headers={"Authorization": "Bearer rbac-token"},
    )
    result_list = client.get("/api/v1/results", headers={"Authorization": "Bearer rbac-token"})
    result_detail = client.get(
        "/api/v1/results/res_public",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert run_results.status_code == 200
    assert result_list.status_code == 200
    assert result_detail.status_code == 200
    public_payload = json.dumps(
        [run_results.json(), result_list.json(), result_detail.json()],
        sort_keys=True,
    )
    assert "C:/secret" not in public_payload
    assert "file:///secret" not in public_payload
    assert "s3://secret" not in public_payload
    assert "storageUri" not in public_payload
    assert "resultDir" not in public_payload
    assert "lineageEdges" not in public_payload
    assert run_results.json()["data"]["artifacts"][0]["artifactKey"] == "report"
    assert result_detail.json()["data"]["artifacts"][0]["artifactKey"] == "report"
    unsafe_labels = [
        "C:/secret/token-output",
        "s3://bucket/report",
        "report summary",
        "api_key_report",
        "r" * 81,
    ]
    for label in unsafe_labels:
        unsafe = result_read_service.public_run_results(
            {"artifacts": [{"artifactId": "art_unsafe", "artifactKey": label}]}
        )
        assert "artifactKey" not in unsafe["artifacts"][0]

    run_audit = list_governance_audit_events(cfg, action="run.results.read")["items"][-1]
    list_audit = list_governance_audit_events(cfg, action="result.list")["items"][-1]
    detail_audit = list_governance_audit_events(cfg, action="result.read")["items"][-1]
    assert run_audit["details"] == {
        "artifactCount": 1,
        "inputArtifactCount": 1,
        "lineageEdgesReturned": False,
    }
    assert list_audit["details"] == {"returnedCount": 1}
    assert detail_audit["details"] == {
        "artifactCount": 1,
        "inputArtifactCount": 1,
    }
    serialized_details = json.dumps(
        [run_audit["details"], list_audit["details"], detail_audit["details"]],
        sort_keys=True,
    )
    assert "run_result_public" not in serialized_details
    assert "res_public" not in serialized_details
    assert "C:/secret" not in serialized_details
    assert "rbac-token" not in json.dumps([run_audit, list_audit, detail_audit], sort_keys=True)


def _raw_run_results(run_id: str) -> dict:
    return {
        "runId": run_id,
        "resultDir": "C:/secret/results",
        "artifactCount": 1,
        "inputArtifactCount": 1,
        "artifacts": [
            {
                "artifactId": "art_report",
                "kind": "report",
                "path": "C:/secret/results/report.txt",
                "storageUri": "file:///secret/results/report.txt",
                "artifactKey": "report",
                "sizeBytes": 12,
                "sha256": "a" * 64,
            }
        ],
        "inputArtifacts": [
            {
                "artifactBlobId": "blob_reads",
                "sha256": "b" * 64,
                "sizeBytes": 5,
                "sourceStorageUri": "s3://secret/input.fastq",
                "ports": [
                    {
                        "sourceType": "artifact",
                        "artifactId": "art_reads",
                        "upstreamRunId": "run_secret_upstream",
                        "portName": "reads",
                        "storageUri": "file:///secret/input.fastq",
                    }
                ],
            }
        ],
        "lineageEdges": [{"payload": {"storageUri": "file:///secret/lineage.json"}}],
    }


def _raw_result_summary() -> dict:
    return {
        "resultId": "res_list",
        "runId": "run_list",
        "title": "Pipeline result",
        "pipelineId": "pipe_public",
        "artifactCount": 1,
        "inputArtifactCount": 1,
        "producedAt": "2099-06-07T10:00:00Z",
        "resultDir": "C:/secret/list",
        "storageUri": "file:///secret/list",
    }


def _raw_result_detail(result_id: str) -> dict:
    return {
        "resultId": result_id,
        "title": "Pipeline result",
        "pipelineId": "pipe_public",
        "producedAt": "2099-06-07T10:00:00Z",
        **_raw_run_results("run_result_detail"),
    }
