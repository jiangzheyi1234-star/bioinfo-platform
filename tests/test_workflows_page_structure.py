from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_workflows_page_uses_live_builder_modules() -> None:
    page = (COMPONENTS / "workflows-page.tsx").read_text(encoding="utf-8")
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    ui = (COMPONENTS / "workflows-page-ui.tsx").read_text(encoding="utf-8")

    assert "const workflowTemplates = [" not in page
    assert "requestLocalApiJson" not in page
    assert "useWorkflowsPageState" in page
    assert "fetchWorkflowTemplates" in api
    assert '"/api/v1/workflow-templates"' in api
    assert '"/api/v1/runs"' in api
    assert '"/api/v1/uploads"' in api
    assert '"/api/v1/servers"' in api
    assert "serverId" in api
    assert "contentBase64" in api
    assert "generated-tool-run-v1" in model
    assert "buildGeneratedRunSpec" in model
    assert "export function useWorkflowsPageState" in hook
    assert "export function WorkflowTemplateList" in ui
    assert "export function WorkflowRunBuilder" in ui
