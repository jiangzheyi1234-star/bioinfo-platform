from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _component_source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_workflow_run_detail_model_and_panel_surface_rule_level_state() -> None:
    model = _component_source("workflows-page-model.ts")
    panel = _component_source("workflow-run-detail-panel.tsx")
    catalog_service = (ROOT / "apps" / "api" / "workflow_catalog_service.py").read_text(encoding="utf-8")

    assert "export type WorkflowRunRuleEvent" in model
    assert "export type WorkflowRunRule" in model
    assert "export type WorkflowRunRules" in model
    assert "export type WorkflowRunExecutionContext" in model
    assert "rules?: WorkflowRunRules" in model
    assert "executionContext?: WorkflowRunExecutionContext" in model
    assert '"rules": _unwrap_data(rules, {})' in catalog_service
    assert '"executionContext": _unwrap_data(execution_context, {})' in catalog_service
    assert "runtime.get_run_rules(run_id)" in catalog_service
    assert "runtime.get_run_execution_context(run_id)" in catalog_service

    assert 'type TabKey = "overview" | "rules" | "artifacts" | "stdout" | "stderr"' in panel
    assert '{ key: "rules", label: "规则" }' in panel
    assert "WorkflowRunExecutionContextPanel" in panel
    assert "context={detail.executionContext}" in panel
    assert "function RunRules" in panel
    assert "detail.rules?.items || []" in panel
    assert "<RunRules rules={rules} />" in panel
    assert "失败 rule：" in panel
    assert "rule.attemptNumber" in panel
    assert "rule.leaseGeneration" in panel
    assert "rule.events || []" in panel


def test_workflow_dag_preview_maps_rule_status_to_graph_nodes() -> None:
    dag_preview = _component_source("workflow-dag-preview.tsx")

    assert "WorkflowRunRule" in dag_preview
    assert "runRulesByGraphNode(flowNodes, runDetail)" in dag_preview
    assert "const byRuntimeStatusKey" in dag_preview
    assert "const byStepId" in dag_preview
    assert "const byRuleName" in dag_preview
    assert "node.runtimeStatusKey ? byRuntimeStatusKey.get(node.runtimeStatusKey)" in dag_preview
    assert "byStepId.get(node.id)" in dag_preview
    assert "byRuleName.get(node.label)" in dag_preview
    assert "RuleRunStatus" in dag_preview
    assert "ruleByNodeId.get(node.id)" in dag_preview
