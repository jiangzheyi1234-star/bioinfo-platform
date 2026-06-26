from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_workflow_production_governance_panel_reads_service_info_readiness() -> None:
    api = _source("workflow-service-info-api.ts")
    model = _source("workflow-service-info-model.ts")
    panel = _source("workflow-production-governance-panel.tsx")
    page = _source("workflows-page.tsx")

    assert "export type WorkflowProductionGovernanceReadiness" in model
    assert "export type WorkflowProductionGovernanceCheck" in model
    assert "productionGovernance?: WorkflowProductionGovernanceReadiness" in model
    assert "publicMultiUserReady?: boolean" in model
    assert "publicMultiUserBlockingCheckIds?: string[]" in model
    assert "currentModeBlockingCheckIds?: string[]" in model
    assert "details?:" not in model
    assert "summary?:" not in model
    assert "securityWarnings" not in model
    assert "credentialStorage" not in model
    assert "stateCounts" not in model
    assert "identity" not in model

    assert "export async function fetchWorkflowServiceInfo" in api
    assert "WORKFLOW_SERVICE_INFO_CACHE_KEY" in api
    assert '"/api/v1/service-info"' in api
    assert '"GET"' in api
    assert "{ cache: \"no-store\" }" in api
    assert "response.item" in api
    assert "normalizeWorkflowServiceInfo(response.item)" in api
    assert "normalizeProductionGovernanceCheck" in api
    assert "stringList(check.evidence)" in api
    assert "return response.item" not in api
    assert '"POST"' not in api
    assert '"PUT"' not in api
    assert '"PATCH"' not in api
    assert '"DELETE"' not in api

    assert "export function WorkflowProductionGovernancePanel" in panel
    assert "fetchWorkflowServiceInfo({ forceRefresh })" in panel
    assert "productionGovernanceSummary(governance)" in panel
    assert "publicMultiUserBlockingCheckIds" in panel
    assert "currentModeStatus" in panel
    assert "publicMultiUserStatus" in panel
    assert "WorkflowProductionGovernancePanel" in page


def test_workflow_production_governance_panel_is_redacted_and_read_only() -> None:
    panel = _source("workflow-production-governance-panel.tsx")
    model = _source("workflow-service-info-model.ts")

    assert ".details" not in panel
    assert "check.details" not in panel
    assert ".summary" not in panel
    assert "check.summary" not in panel
    assert "securityWarnings" not in panel
    assert "credentialStorage" not in panel
    assert "stateCounts" not in panel
    assert "identity" not in panel
    assert "rawSecret" not in model
    assert "secretRef" not in model

    forbidden_tokens = {
        "H2OMETA_RUNNER_TOKEN",
        "H2OMETA_DATABASE_URL",
        "DATABASE_URL",
        "H2OMETA_ARTIFACT_S3_ENDPOINT",
        "H2OMETA_ARTIFACT_S3_BUCKET",
        "H2OMETA_ARTIFACT_S3_ACCESS_KEY",
        "H2OMETA_ARTIFACT_S3_SECRET_KEY",
        "databaseUrl",
        "accessKey",
        "secretKey",
        "bucketName",
        "endpointUrl",
    }
    assert not forbidden_tokens.intersection(_tokens(model))
    assert not forbidden_tokens.intersection(_tokens(panel))


def _tokens(source: str) -> set[str]:
    return set(source.replace('"', " ").replace("'", " ").replace("`", " ").split())
