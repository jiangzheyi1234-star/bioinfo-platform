from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_workflow_design_compile_summary_displays_slim_revision_semantic_port_evidence() -> None:
    builder = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    model = (COMPONENTS / "workflow-design-draft-model.ts").read_text(encoding="utf-8")
    summary = (COMPONENTS / "workflow-design-compile-summary.tsx").read_text(encoding="utf-8")

    assert 'import { WorkflowDesignCompileSummary } from "./workflow-design-compile-summary";' in builder
    assert "<WorkflowDesignCompileSummary result={compileResult || null} />" in builder
    assert "function WorkflowDesignCompileSummary" not in builder

    assert "export type WorkflowDesignSemanticPortEvidenceEdge" in model
    assert "export type WorkflowDesignSemanticPortEvidence" in model
    assert "semanticPortEvidence?: WorkflowDesignSemanticPortEvidence" in model
    assert "schemaVersion: \"h2ometa.workflow-design-semantic-port-evidence.v1\"" in model

    assert "export function semanticPortEvidenceForResult" in summary
    assert "result.semanticPortEvidence || result.workflowRevision?.graphSnapshot?.semanticPortEvidence || null" in summary
    assert 'data-testid="workflow-design-semantic-port-evidence"' in summary
    assert "data-semantic-port-evidence-status={evidence.status}" in summary
    assert "data-semantic-port-evidence-edge-count={evidence.edgeCount}" in summary
    assert "data-semantic-port-evidence-blocked-count={evidence.blockedEdgeCount}" in summary
    assert "evidence.edges.slice(0, 3)" in summary
    assert "edge.recommendation.reasonCode" in summary

    assert "converterCandidates" not in summary
    assert "ruleTemplate" not in summary
    assert "commandTemplate" not in summary
