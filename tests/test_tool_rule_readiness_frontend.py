from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_frontend_uses_shared_rule_readiness_for_tools_and_workflow() -> None:
    helper = (COMPONENTS / "tool-rule-readiness.ts").read_text(encoding="utf-8")
    tools_model = (COMPONENTS / "tools-page-model.ts").read_text(encoding="utf-8")
    completion = (COMPONENTS / "tools-page-rule-spec-completion.ts").read_text(encoding="utf-8")
    library = (COMPONENTS / "tools-page-library-section.tsx").read_text(encoding="utf-8")
    builder = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    workflow_model = (COMPONENTS / "generated-workflow-model.ts").read_text(encoding="utf-8")
    tools_state = (COMPONENTS / "use-tools-page-state.ts").read_text(encoding="utf-8")
    editor = (COMPONENTS / "tools-page-rule-spec-editor.tsx").read_text(encoding="utf-8")

    assert "export function ruleSpecReadinessForTool" in helper
    assert "export function executableRuleTemplateForTool" in helper
    assert "requiresUserCompletion === true" in helper
    assert 'kind: "workflow-ready"' in helper
    assert 'kind: "validation-pending"' in helper
    assert 'kind: "rule-draft"' in helper
    assert 'kind: "dependency-only"' in helper
    assert "outputsReady" in helper
    assert "paramsReady" in helper
    assert "ruleRuntimeReady" in helper
    assert "runtimeLabel" in helper
    assert "待补 runtime/log" in helper
    assert "smokeTestReady" in helper
    assert "input.required !== false" in helper
    assert "smokeLabel" in helper
    assert "待补 smoke" in helper
    assert "wrapperRefLocked" in helper
    assert "待锁 wrapper" in helper
    assert "dependencyLocked" in helper
    assert "channelPriorityStrict" in helper
    assert "待锁 env" in helper
    assert "mimeType" not in helper
    assert "demoqc" not in helper
    assert "可加入流程" in helper
    assert "待验证" in helper
    assert "待确认 RuleSpec" in helper
    assert "仅依赖" in helper
    assert "tool.toolContract?.workflowReady" in helper
    assert "contractWorkflowReady === undefined ? localWorkflowReady" not in helper
    assert "Boolean(contractWorkflowReady && localWorkflowReady)" in helper
    assert "missingRuleSpecFields" in tools_model
    assert "isExecutableRuleSpec" in tools_model
    assert "buildExecutableRuleSpecForSelectedTool" in tools_model
    assert "applySelectedWrapperLock" in tools_model
    assert "params:" in completion
    assert "smokeTest" in completion
    assert "environment" in completion
    assert "RuleSpec 需要补全并确认" in completion
    assert "canAutoConfirmRuleSpec" in completion
    assert "outputPathSpecified" in completion

    assert "ruleSpecReadinessForTool" in library
    assert "state.label" in library
    assert "验证工具" in library
    assert "ToolContractStatusRow" in library
    assert 'label="Production"' in library
    assert "validation.production" in library

    assert "workflowReadyTools" in builder
    assert "ruleSpecReadinessForTool(tool).workflowReady" in builder
    assert "tools={workflowReadyTools}" in builder
    assert "没有可加入流程的工具" in builder

    assert "executableRuleTemplateForTool" in workflow_model
    assert "WORKFLOW_TOOL_NOT_READY" in workflow_model

    assert "canSaveSelected" in tools_state
    assert "canValidateSelected" not in tools_state
    assert "addToolDependency(nextTool)" in tools_state
    assert "createToolPrepareJob(nextTool)" in tools_state
    assert "mem_mb" in editor
    assert "log:" in editor
