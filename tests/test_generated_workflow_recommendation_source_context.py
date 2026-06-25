from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_recommended_tool_add_preserves_selected_source_output_context() -> None:
    recommendations = _source("generated-workflow-tool-recommendations.tsx")

    assert "onAddTool: (toolRevisionId: string, options?: GeneratedWorkflowAddStepOptions) => void" in recommendations
    assert "onAddTool(addStepRevisionId, {" in recommendations
    assert "preferredSourceOutput: {" in recommendations
    assert "output: selectedOutputCandidate.output" in recommendations
    assert "stepId: selectedOutputCandidate.stepId" in recommendations
    assert "targetInput: recommendation.inputPort.name" in recommendations


def test_builder_applies_preferred_source_output_only_after_compatibility_check() -> None:
    hook = _source("use-generated-workflow-builder.ts")

    assert "export type GeneratedWorkflowPreferredSourceOutput" in hook
    assert "preferredSourceOutput?: GeneratedWorkflowPreferredSourceOutput" in hook
    assert "preferredSourceOutput: options.preferredSourceOutput" in hook
    assert "applyPreferredSourceOutputBinding({" in hook
    assert "const sourceStep = upstreamSteps.find" in hook
    assert "const sourceOutput = readRuleOutputs" in hook
    assert "const targetInputs = readRuleInputs" in hook
    assert "const targetInput = targetInputs.find((input) => portsCompatible(input, sourceOutput))" in hook
    assert "audit: autoEdgeAudit(explainPortRecommendation(targetInput, sourceOutput))" in hook


def test_page_state_keeps_recommendation_source_context_across_tool_refresh() -> None:
    page_state = _source("use-workflows-page-state.ts")

    assert "type GeneratedWorkflowAddStepOptions" in page_state
    assert "const [pendingRecommendedTool, setPendingRecommendedTool]" in page_state
    assert "options: GeneratedWorkflowAddStepOptions = {}" in page_state
    assert "generatedBuilder.addStep(toolRevisionId, options)" in page_state
    assert "setPendingRecommendedTool({ options, toolRevisionId: normalizedRevisionId })" in page_state
    assert "generatedBuilder.addStep(toolRevisionId, pendingRecommendedTool?.options)" in page_state
