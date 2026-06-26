from __future__ import annotations

from fastapi.testclient import TestClient

from apps.remote_runner import artifact_lifecycle_controller_control_route_service
from apps.remote_runner import route_utils
from apps.remote_runner.errors import RemoteRunnerAuthorizationError
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.route_utils import authorize_action
from tests.helpers.reference_database import make_configured_remote_runner


def test_artifact_lifecycle_controller_run_once_requires_artifact_curator_role(tmp_path) -> None:
    denied = make_configured_remote_runner(
        tmp_path / "denied",
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    curator = make_configured_remote_runner(
        tmp_path / "curator",
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )

    try:
        authorize_action(denied, "artifact.lifecycle.controller.run_once")
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError("artifact.lifecycle.controller.run_once must require artifact-curator")
    deny_events = list_governance_audit_events(denied, action="artifact.lifecycle.controller.run_once")["items"]
    assert deny_events[-1]["decision"] == "deny"
    assert deny_events[-1]["details"]["requiredRoles"] == ["artifact-curator"]
    assert deny_events[-1]["details"]["providedRoles"] == ["auditor"]
    assert authorize_action(curator, "artifact.lifecycle.controller.run_once").roles == ("artifact-curator",)


def test_artifact_lifecycle_controller_run_once_route_denies_wrong_role_before_tick(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_controller_tick(*_args, **_kwargs):
        raise AssertionError("controller run-once must not run before authorization")

    monkeypatch.setattr(
        artifact_lifecycle_controller_control_route_service,
        "run_governed_artifact_lifecycle_controller_once",
        fail_controller_tick,
    )

    response = TestClient(app).post(
        "/api/v1/artifacts/lifecycle/controller/run-once",
        headers={"Authorization": "Bearer rbac-token"},
        json={"confirmation": "run-artifact-lifecycle-controller-once"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    events = list_governance_audit_events(cfg, action="artifact.lifecycle.controller.run_once")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["subjectKind"] == "artifact_lifecycle_controller"
    assert events[0]["subjectId"] == "authorization"
