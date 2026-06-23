from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.databases import list_reference_databases
from apps.remote_runner.errors import RemoteRunnerAuthorizationError
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.route_utils import authorize_action
from tests.helpers.reference_database import make_configured_remote_runner


def test_remote_runner_action_authorization_denies_unknown_and_wrong_roles(tmp_path) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )

    try:
        authorize_action(cfg, "database.create")
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError("database.create must require data-steward")

    deny_events = list_governance_audit_events(cfg, action="database.create")["items"]
    assert len(deny_events) == 1
    assert deny_events[0]["decision"] == "deny"
    assert deny_events[0]["reasonCode"] == "REMOTE_RUNNER_ROLE_REQUIRED"
    assert deny_events[0]["details"]["requiredRoles"] == ["data-steward"]
    assert deny_events[0]["details"]["providedRoles"] == ["auditor"]

    try:
        authorize_action(cfg, "missing.policy")
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization policy missing: missing.policy"
    else:
        raise AssertionError("unknown high-risk action must fail closed")


def test_remote_runner_action_authorization_allows_matching_role(tmp_path) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("data-steward",),
    )

    principal = authorize_action(cfg, "database.create")

    assert principal.actor == "remote-runner-api"
    assert principal.roles == ("data-steward",)


def test_database_mutation_route_denies_role_without_side_effect_or_secret_leak(
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "runner.json"
    payload = {
        "token": "rbac-token",
        "api_token_roles": ["auditor"],
        "data_root": str(tmp_path / "shared"),
        "db_path": str(tmp_path / "shared" / "data" / "runner.db"),
        "uploads_dir": str(tmp_path / "shared" / "uploads"),
        "results_dir": str(tmp_path / "shared" / "results"),
        "work_dir": str(tmp_path / "shared" / "work"),
        "logs_dir": str(tmp_path / "shared" / "logs"),
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    ensure_runtime_layout(cfg)

    response = TestClient(app).post(
        "/api/v1/databases",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "id": "db_denied",
            "name": "Denied DB",
            "templateId": "kraken2",
            "path": str(tmp_path / "kraken2-mini"),
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    assert list_reference_databases(cfg) == []
    events = list_governance_audit_events(cfg, action="database.create")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["subjectKind"] == "database"
    assert events[0]["subjectId"] == "authorization"
    assert "authorization" not in json.dumps(events[0]["details"]).lower()
    assert "rbac-token" not in json.dumps(events[0], sort_keys=True)
