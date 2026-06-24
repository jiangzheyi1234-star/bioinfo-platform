from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.remote_runner import route_utils
from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import list_reference_databases
from apps.remote_runner.errors import RemoteRunnerAuthorizationError
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.route_utils import authorize_action
from apps.remote_runner.sqlite_migrations import SCHEMA_LEDGER_CHECKSUM_ERROR, RemoteRunnerSQLiteSchemaError
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


def test_remote_runner_authorization_denial_stays_403_when_audit_ledger_is_missing(tmp_path) -> None:
    cfg = RemoteRunnerConfig(
        token="rbac-token",
        api_token_roles=("auditor",),
        db_path=str(tmp_path / "missing" / "runner.db"),
    )

    try:
        authorize_action(cfg, "database.create")
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError("authorization denial must not depend on an initialized audit ledger")


def test_database_mutation_route_denies_role_when_audit_ledger_is_missing(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "missing" / "runner.db"
    config_path = tmp_path / "runner.json"
    config_path.write_text(
        json.dumps(
            {
                "token": "rbac-token",
                "api_token_roles": ["auditor"],
                "data_root": str(tmp_path / "shared"),
                "db_path": str(db_path),
                "uploads_dir": str(tmp_path / "shared" / "uploads"),
                "results_dir": str(tmp_path / "shared" / "results"),
                "work_dir": str(tmp_path / "shared" / "work"),
                "logs_dir": str(tmp_path / "shared" / "logs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("H2OMETA_REMOTE_CONFIG", str(config_path))

    response = TestClient(app).post(
        "/api/v1/databases",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "id": "db_denied_missing_ledger",
            "name": "Denied Missing Ledger DB",
            "templateId": "kraken2",
            "path": str(tmp_path / "kraken2-mini"),
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    assert not db_path.exists()
    assert "rbac-token" not in json.dumps(response.json(), sort_keys=True)


def test_authorization_denial_does_not_hide_audit_integrity_errors(tmp_path, monkeypatch) -> None:
    cfg = RemoteRunnerConfig(
        token="rbac-token",
        api_token_roles=("auditor",),
        db_path=str(tmp_path / "runner.db"),
    )

    def fail_audit_record(*_args, **_kwargs) -> None:
        raise RemoteRunnerSQLiteSchemaError(SCHEMA_LEDGER_CHECKSUM_ERROR)

    monkeypatch.setattr(route_utils, "record_governance_audit_event", fail_audit_record)

    try:
        authorize_action(cfg, "database.create")
    except RemoteRunnerSQLiteSchemaError as exc:
        assert str(exc) == SCHEMA_LEDGER_CHECKSUM_ERROR
    else:
        raise AssertionError("audit integrity failures must not be hidden behind authorization denial")


def test_remote_runner_action_authorization_allows_matching_role(tmp_path) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("data-steward",),
    )

    principal = authorize_action(cfg, "database.create")

    assert principal.actor == "remote-runner-api"
    assert principal.roles == ("data-steward",)


def test_inbox_replay_action_uses_workflow_operator_role(tmp_path) -> None:
    denied = make_configured_remote_runner(
        tmp_path / "denied",
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    allowed = make_configured_remote_runner(
        tmp_path / "allowed",
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )

    try:
        authorize_action(denied, "workflow_trigger.inbox_replay")
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError("workflow_trigger.inbox_replay must require workflow-operator")

    deny_events = list_governance_audit_events(denied, action="workflow_trigger.inbox_replay")["items"]
    assert deny_events[0]["decision"] == "deny"
    assert deny_events[0]["details"]["requiredRoles"] == ["workflow-operator"]
    assert authorize_action(allowed, "workflow_trigger.inbox_replay").roles == ("workflow-operator",)


def test_result_package_retire_action_uses_artifact_curator_role(tmp_path) -> None:
    denied = make_configured_remote_runner(
        tmp_path / "denied",
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    allowed = make_configured_remote_runner(
        tmp_path / "allowed",
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )

    try:
        authorize_action(denied, "result.package.retire")
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError("result.package.retire must require artifact-curator")

    deny_events = list_governance_audit_events(denied, action="result.package.retire")["items"]
    assert deny_events[0]["decision"] == "deny"
    assert deny_events[0]["details"]["requiredRoles"] == ["artifact-curator"]
    assert authorize_action(allowed, "result.package.retire").roles == ("artifact-curator",)


def test_result_package_byte_delete_action_uses_artifact_curator_role(tmp_path) -> None:
    denied = make_configured_remote_runner(
        tmp_path / "denied",
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    allowed = make_configured_remote_runner(
        tmp_path / "allowed",
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )

    try:
        authorize_action(denied, "result.package.bytes.delete")
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError("result.package.bytes.delete must require artifact-curator")

    deny_events = list_governance_audit_events(denied, action="result.package.bytes.delete")["items"]
    assert deny_events[0]["decision"] == "deny"
    assert deny_events[0]["details"]["requiredRoles"] == ["artifact-curator"]
    assert authorize_action(allowed, "result.package.bytes.delete").roles == ("artifact-curator",)


def test_result_package_list_action_allows_auditor_and_artifact_curator_roles(tmp_path) -> None:
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

    try:
        authorize_action(denied, "result.package.list")
    except RemoteRunnerAuthorizationError as exc:
        assert str(exc) == "runner authorization failed"
    else:
        raise AssertionError("result.package.list must require auditor or artifact-curator")

    deny_events = list_governance_audit_events(denied, action="result.package.list")["items"]
    assert deny_events[0]["decision"] == "deny"
    assert deny_events[0]["details"]["requiredRoles"] == ["artifact-curator", "auditor"]
    assert authorize_action(auditor, "result.package.list").roles == ("auditor",)
    assert authorize_action(curator, "result.package.list").roles == ("artifact-curator",)


def test_governance_audit_read_route_requires_auditor_role(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    response = TestClient(app).get(
        "/api/v1/audit/events",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    events = list_governance_audit_events(cfg, action="audit.events.read")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["subjectKind"] == "governance_audit"
    assert events[0]["details"]["requiredRoles"] == ["auditor", "platform-admin"]
    assert events[0]["details"]["providedRoles"] == ["workflow-operator"]


def test_governance_audit_read_route_allows_auditor_role(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    response = TestClient(app).get(
        "/api/v1/audit/events",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


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
