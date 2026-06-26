from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.remote_runner import route_utils
from apps.remote_runner.governance_audit import list_governance_audit_events
from apps.remote_runner.main import app
from apps.remote_runner.secret_provider_readiness import build_secret_provider_readiness
from tests.helpers.reference_database import make_configured_remote_runner


def test_secret_provider_readiness_reports_provider_integration_without_ref_or_value_leak(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.remote_runner.secret_provider_readiness.keyring_secret_provider_available",
        lambda: False,
    )

    readiness = build_secret_provider_readiness()

    assert readiness["schemaVersion"] == "remote-runner-secret-provider-readiness.v1"
    assert readiness["supportedPurposes"] == ["webhook-signing-secret"]
    assert readiness["defaultWebhookProviderSchemes"] == ["env"]
    providers = {item["scheme"]: item for item in readiness["providers"]}
    assert providers["env"] == {
        "scheme": "env",
        "providerKind": "environment",
        "defaultForWebhookSigning": True,
        "state": "available",
        "reasonCode": "",
        "resolutionBoundary": "provider-integration",
    }
    for scheme in ("keyring", "secret", "vault"):
        assert providers[scheme]["state"] == "unconfigured"
        assert providers[scheme]["reasonCode"] == "SECRET_PROVIDER_UNAVAILABLE"
        assert providers[scheme]["resolutionBoundary"] == "fail-closed"
    assert readiness["redactionPolicy"] == {
        "rawReferencesExposed": False,
        "secretValuesExposed": False,
        "individualReferenceProbing": False,
    }
    serialized = json.dumps(readiness, sort_keys=True)
    assert "env://H2OMETA" not in serialized
    assert "secret://webhooks" not in serialized
    assert "vault://webhooks" not in serialized
    assert "github-secret" not in serialized


def test_secret_provider_readiness_marks_keyring_available_without_ref_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.remote_runner.secret_provider_readiness.keyring_secret_provider_available",
        lambda: True,
    )

    readiness = build_secret_provider_readiness()

    assert readiness["defaultWebhookProviderSchemes"] == ["env", "keyring"]
    providers = {item["scheme"]: item for item in readiness["providers"]}
    assert providers["keyring"] == {
        "scheme": "keyring",
        "providerKind": "os-keyring",
        "defaultForWebhookSigning": True,
        "state": "available",
        "reasonCode": "",
        "resolutionBoundary": "provider-integration",
    }
    assert readiness["redactionPolicy"]["individualReferenceProbing"] is False
    serialized = json.dumps(readiness, sort_keys=True)
    assert "keyring://webhooks" not in serialized
    assert "github-secret" not in serialized


def test_secret_provider_readiness_route_requires_auditor_role_and_records_safe_allow_audit(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.remote_runner.secret_provider_readiness.keyring_secret_provider_available",
        lambda: False,
    )
    denied = make_configured_remote_runner(
        tmp_path / "denied",
        token="secret-readiness-token",
        api_token_roles=("workflow-operator",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: denied)

    denied_response = TestClient(app).get(
        "/api/v1/secrets/provider-readiness",
        headers={"Authorization": "Bearer secret-readiness-token"},
    )

    assert denied_response.status_code == 403
    deny_events = list_governance_audit_events(denied, action="secret.provider_readiness.read")["items"]
    assert deny_events[-1]["decision"] == "deny"
    assert deny_events[-1]["subjectKind"] == "secret_provider"
    assert deny_events[-1]["details"]["requiredRoles"] == ["auditor", "platform-admin"]

    allowed = make_configured_remote_runner(
        tmp_path / "allowed",
        token="secret-readiness-token",
        api_token_roles=("auditor",),
    )
    monkeypatch.setattr(route_utils, "load_remote_runner_config", lambda: allowed)

    response = TestClient(app).get(
        "/api/v1/secrets/provider-readiness",
        headers={"Authorization": "Bearer secret-readiness-token"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["redactionPolicy"]["secretValuesExposed"] is False
    allow_events = list_governance_audit_events(allowed, action="secret.provider_readiness.read")["items"]
    assert allow_events[-1]["decision"] == "allow"
    assert allow_events[-1]["actorRoles"] == ["auditor"]
    assert allow_events[-1]["details"] == {
        "schemaVersion": "provider-readiness-audit.v1",
        "providerCount": 4,
        "configuredProviderCount": 1,
        "rawReferenceExposure": False,
        "valueExposure": False,
        "individualReferenceProbe": False,
    }
    serialized = json.dumps(allow_events[-1], sort_keys=True)
    assert "secret-readiness-token" not in serialized
    assert "env://H2OMETA" not in serialized
    assert "github-secret" not in serialized
