from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_artifact_cache_frontend_api_uses_governed_reads_and_ignores_mutation_rows() -> None:
    api = _read(WEB_COMPONENTS / "workflow-artifact-cache-api.ts")
    retain_block = _between(
        api,
        "export async function retainArtifactCacheEntry",
        "export async function releaseArtifactCachePolicyPin",
    )
    release_block = _between(
        api,
        "export async function releaseArtifactCachePolicyPin",
        "function artifactCacheQuery",
    )

    assert "fetchArtifactCacheEntries" in api
    assert "fetchArtifactCachePins" in api
    assert "retainArtifactCacheEntry" in api
    assert "releaseArtifactCachePolicyPin" in api
    assert "/api/v1/artifacts/cache/entries" in api
    assert "/api/v1/artifacts/cache/pins" in api
    assert "/retain" in api
    assert "/release" in api
    assert 'confirmation: request.confirmation.trim()' in api
    assert "invalidateAsyncCachePrefix(ARTIFACT_CACHE_ENTRIES_CACHE)" in api
    assert "invalidateAsyncCachePrefix(ARTIFACT_CACHE_PINS_CACHE)" in api
    assert "return response.data" not in retain_block
    assert "return response.data" not in release_block
    assert "const response" not in retain_block
    assert "const response" not in release_block


def test_artifact_cache_frontend_models_only_public_projection_fields() -> None:
    model = _read(WEB_COMPONENTS / "workflow-artifact-cache-model.ts")
    panel = _read(WEB_COMPONENTS / "workflow-artifact-cache-panel.tsx")
    controller = _read(WEB_COMPONENTS / "workflow-artifact-cache-controller.tsx")

    assert "WorkflowArtifactCacheEntry" in model
    assert "WorkflowArtifactCachePin" in model
    assert "cacheKeyFingerprint?: string" in model
    assert "workflowRevisionFingerprint?: string" in model
    assert "sha256?: string" in model
    assert "storageBackend?: string" in model
    assert "lifecycleState?: string" in model
    assert "pinScope?: string" in model
    assert "ownerKind?: string" in model
    assert "ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION" in model
    assert "cacheKeyFingerprint" in panel
    assert "workflowRevisionFingerprint" in panel
    assert "WorkflowArtifactCachePanel" in controller

    forbidden = {
        "cacheKey",
        "keyPayload",
        "workflowRevisionId",
        "artifactKey",
        "stepId",
        "storageUri",
        "path",
        "localPath",
        "externalUri",
        "packagePath",
        "packageUri",
    }
    assert not forbidden.intersection(_tokens(model))
    assert not forbidden.intersection(_tokens(panel))
    assert not forbidden.intersection(_tokens(controller))


def test_artifact_cache_panel_gates_policy_pin_release_and_refreshes_lifecycle() -> None:
    model = _read(WEB_COMPONENTS / "workflow-artifact-cache-model.ts")
    panel = _read(WEB_COMPONENTS / "workflow-artifact-cache-panel.tsx")
    controller = _read(WEB_COMPONENTS / "workflow-artifact-cache-controller.tsx")
    page = _read(WEB_COMPONENTS / "workflow-artifact-lifecycle-page.tsx")

    assert "pins.filter(isActivePolicyPin)" in panel
    assert 'pinItem.pinScope === "policy"' in panel
    assert 'pinItem.ownerKind === "operator"' in panel
    assert 'pinItem.state === "active"' in panel
    assert "releaseConfirmation.trim() !== ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION" in panel
    assert "release-artifact-cache-policy-pin" in model
    assert "保留缓存" in panel
    assert "释放 policy pin" in panel
    assert "onPolicyChanged" in controller
    assert "await Promise.all([load(true), onPolicyChanged()])" in controller
    assert "reloadAfterCachePolicyChange" in page
    assert "clearSavedPreview()" in page
    assert "WorkflowArtifactCacheController" in page
    assert "refreshVersion={cacheRefreshVersion}" in page


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index + len(start))
    return source[start_index:end_index]


def _tokens(source: str) -> set[str]:
    return set(
        source.replace('"', " ")
        .replace("'", " ")
        .replace("`", " ")
        .replace(":", " ")
        .replace("?", " ")
        .replace(";", " ")
        .replace(",", " ")
        .replace(".", " ")
        .split()
    )
