from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
WEB_ROUTES = ROOT / "apps" / "web" / "app" / "workflows" / "results"


def test_artifact_lifecycle_frontend_surface_is_confirmation_gated_gc() -> None:
    api = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-api.ts")
    page = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-page.tsx")
    controller_panel = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-controller-panel.tsx")
    package_byte_gc_panel = _read(WEB_COMPONENTS / "workflow-result-package-byte-gc-panel.tsx")

    assert "fetchArtifactLifecycleUsage" in api
    assert "fetchArtifactLifecycleControllerTicks" in api
    assert "runArtifactLifecycleControllerOnce" in api
    assert "previewArtifactGc" in api
    assert "runArtifactGc" in api
    assert "previewResultPackageByteGc" in api
    assert "runResultPackageByteGc" in api
    assert "/api/v1/artifacts/lifecycle/usage" in api
    assert "/api/v1/artifacts/lifecycle/controller/ticks" in api
    assert "/api/v1/artifacts/lifecycle/controller/run-once" in api
    assert "/api/v1/artifacts/lifecycle/gc/preview" in api
    assert "/api/v1/artifacts/lifecycle/gc/run" in api
    assert "/api/v1/result-package-exports/bytes/gc/preview" in api
    assert "/api/v1/result-package-exports/bytes/gc/run" in api
    assert "WorkflowArtifactLifecycleControllerRunOnceResponse" in api
    assert 'confirmation: "run-artifact-lifecycle-controller-once"' in api
    assert "invalidateAsyncCachePrefix(ARTIFACT_LIFECYCLE_TICKS_CACHE_KEY)" in api
    assert "WorkflowArtifactGcRunRequest" in api
    assert "WorkflowArtifactGcRunResult" in api
    assert "WorkflowResultPackageByteGcRunRequest" in api
    assert "WorkflowResultPackageByteGcRunResult" in api
    assert "response.data" in api

    assert 'GC_RUN_CONFIRMATION = "delete-artifact-payloads"' in page
    assert "planFingerprint: preview.planFingerprint" in page
    assert "...previewRequest" in page
    assert "setPreviewRequest(request)" in page
    assert "clearSavedPreview" in page
    assert "confirmationValue.trim() === GC_RUN_CONFIRMATION" in page
    assert "disabled={!canRun}" in page
    assert "CONTROLLER_PREVIEW_REASON" in page
    assert "previewRequestFromControllerTick" in page
    assert "controllerTickCanPreviewPolicy" in page
    assert "maxDeleteBytesPerTick" in page
    assert "WorkflowArtifactLifecycleControllerPanel" in page
    assert "WorkflowResultPackageByteGcPanel" in page
    assert "onRunComplete={refresh}" in page
    assert "runArtifactLifecycleControllerOnce" in page
    assert "controllerRunning" in page
    assert "onRunControllerOnce={() => void runControllerOnce()}" in page
    assert "previewArtifactGc(request)" in page
    assert "planFingerprint: tick.gcPreview" not in page
    assert "planFingerprint: tick.policy" not in page
    assert "CONTROLLER_RUN_ONCE_CONFIRMATION" in controller_panel
    assert "run-artifact-lifecycle-controller-once" in controller_panel
    assert "运行一次 controller" in controller_panel
    assert "确认运行 controller" in controller_panel
    assert "preview-only artifact lifecycle controller tick" in controller_panel
    assert "不会删除产物 payload" in controller_panel
    assert "disabled={confirmation.trim() !== CONTROLLER_RUN_ONCE_CONFIRMATION || runningController}" in controller_panel
    assert 'RESULT_PACKAGE_BYTE_GC_CONFIRMATION = "run-result-package-byte-gc"' in package_byte_gc_panel
    assert "previewResultPackageByteGc(request)" in package_byte_gc_panel
    assert "runResultPackageByteGc({" in package_byte_gc_panel
    assert "...previewRequest" in package_byte_gc_panel
    assert "setPreviewRequest(request)" in package_byte_gc_panel
    assert "planFingerprint: preview.planFingerprint" in package_byte_gc_panel
    assert "confirmationValue.trim() === RESULT_PACKAGE_BYTE_GC_CONFIRMATION" in package_byte_gc_panel
    assert "disabled={!canRun}" in package_byte_gc_panel


def test_artifact_lifecycle_frontend_uses_public_projection_and_safe_preview_summary() -> None:
    model = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-model.ts")
    page = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-page.tsx")
    controller_panel = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-controller-panel.tsx")
    package_byte_gc_panel = _read(WEB_COMPONENTS / "workflow-result-package-byte-gc-panel.tsx")

    assert "WorkflowArtifactLifecycleUsage" in model
    assert "WorkflowArtifactLifecycleControllerTick" in model
    assert "WorkflowArtifactLifecycleControllerRunOnceResult" in model
    assert "WorkflowArtifactGcPlan" in model
    assert "WorkflowArtifactGcRunResult" in model
    assert "WorkflowResultPackageByteGcPlan" in model
    assert "WorkflowResultPackageByteGcRunResult" in model
    assert "planFingerprint?: string" in model
    assert "controlsExposed?: boolean" in model
    assert "deleteExecutionAuthorized?: boolean" in model
    assert "gcPreview" in page
    assert "WorkflowResultPackageByteGcPanel" in page
    assert "retentionHolds" in controller_panel
    assert "batchSafety" in controller_panel
    assert "shortFingerprint(tick.gcPreview?.planFingerprint)" in controller_panel
    assert "计划指纹" in controller_panel
    assert "reasonCounts" in package_byte_gc_panel
    assert "checksumVerified" in package_byte_gc_panel
    assert "activeStorageObjectCount" in page
    assert "quotaBytes" in page
    forbidden = {
        "storageUri",
        "localPath",
        "packagePath",
        "packageExportId",
        "groupId",
        "artifactIds",
        "runIds",
        "resultId",
        "runId",
        "materializationIds",
        "sha256",
    }
    assert not forbidden.intersection(_tokens(model))
    assert not forbidden.intersection(_tokens(page))
    assert not forbidden.intersection(_tokens(controller_panel))
    assert not forbidden.intersection(_tokens(package_byte_gc_panel))
    assert '"path"' not in model
    assert '"path"' not in page
    assert '"path"' not in controller_panel
    assert '"path"' not in package_byte_gc_panel


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
