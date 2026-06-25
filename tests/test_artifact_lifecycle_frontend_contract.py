from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
WEB_ROUTES = ROOT / "apps" / "web" / "app" / "workflows" / "results"


def test_artifact_lifecycle_frontend_surface_is_read_only_preview() -> None:
    api = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-api.ts")
    page = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-page.tsx")

    assert "fetchArtifactLifecycleUsage" in api
    assert "fetchArtifactLifecycleControllerTicks" in api
    assert "previewArtifactGc" in api
    assert "/api/v1/artifacts/lifecycle/usage" in api
    assert "/api/v1/artifacts/lifecycle/controller/ticks" in api
    assert "/api/v1/artifacts/lifecycle/gc/preview" in api

    forbidden = {
        "runArtifactGc",
        "ARTIFACT_GC_CONFIRMATION",
        "delete-artifact-payloads",
        "/api/v1/artifacts/lifecycle/gc/run",
    }
    assert not forbidden.intersection(_tokens(api))
    assert not forbidden.intersection(_tokens(page))


def test_artifact_lifecycle_frontend_uses_public_projection_and_safe_preview_summary() -> None:
    model = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-model.ts")
    page = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-page.tsx")

    assert "WorkflowArtifactLifecycleUsage" in model
    assert "WorkflowArtifactLifecycleControllerTick" in model
    assert "WorkflowArtifactGcPlan" in model
    assert "retentionHolds" in page
    assert "batchSafety" in page
    assert "gcPreview" in page
    assert "activeStorageObjectCount" in page
    assert "quotaBytes" in page
    assert "storageUri" not in model
    assert "storageUri" not in page
    assert '"path"' not in model
    assert '"path"' not in page


def test_artifact_lifecycle_route_and_results_entry_exist() -> None:
    route = _read(WEB_ROUTES / "lifecycle" / "page.tsx")
    results_page = _read(WEB_COMPONENTS / "workflow-results-page.tsx")

    assert "WorkflowArtifactLifecyclePage" in route
    assert 'href="/workflows/results/lifecycle"' in results_page
    assert "fetchArtifactLifecycleUsage" in results_page
    assert "fetchArtifactLifecycleControllerTicks" in results_page


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tokens(source: str) -> set[str]:
    return set(source.replace('"', " ").replace("'", " ").replace("`", " ").split())
