from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.remote_runner import artifact_cache_read_service
from apps.remote_runner import control_service
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
    assert deny_events[0]["actorRoles"] == ["auditor"]

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
    assert deny_events[0]["actorRoles"] == ["auditor"]
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


def test_result_preview_and_artifact_audit_actions_allow_auditor_and_artifact_curator_roles(tmp_path) -> None:
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

    for action in ("result.artifact.preview", "result.artifact_audit.read"):
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


def test_artifact_cache_read_actions_allow_auditor_and_artifact_curator_roles(tmp_path) -> None:
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

    for action in ("artifact.cache.entries.read", "artifact.cache_pins.read", "artifact.cache.lookup"):
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


def test_artifact_cache_lookup_route_denies_wrong_role_before_cache_read(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_cache_read(*_args, **_kwargs):
        raise AssertionError("cache lookup must not run before authorization")

    monkeypatch.setattr(control_service, "lookup_governed_artifact_cache_entry", fail_cache_read)

    response = TestClient(app).post(
        "/api/v1/artifacts/cache/lookup",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "workflowRevisionId": "wrev_denied",
            "artifactKey": "report",
            "role": "output",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    events = list_governance_audit_events(cfg, action="artifact.cache.lookup")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["subjectKind"] == "artifact_cache"
    assert events[0]["subjectId"] == "authorization"


def test_artifact_cache_read_routes_record_safe_allow_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(
        artifact_cache_read_service,
        "list_artifact_cache_entries",
        lambda *_args, **_kwargs: {
            "items": [
                {
                    "cacheEntryId": "ace_public",
                    "cacheKey": "acache_public",
                    "artifactBlobId": "ablob_public",
                    "storageBackend": "local",
                    "storageUri": "file:///C:/secret/cache/report.txt",
                    "sha256": "c" * 64,
                }
            ]
        },
    )
    monkeypatch.setattr(
        artifact_cache_read_service,
        "list_artifact_cache_policy_pins",
        lambda *_args, **_kwargs: {
            "items": [
                {
                    "cachePinId": "acpin_public",
                    "cacheEntryId": "ace_public",
                    "cacheKey": "acache_public",
                    "artifactBlobId": "ablob_public",
                    "storageBackend": "local",
                    "storageUri": "file:///C:/secret/cache/report.txt",
                    "sha256": "c" * 64,
                    "state": "active",
                }
            ]
        },
    )
    monkeypatch.setattr(
        artifact_cache_read_service,
        "lookup_artifact_cache_entry",
        lambda *_args, **_kwargs: {
            "cacheKey": "acache_lookup",
            "keyPayload": {"workflowRevisionId": "wrev_secret_lookup", "artifactKey": "cache_secret_selector"},
            "hit": True,
            "reason": "hit",
            "entry": {
                "cacheEntryId": "ace_lookup",
                "cacheKey": "acache_lookup",
                "artifactBlobId": "ablob_lookup",
                "storageBackend": "local",
                "storageUri": "file:///C:/secret/cache/report.txt",
                "sha256": "d" * 64,
            },
            "evidenceId": "evt_lookup",
            "lookedUpAt": "2099-06-07T10:00:00Z",
        },
    )

    entries_response = TestClient(app).get(
        "/api/v1/artifacts/cache/entries?workflowRevisionId=wrev_secret_filter&limit=25",
        headers={"Authorization": "Bearer rbac-token"},
    )
    pins_response = TestClient(app).get(
        "/api/v1/artifacts/cache/pins?cacheEntryId=ace_secret_filter&state=active&limit=5",
        headers={"Authorization": "Bearer rbac-token"},
    )
    lookup_response = TestClient(app).post(
        "/api/v1/artifacts/cache/lookup",
        headers={"Authorization": "Bearer rbac-token"},
        json={
            "workflowRevisionId": "wrev_secret_lookup",
            "artifactKey": "cache_secret_selector",
            "stepId": "step_secret_selector",
            "role": "output",
            "inputs": [{"name": "reads"}],
            "params": {"mode": "strict"},
            "resourceBindings": {"database": "masked"},
            "execution": {"threads": 1},
        },
    )

    assert entries_response.status_code == 200
    assert pins_response.status_code == 200
    assert lookup_response.status_code == 200
    assert "storageUri" not in entries_response.json()["data"]["items"][0]
    assert "storageUri" not in pins_response.json()["data"]["items"][0]
    assert "storageUri" not in lookup_response.json()["data"]["entry"]
    assert lookup_response.json()["data"]["hit"] is True

    entries_audit = list_governance_audit_events(cfg, action="artifact.cache.entries.read")["items"]
    pins_audit = list_governance_audit_events(cfg, action="artifact.cache_pins.read")["items"]
    lookup_audit = list_governance_audit_events(cfg, action="artifact.cache.lookup")["items"]
    assert entries_audit[-1]["details"] == {
        "filteredByWorkflowRevision": True,
        "limit": 25,
        "returnedCount": 1,
    }
    assert pins_audit[-1]["details"] == {
        "filteredByCacheEntry": True,
        "filteredByState": True,
        "limit": 5,
        "returnedCount": 1,
    }
    assert lookup_audit[-1]["details"] == {
        "hit": True,
        "reason": "hit",
        "workflowRevisionProvided": True,
        "selectorProvided": True,
        "stepSelectorProvided": True,
        "inputCount": 1,
        "hasParams": True,
        "hasResourceBindings": True,
        "hasExecutionOptions": True,
        "lookupEvidenceRecorded": True,
    }
    serialized = json.dumps(entries_audit + pins_audit + lookup_audit, sort_keys=True)
    public_payload = json.dumps(
        [entries_response.json(), pins_response.json(), lookup_response.json()],
        sort_keys=True,
    )
    assert "wrev_secret_filter" not in serialized
    assert "ace_secret_filter" not in serialized
    assert "wrev_secret_lookup" not in serialized
    assert "cache_secret_selector" not in serialized
    assert "step_secret_selector" not in serialized
    assert "file:///C:/secret" not in serialized
    assert "file:///C:/secret" not in public_payload
    assert "rbac-token" not in serialized


def test_result_preview_route_denies_wrong_role_before_payload_read(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def fail_preview_read(*_args, **_kwargs):
        raise AssertionError("preview payload read must not run before authorization")

    monkeypatch.setattr(control_service, "build_result_preview_data", fail_preview_read)

    response = TestClient(app).get(
        "/api/v1/results/res_denied/preview",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "runner authorization failed"
    events = list_governance_audit_events(cfg, action="result.artifact.preview")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "deny"
    assert events[0]["subjectKind"] == "result_artifact"
    assert events[0]["subjectId"] == "authorization"


def test_result_preview_route_records_safe_allow_audit(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def preview_payload(_cfg, result_id, artifact_id=None):
        assert result_id == "res_preview"
        assert artifact_id == "art_report"
        return {
            "resultId": "res_preview",
            "artifactId": "art_report",
            "artifact": {
                "artifactId": "art_report",
                "kind": "report",
                "mimeType": "text/plain",
                "sizeBytes": 11,
                "sha256": "a" * 64,
                "path": "C:/secret/report.txt",
                "storageUri": "file:///C:/secret/report.txt",
            },
            "preview": {"kind": "text", "content": "secret body", "truncated": False},
        }

    monkeypatch.setattr(control_service, "build_result_preview_data", preview_payload)

    response = TestClient(app).get(
        "/api/v1/results/res_preview/preview?artifact_id=art_report",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 200
    response_data = response.json()["data"]
    assert response_data["preview"]["content"] == "secret body"
    assert "path" not in response_data["artifact"]
    assert "storageUri" not in response_data["artifact"]
    events = list_governance_audit_events(cfg, action="result.artifact.preview")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "allow"
    assert events[0]["subjectKind"] == "result_artifact"
    assert events[0]["subjectId"] == "art_report"
    assert events[0]["actorRoles"] == ["auditor"]
    assert events[0]["details"] == {
        "resultId": "res_preview",
        "artifactId": "art_report",
        "artifactKind": "report",
        "mimeType": "text/plain",
        "sizeBytes": 11,
        "sha256": "a" * 64,
        "previewKind": "text",
        "truncated": False,
    }
    serialized = json.dumps(events[0], sort_keys=True)
    assert "secret body" not in serialized
    assert "C:/secret" not in serialized
    assert "storageUri" not in serialized
    assert "rbac-token" not in serialized


def test_result_artifact_audit_route_records_safe_allow_audit_and_redacts_public_payload(
    tmp_path,
    monkeypatch,
) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("artifact-curator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    def audit_payload(_cfg, result_id):
        assert result_id == "res_audit"
        return {
            "resultId": "res_audit",
            "runId": "run_audit",
            "verificationMode": "payload-checksum",
            "status": "passed",
            "checkedAt": "2099-06-07T10:00:00Z",
            "artifactCount": 1,
            "failedCount": 0,
            "artifacts": [
                {
                    "artifactId": "art_report",
                    "status": "passed",
                    "path": "C:/secret/report.txt",
                    "storageUri": "file:///C:/secret/report.txt",
                    "sha256": "b" * 64,
                }
            ],
        }

    monkeypatch.setattr(control_service, "build_result_artifact_audit", audit_payload)

    response = TestClient(app).get(
        "/api/v1/results/res_audit/audit",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 200
    public_artifact = response.json()["data"]["artifacts"][0]
    assert "path" not in public_artifact
    assert "storageUri" not in public_artifact
    events = list_governance_audit_events(cfg, action="result.artifact_audit.read")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "allow"
    assert events[0]["subjectKind"] == "result_artifact_audit"
    assert events[0]["subjectId"] == "res_audit"
    assert events[0]["actorRoles"] == ["artifact-curator"]
    assert events[0]["details"] == {
        "resultId": "res_audit",
        "runId": "run_audit",
        "verificationMode": "payload-checksum",
        "status": "passed",
        "artifactCount": 1,
        "failedCount": 0,
    }
    serialized = json.dumps(events[0], sort_keys=True)
    assert "C:/secret" not in serialized
    assert "storageUri" not in serialized
    assert "rbac-token" not in serialized


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
    events = list_governance_audit_events(cfg, action="audit.events.read")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "allow"
    assert events[0]["subjectKind"] == "governance_audit"
    assert events[0]["subjectId"] == "query"
    assert events[0]["actorRoles"] == ["auditor"]
    assert events[0]["details"] == {
        "filteredBySubjectKind": False,
        "filteredBySubjectId": False,
        "filteredByAction": False,
        "limit": 100,
        "returnedCount": 0,
    }
    assert "rbac-token" not in json.dumps(events[0], sort_keys=True)


def test_governance_audit_read_allow_event_redacts_raw_filters(tmp_path, monkeypatch) -> None:
    cfg = make_configured_remote_runner(
        tmp_path,
        token="rbac-token",
        api_token_roles=("platform-admin",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: cfg)

    response = TestClient(app).get(
        "/api/v1/audit/events"
        "?subjectKind=run&subjectId=canary_secret_filter_value&action=database.create&limit=25",
        headers={"Authorization": "Bearer rbac-token"},
    )

    assert response.status_code == 200
    events = list_governance_audit_events(cfg, action="audit.events.read")["items"]
    assert len(events) == 1
    assert events[0]["decision"] == "allow"
    assert events[0]["actorRoles"] == ["platform-admin"]
    assert events[0]["details"] == {
        "filteredBySubjectKind": True,
        "filteredBySubjectId": True,
        "filteredByAction": True,
        "limit": 25,
        "returnedCount": 0,
    }
    serialized = json.dumps(events[0], sort_keys=True)
    assert "canary_secret_filter_value" not in serialized
    assert "database.create" not in serialized
    assert "rbac-token" not in serialized


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
