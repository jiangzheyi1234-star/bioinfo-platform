from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRST_RUN_COMPONENTS = ROOT / "apps" / "web" / "app" / "workflows" / "first-run" / "_components"


def test_first_run_requires_visible_finalize_action() -> None:
    page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    validation = (FIRST_RUN_COMPONENTS / "workflow-first-run-validation.tsx").read_text(encoding="utf-8")

    assert "autoFinalizeFirstRunRef" not in page
    assert 'firstRunNextActionCode !== "FINALIZE_FIRST_RUN"' not in page
    assert "onFinalize" in page
    assert "await finalizeAndRefreshStatus();" in page
    assert "onFinalize={() => void finalizeAndRefreshStatus()}" in page

    assert 'data-testid="first-run-finalize"' in validation
    assert "完成首跑" in validation
