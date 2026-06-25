from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_workflow_design_semantic_port_plan_is_rendered_from_backend_plan() -> None:
    builder = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    component = (COMPONENTS / "workflow-design-semantic-port-plan.tsx").read_text(encoding="utf-8")
    model = (COMPONENTS / "workflow-design-draft-model.ts").read_text(encoding="utf-8")

    assert "WorkflowDesignSemanticPortPlanPreview" in builder
    assert "plan={designPlan?.semanticPortPlan || null}" in builder
    assert "onInsertConverter={builder.insertConverter}" in builder
    assert "tools={workflowReadyTools}" in builder
    assert "export type WorkflowDesignSemanticPortPlan" in model
    assert "semanticPortPlan?: WorkflowDesignSemanticPortPlan" in model

    assert 'data-testid="workflow-design-semantic-port-plan"' in component
    assert "WorkflowDesignSemanticPortPlan" in component
    assert "RulePortConverterInsertionRequest" in component
    assert "workflowToolRevisionId" in component
    assert "edge.converterCandidates.slice(0, 2)" in component
    assert "candidate.confirmationRequired" in component
    assert "candidate.insertionMode" in component
    assert "insertionRequestForBackendCandidate" in component
    assert "onInsertConverter(insertionRequestForBackendCandidate(edge, candidate))" in component
    assert "inputName: candidate.inputPort" in component
    assert "outputName: candidate.outputPort" in component
    assert "decision.matchedFields" in component
    assert "decision.genericFields.map" in component
    assert "需确认，不会自动插入" in component
    assert "确认插入转换" in component
    assert "候选工具不在当前可用工具库" in component

    assert "ruleTemplate" not in component
    assert "commandTemplate" not in component
    assert "converterPath" not in component
