from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRST_RUN_COMPONENTS = ROOT / "apps" / "web" / "app" / "workflows" / "first-run" / "_components"


def test_first_run_auto_finalizes_completed_official_run_once() -> None:
    page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    validation = (FIRST_RUN_COMPONENTS / "workflow-first-run-validation.tsx").read_text(encoding="utf-8")

    assert 'const autoFinalizeFirstRunRef = useRef("");' in page
    assert 'const firstRunStatusStage = firstRunStatusSnapshot?.stage || "";' in page
    assert 'const firstRunNextActionCode = firstRunStatusSnapshot?.nextAction?.code || "";' in page
    assert 'const firstRunNextActionBlockedCode = firstRunStatusSnapshot?.nextAction?.blockedCode || "";' in page
    assert "const finalizeKey = `${finalizedRunId}|${blockedCode}`;" in page
    assert 'firstRunStatusStage !== "export_result_package"' in page
    assert 'firstRunNextActionCode !== "FINALIZE_FIRST_RUN"' in page
    assert 'String(statusRun?.status || "").toLowerCase() === "completed"' in page
    assert "firstRunEvidence.finalizingFirstRun" in page
    assert "firstRunEvidence.validationReady" in page
    assert "autoFinalizeFirstRunRef.current === finalizeKey" in page
    assert "autoFinalizeFirstRunRef.current = finalizeKey" in page
    assert "void finalizeAndRefreshStatus();" in page

    assert 'data-testid="first-run-finalize"' in validation
    assert "完成首跑" in validation
