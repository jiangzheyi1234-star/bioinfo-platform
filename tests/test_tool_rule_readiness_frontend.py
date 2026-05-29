from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_frontend_uses_shared_rule_readiness_for_tools_and_workflow() -> None:
    helper = (COMPONENTS / "tool-rule-readiness.ts").read_text(encoding="utf-8")
    library = (COMPONENTS / "tools-page-library-section.tsx").read_text(encoding="utf-8")
    builder = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    model = (COMPONENTS / "generated-workflow-model.ts").read_text(encoding="utf-8")
    tools_state = (COMPONENTS / "use-tools-page-state.ts").read_text(encoding="utf-8")
    editor = (COMPONENTS / "tools-page-rule-spec-editor.tsx").read_text(encoding="utf-8")

    assert "export function ruleSpecReadinessForTool" in helper
    assert "export function executableRuleTemplateForTool" in helper
    assert "requiresUserCompletion === true" in helper
    assert 'kind: "workflow-ready"' in helper
    assert 'kind: "rule-draft"' in helper
    assert 'kind: "dependency-only"' in helper
    assert "outputsReady" in helper
    assert "mimeType" in helper
    assert "starterRuleTemplateForKnownTool" in helper
    assert "fastqc" in helper
    assert "可加入流程" in helper
    assert "待确认 RuleSpec" in helper
    assert "仅依赖" in helper

    assert "ruleSpecReadinessForTool" in library
    assert "state.label" in library

    assert "workflowReadyTools" in builder
    assert "ruleSpecReadinessForTool(tool).workflowReady" in builder
    assert "tools={workflowReadyTools}" in builder
    assert "没有可加入流程的工具" in builder

    assert "executableRuleTemplateForTool" in model
    assert "WORKFLOW_TOOL_NOT_READY" in model

    assert "withCuratedRuleTemplate" in tools_state
    assert "starterRuleTemplateForKnownTool" in editor
