from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _component_source(filename: str) -> str:
    return (COMPONENTS / filename).read_text(encoding="utf-8")


def test_workflow_run_detail_model_and_panel_surface_rule_level_state() -> None:
    model = _component_source("workflows-page-model.ts")
    api = _component_source("workflows-page-api.ts")
    panel = _component_source("workflow-run-detail-panel.tsx")
    execution_panel = _component_source("workflow-run-execution-context.tsx")
    rule_failure_diagnostics = _component_source("workflow-rule-failure-diagnostics.tsx")
    package_panel = _component_source("workflow-result-package-panel.tsx")
    dag_preview = _component_source("workflow-dag-preview.tsx")
    catalog_service = (ROOT / "apps" / "api" / "workflow_catalog_service.py").read_text(encoding="utf-8")

    assert "export type WorkflowRunRuleEvent" in model
    assert "export type WorkflowRunRule" in model
    assert "export type WorkflowRunRules" in model
    assert "export type WorkflowRunExecutionContext" in model
    assert "export type WorkflowRunRuleRetryPlan" in model
    assert "export type WorkflowRunRuleRetryExecutionPlan" in model
    assert "export type WorkflowRunRuleRetrySnakemakeOptions" in model
    assert "export type WorkflowRunResumePlan" in model
    assert "export type WorkflowRunResumeSnakemakeOptions" in model
    assert "export type WorkflowRunFailureLocator" in model
    assert "export type WorkflowResultPackageDownload" in model
    assert "export type WorkflowResultPackageExport" in model
    assert "export type WorkflowResultPackageExportListResponse" in model
    assert "export type WorkflowResultPackageExportResponse" in model
    assert "packageExportId?: string" in model
    assert "lifecycleState?: string" in model
    assert "download?: WorkflowResultPackageDownload" in model
    assert "exportId?: string" not in model
    assert "packagePath?: string" not in model
    assert "packageUri?: string" not in model
    assert "rules?: WorkflowRunRules" in model
    assert "executionContext?: WorkflowRunExecutionContext" in model
    assert "failureLocator?: WorkflowRunFailureLocator" in model
    assert "ruleLogContext?: WorkflowRunRuleLogContext" in model
    assert "export type WorkflowRunRuleLogContext" in model
    assert '"PATH_REFERENCE_ONLY"' in model
    assert '"PREVIEW_AVAILABLE"' in model
    assert "reasonCode?: \"RUN_NOT_FAILED\" | \"RUN_FAILED_NO_RULE\" | \"FAILED_RULE\" | string" in model
    assert "ruleRetryPlan?: WorkflowRunRuleRetryPlan" in model
    assert "ruleRetryExecutionPlan?: WorkflowRunRuleRetryExecutionPlan" in model
    assert "resumePlan?: WorkflowRunResumePlan" in model
    assert "workdirEvidence?:" in model
    assert "incompleteOutputAudit?:" in model
    assert "artifactAdoptionBoundary?: WorkflowRunAdoptionBoundary" in model
    assert "executionEnabled?: boolean" in model
    assert "commandPreviewAvailable?: boolean" in model
    assert "snakemakeOptions?: WorkflowRunRuleRetrySnakemakeOptions" in model
    assert "snakemakeOptions?: WorkflowRunResumeSnakemakeOptions" in model
    assert "unsafeFlagsProhibited?: string[]" in model
    assert "selectedAttempt?: WorkflowRunRuleSelectedAttempt" in model
    assert "cacheAdoptionBoundary?: WorkflowRunAdoptionBoundary" in model
    assert "artifactAdoptionBoundary?: WorkflowRunAdoptionBoundary" in model
    assert "preservedRules?: WorkflowRunRuleRetryPlanRuleRef[]" in model
    assert "invalidatedRules?: WorkflowRunRuleRetryPlanRuleRef[]" in model
    assert "logs?: string[]" in model
    assert "details?: Record<string, unknown>" in model
    assert "exportWorkflowResultPackage" in api
    assert "workflowResultPackageDownloadHref" in api
    assert "href.startsWith(\"/api/v1/\")" in api
    assert "`/api/v1/results/${encodeURIComponent(resultId)}/export`" in api
    assert 'actor: "workflow-ui"' in api
    assert "includeArtifacts" in api
    assert "rules_data = _unwrap_data(rules, {})" in catalog_service
    assert "execution_context_data = _unwrap_data(execution_context, {})" in catalog_service
    assert '"rules": rules_data' in catalog_service
    assert '"executionContext": execution_context_data' in catalog_service
    assert "failure_locator = _build_failure_locator(" in catalog_service
    assert '"failureLocator": failure_locator' in catalog_service
    assert '_load_rule_log_context(' in catalog_service
    assert '"schemaVersion": "run-failure-locator.v1"' in catalog_service
    assert '_canonical_result_id_for_run(str(result_data.get("runId") or run_id))' in catalog_service
    assert "runtime.get_run_rules(run_id)" in catalog_service
    assert "runtime.get_run_execution_context(run_id)" in catalog_service

    assert 'type TabKey = "overview" | "rules" | "artifacts" | "stdout" | "stderr"' in panel
    assert '{ key: "rules", label: "规则" }' in panel
    assert "WorkflowRunExecutionContextPanel" in panel
    assert "WorkflowResultPackagePanel" in panel
    assert "context={detail.executionContext}" in panel
    assert "ruleRetryPlan" not in panel
    assert "resultId={detail.results?.resultId}" in panel
    assert "workflowRevisionId={workflowRevisionId}" in panel
    assert "function RunRules" in panel
    assert "detail.rules?.items || []" in panel
    assert "<RunRules rules={rules} />" in panel
    assert "WorkflowRuleFailureDiagnostics" in panel
    assert "failureLocator={detail.failureLocator}" in panel
    assert "failureLocator?.failedRule?.runRuleId" in panel
    assert "failureLocator?.logContext?.stderrTail" in panel
    assert "ruleLogContext={failureLocator?.ruleLogContext}" in panel
    assert "失败 rule：" in panel
    assert "rule.attemptNumber" in panel
    assert "rule.leaseGeneration" in panel
    assert "rule.events || []" in panel
    assert "失败定位" in rule_failure_diagnostics
    assert "log paths" in rule_failure_diagnostics
    assert "log evidence" in rule_failure_diagnostics
    assert "selectedLogArtifact?.artifactId" in rule_failure_diagnostics
    assert "logTail.join" in rule_failure_diagnostics
    assert "scalarDetails(failedEvent?.details)" in rule_failure_diagnostics
    assert "[...(rule.events || [])].reverse().find(isFailureEvent)" in rule_failure_diagnostics
    assert "ruleLogContext?: WorkflowRunRuleLogContext" in rule_failure_diagnostics
    assert "context.ruleRetryPlan" in execution_panel
    assert "context.ruleRetryExecutionPlan" in execution_panel
    assert "context.resumePlan" in execution_panel
    assert "RuleRetryPlanSummary" in execution_panel
    assert "RuleRetryExecutionPlanPreview" in execution_panel
    assert "RunResumePlanPreview" in execution_panel
    assert "plan.selectedAttemptCount" in execution_panel
    assert "planned only" in execution_panel
    assert "not enabled" in execution_panel
    assert "规则级重试计划仅供诊断" in execution_panel
    assert "当前重试按钮会重新调度整个 run" in execution_panel
    assert "rule retry execution plan" in execution_panel
    assert "run resume plan" in execution_panel
    assert "workdir evidence" in execution_panel
    assert "output audit" in execution_panel
    assert "artifact adoption" in execution_panel
    assert "command preview" in execution_panel
    assert "preview only" in execution_panel
    assert "局部规则重试执行仍关闭" in execution_panel
    assert "unsafe flags" in execution_panel
    assert "onResumeRun" not in execution_panel
    assert "onRetryRule" not in execution_panel
    assert "retryRule" not in execution_panel
    assert "resumeRun" not in execution_panel
    assert "onRetryRule" not in panel
    assert "retryRule" not in panel
    assert "onRetryRule" not in rule_failure_diagnostics
    assert "retryRule" not in rule_failure_diagnostics
    assert "onRetryRule" not in dag_preview
    assert "retryRule" not in dag_preview

    assert "export function WorkflowResultPackagePanel" in package_panel
    assert "fetchWorkflowResultPackageExports(resultId)" in package_panel
    assert "exportWorkflowResultPackage(resultId, mode === \"full\")" in package_panel
    assert "mergeResultPackageExport(item, current)" in package_panel
    assert "resultPackageDisabledReason" in package_panel
    assert "isResultPackageExportableRunStatus(run.status)" in package_panel
    assert 'status === "completed" || status === "failed"' in package_panel
    assert "metadata-only" in package_panel
    assert "含产物文件" in package_panel
    assert "仅 completed/failed 运行可导出" in package_panel
    assert "缺少 WorkflowRevision" in package_panel
    assert "workflowResultPackageDownloadHref(item)" in package_panel
    assert "lifecycleState" in package_panel
    assert "导出记录" in package_panel
    assert "fetchWorkflowResultPackageExports" in api
    assert "Download" in package_panel
    assert "下载结果包" in package_panel
    assert "packageUri" not in package_panel
    assert "packagePath" not in package_panel
    assert "file://" not in package_panel
    assert "packageExportId" in package_panel
    assert "sha256" in package_panel
    assert "manifestSha256" in package_panel
    assert "evidenceId" in package_panel
    assert "window.open" not in package_panel
    assert "HTMLAnchorElement" not in package_panel


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
