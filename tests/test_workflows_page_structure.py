from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
FIRST_RUN_ROUTE = ROOT / "apps" / "web" / "app" / "workflows" / "first-run"
FIRST_RUN_COMPONENTS = FIRST_RUN_ROUTE / "_components"
FIRST_RUN_API = FIRST_RUN_ROUTE / "_api"
FIRST_RUN_DOMAIN = FIRST_RUN_ROUTE / "_domain"
FIRST_RUN_STATE = FIRST_RUN_ROUTE / "_state"


def _tools_page_model_source() -> str:
    return "\n".join(
        (COMPONENTS / filename).read_text(encoding="utf-8")
        for filename in (
            "tools-page-model.ts",
            "tools-page-core-model.ts",
            "tools-page-catalog-model.ts",
        )
    )


def _tools_page_ui_source() -> str:
    return "\n".join(
        (COMPONENTS / filename).read_text(encoding="utf-8")
        for filename in (
            "tools-page-ui.tsx",
            "tools-page-catalog-quality-strip.tsx",
        )
    )


def test_first_successful_run_is_default_onboarding_path() -> None:
    root_page = (ROOT / "apps" / "web" / "app" / "page.tsx").read_text(encoding="utf-8")
    tabs = (COMPONENTS / "workflow-workspace-tabs.tsx").read_text(encoding="utf-8")
    first_run_route = ROOT / "apps" / "web" / "app" / "workflows" / "first-run" / "page.tsx"
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    first_run_api = (FIRST_RUN_API / "workflow-first-run-api.ts").read_text(encoding="utf-8")
    first_run_completion = (FIRST_RUN_COMPONENTS / "workflow-first-run-completion.tsx").read_text(encoding="utf-8")
    first_run_conductor = (FIRST_RUN_COMPONENTS / "workflow-first-run-conductor.tsx").read_text(encoding="utf-8")
    first_run_report = (FIRST_RUN_COMPONENTS / "workflow-first-run-report.tsx").read_text(encoding="utf-8")
    first_run_sample_submit = (FIRST_RUN_COMPONENTS / "workflow-first-run-sample-submit.tsx").read_text(encoding="utf-8")
    first_run_trust_summary = (FIRST_RUN_COMPONENTS / "workflow-first-run-trust-summary.tsx").read_text(encoding="utf-8")
    first_run_validation = (FIRST_RUN_COMPONENTS / "workflow-first-run-validation.tsx").read_text(encoding="utf-8")
    first_run_evidence_bundle = (FIRST_RUN_DOMAIN / "first-run-evidence-bundle.ts").read_text(encoding="utf-8")
    first_run_progress = (FIRST_RUN_DOMAIN / "first-run-progress.ts").read_text(encoding="utf-8")
    first_run_display = (FIRST_RUN_DOMAIN / "first-run-display.ts").read_text(encoding="utf-8")
    first_run_package = (FIRST_RUN_DOMAIN / "first-run-package.ts").read_text(encoding="utf-8")
    first_run_types = (FIRST_RUN_DOMAIN / "first-run-types.ts").read_text(encoding="utf-8")
    first_run_evidence_state = (FIRST_RUN_STATE / "use-first-run-evidence.ts").read_text(encoding="utf-8")
    first_run_status_state = (FIRST_RUN_STATE / "use-first-run-status.ts").read_text(encoding="utf-8")
    server_readiness_api = (COMPONENTS / "workflow-server-readiness-api.ts").read_text(encoding="utf-8")
    workflow_detail_page = (COMPONENTS / "workflow-detail-page.tsx").read_text(encoding="utf-8")
    results_page = (COMPONENTS / "workflow-results-page.tsx").read_text(encoding="utf-8")
    result_detail_page = (COMPONENTS / "workflow-result-detail-page.tsx").read_text(encoding="utf-8")
    runner_repair = (COMPONENTS / "workflow-runner-repair-state.tsx").read_text(encoding="utf-8")
    page_ui = (COMPONENTS / "workflows-page-ui.tsx").read_text(encoding="utf-8")
    models = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    first_run_source = f"{first_run_page}\n{first_run_api}\n{first_run_completion}\n{first_run_conductor}\n{first_run_report}\n{first_run_sample_submit}\n{first_run_trust_summary}\n{first_run_validation}"
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    runner_adapter = _function_body(runner_repair, "workflowServerRepairStatus")

    assert 'redirect("/workflows/first-run")' in root_page
    assert first_run_route.exists()
    assert not any(COMPONENTS.glob("workflow-first-run-*"))
    assert not (COMPONENTS / "workflow-sample-data-api.ts").exists()
    assert not (FIRST_RUN_DOMAIN / "first-run-validation-state.ts").exists()
    assert "./_components/workflow-first-run-page" in first_run_route.read_text(encoding="utf-8")
    assert "WorkflowFirstRunPage" in first_run_route.read_text(encoding="utf-8")
    assert '{ href: "/workflows/first-run", label: "首跑" }' in tabs
    assert 'export const FIRST_RUN_PIPELINE_ID = "moving-pictures-16s-rulegraph-v1"' in first_run_progress
    assert "buildFirstRunSteps" in first_run_progress
    assert "runnerChecks" in first_run_progress
    assert "workflowRevisionIdFor" in first_run_progress
    assert "resultPackageDisabledReason" in first_run_progress
    assert "export function artifactName" in first_run_display
    assert "export function formatBytes" in first_run_display
    assert "export function firstRunResultPackageReady" in first_run_package
    assert "export function useFirstRunEvidence" in first_run_evidence_state
    assert "export function useFirstRunStatus" in first_run_status_state
    assert "fetchFirstRunStatus" in first_run_status_state
    assert "from \"../_domain/first-run-progress\"" in first_run_page
    assert "from \"../_state/use-first-run-evidence\"" in first_run_page
    assert "from \"../_state/use-first-run-status\"" in first_run_page
    assert 'const FIRST_RUN_PIPELINE_ID = "moving-pictures-16s-rulegraph-v1"' not in first_run_page
    assert "useWorkflowsPageState(FIRST_RUN_PIPELINE_ID)" in first_run_page
    assert "useWorkflowsPageState(FIRST_RUN_PIPELINE_ID, { autoResumeLatestRun: true })" not in first_run_page
    assert "useWorkflowsPageState(workflowId)" in workflow_detail_page
    assert "autoResumeLatestRun" not in workflow_detail_page
    assert "autoResumeLatestRun" not in hook
    assert "const movingPicturesWorkflow = state.catalog.find((item) => item.id === FIRST_RUN_PIPELINE_ID) || null" in first_run_page
    assert "连接远端" in first_run_page
    assert "runner readiness" in first_run_page
    assert "准备示例数据" in first_run_progress
    assert "提交运行" in first_run_progress
    assert "看懂报告" in first_run_progress
    assert "Moving Pictures 结果解读" in first_run_report
    assert "MOVING_PICTURES_EXPECTED_OUTPUTS" in first_run_report
    assert "summary.tsv" in first_run_report
    assert "qc-summary.tsv" in first_run_report
    assert "feature-table.tsv" in first_run_report
    assert "run-report.html" in first_run_report
    assert "first-run-report-insight" in first_run_report
    assert "first-run-rule-level-run-view" in first_run_report
    assert "data-rule-projection={rulesReady ? \"available\" : \"pending\"}" in first_run_report
    assert "WorkflowRuleFailureDiagnostics" in first_run_report
    assert "WorkflowRuleLogEvidence" in first_run_report
    assert "RuleAttemptBadge" in first_run_report
    assert "firstFailedRule(detail, rules)" in first_run_report
    assert "完整规则 / retry / resume" in first_run_report
    assert "ruleHasLogEvidence" in first_run_report
    assert "完成首跑" in first_run_source
    assert "仅导出结果包" in first_run_source
    assert "结果验证卡" in first_run_source
    assert "下载/分享证据包" in first_run_progress
    assert "结果包、验证卡 JSON/Markdown、pilot handoff 四件套" in first_run_progress
    assert '"evidence-bundle"' in first_run_progress
    assert "FirstRunCompletionPanel" in first_run_page
    assert "first-run-completion-panel" in first_run_completion
    assert "first-run-pilot-handoff" in first_run_completion
    assert "first-run-evidence-bundle" in first_run_completion
    assert "first-run-pilot-backup-restore" in first_run_completion
    assert "first-run-completion-download-${role || \"evidence\"}" in first_run_completion
    assert "card?.pilotHandoff" in first_run_completion
    assert "pilotHandoffFromCard" not in first_run_completion
    assert "first-run-next-scenario-handoff" in first_run_completion
    assert "first-run-next-scenario-blockers" in first_run_completion
    assert "first-run-next-scenario-tool-slice-promotion" in first_run_completion
    assert "data-next-scenario-tool-action" in first_run_completion
    assert "item.acceptanceEvidenceContract?.status !== \"accepted\"" in first_run_completion
    assert "pendingToolEvidence" in first_run_completion
    assert "first-run-next-scenario-database-handoff" in first_run_completion
    assert "first-run-next-scenario-ready-scan" in first_run_completion
    assert "first-run-next-scenario-registration-prefill" in first_run_completion
    assert "data-next-scenario-database-action" in first_run_completion
    assert "pack.databaseHandoff?.packOptions" in first_run_completion
    assert "pack.databaseHandoff?.missingPackTemplates" in first_run_completion
    assert "pack.databaseHandoff?.readyScan" in first_run_completion
    assert "pack.databaseHandoff?.registration" in first_run_completion
    assert "fetchWorkflowScenarioPacks" in first_run_evidence_state
    assert "nextScenarioPacks" in first_run_evidence_state
    assert "downloadFirstRunHandoffManifest" not in first_run_evidence_state
    assert "downloadHandoffManifest" not in first_run_evidence_state
    assert "firstRunEvidenceBundleFiles(evidenceBundle)" in first_run_completion
    assert "firstRunEvidenceBundleFileDownloadHref(file)" in first_run_completion
    assert "fetchWorkflowScenarioPacks" not in first_run_page
    assert "WorkflowFirstRunConductorPanel" in first_run_page
    assert "useFirstRunConductor" in first_run_page
    assert "firstRunConductor" in first_run_page
    assert "continueFirstRun" in first_run_page
    assert "ensureWorkflowServerRunner" in first_run_page
    assert "requestLocalApiJson" not in first_run_page
    assert "export function buildFirstRunContinueAction" in first_run_conductor
    assert "export function WorkflowFirstRunConductorPanel" in first_run_conductor
    assert 'data-testid="first-run-conductor"' in first_run_conductor
    assert 'data-first-run-next-action={action.code}' in first_run_conductor
    assert 'data-testid="first-run-continue"' in first_run_conductor
    assert "继续首跑" in first_run_conductor
    assert '"CONNECT_REMOTE"' in first_run_conductor
    assert '"ENSURE_RUNNER"' in first_run_conductor
    assert '"PREPARE_SAMPLE_DATA"' in first_run_conductor
    assert '"SUBMIT_RUN"' in first_run_conductor
    assert '"FINALIZE_FIRST_RUN"' in first_run_conductor
    assert "export async function ensureWorkflowServerRunner" in server_readiness_api
    assert "export async function startWorkflowServerRunner" in server_readiness_api
    assert "postWorkflowServerRunnerAction(serverId, \"ensure-runner\")" in server_readiness_api
    assert "postWorkflowServerRunnerAction(serverId, \"runner/start\")" in server_readiness_api
    assert "/api/v1/servers/${encodeURIComponent(normalizedServerId)}/${actionPath}" in server_readiness_api
    assert "timeoutMs: 120_000" in server_readiness_api
    assert "invalidateAsyncCache(WORKFLOW_SERVER_CACHE_KEY)" in server_readiness_api
    assert "runWorkflowServerRunnerRepairAction" in hook
    assert "export function workflowServerRepairStatus" in runner_repair
    assert "export function workflowServerRunnerManuallyStopped" in runner_repair
    assert "export async function runWorkflowServerRunnerRepairAction" in runner_repair
    assert "export function useWorkflowRunnerRepairState" in runner_repair
    assert "export function WorkflowRunnerRepairNotice" in runner_repair
    assert "workflowServerRunnerManuallyStopped(server) ? startWorkflowServerRunner : ensureWorkflowServerRunner" in runner_repair
    assert "runner.reasonCode === MANUAL_RUNNER_STOP_REASON" in runner_repair
    assert "refreshWorkflowServer" in hook
    assert "runnerEnsureBusy" in hook
    assert "runnerRepairError" in hook
    assert "onEnsureRunner={() => void state.ensureRunner()}" in workflow_detail_page
    assert "onRefreshServer={state.refreshWorkflowServer}" in workflow_detail_page
    assert "runnerEnsureBusy={state.runnerEnsureBusy}" in workflow_detail_page
    assert "runnerRepairError={state.runnerRepairError}" in workflow_detail_page
    assert "RunnerRepairPanel" in page_ui
    assert "from \"./workflow-runner-repair-state\"" in page_ui
    assert "workflowServerRepairStatus(server)" in page_ui
    assert "const showRunnerRepair = Boolean(runnerRepairStatus?.connected && runnerRepairStatus.runner && !runnerRepairStatus.runner.ready)" in page_ui
    assert "onRefreshStatus={onRefreshServer}" in page_ui
    assert "useWorkflowRunnerRepairState()" in results_page
    assert "WorkflowRunnerRepairNotice controller={runnerRepair} mode=\"compact\"" in results_page
    assert "useWorkflowRunnerRepairState()" in result_detail_page
    assert "WorkflowRunnerRepairNotice controller={runnerRepair} mode=\"compact\"" in result_detail_page
    assert "data-testid=\"workflow-runner-repair-notice\"" in runner_repair
    assert 'data-runner-repair-mode={mode}' in runner_repair
    assert 'mode?: "compact" | "full"' in runner_repair
    assert 'const [expanded, setExpanded] = useState(mode === "full")' in runner_repair
    assert "diagnosticsOnly={compact}" in runner_repair
    assert "const canPrepareRunner = Boolean(status?.connected && status.serverId && !status.runner?.ready)" in runner_repair
    assert "const hasKnownRunnerTarget = Boolean(status?.serverId || controller.server?.serverId)" in runner_repair
    assert "const visibleLoadError = hasKnownRunnerTarget ? controller.loadError : \"\"" in runner_repair
    assert "displayTarget: server.label || server.serverId" in runner_adapter
    assert "connected = server.connected === true" in runner_adapter
    assert "ready: runner.ready === true" in runner_adapter
    assert "server.ready &&" not in runner_adapter
    assert "port: 0" not in runner_adapter
    assert 'user: ""' not in runner_adapter
    assert "has_password" not in runner_adapter
    assert "servicePort?: number" in models
    assert "tunnelPort?: number" in models
    assert "FirstRunTrustSummary" in first_run_completion
    assert "单用户试点交接" in first_run_completion
    assert "首跑已完成" in first_run_completion
    assert "下载结果包" in first_run_completion
    assert "下载证据包清单" in first_run_completion
    assert "下载并分享以下 4 个文件" in first_run_completion
    assert "first-run-evidence-bundle-file" in first_run_completion
    assert "item.filename || item.source" in first_run_completion
    assert "firstRunEvidenceBundleFileDownloadHref(item)" in first_run_completion
    assert "firstRunResultPackageReady(latestPackage)" not in first_run_completion
    assert "from \"../_domain/first-run-package\"" not in first_run_completion
    assert "passed checks" in first_run_completion
    assert "RUN_OWN_SMALL_SAMPLE" not in first_run_completion
    assert "automatic-database-install" not in first_run_completion
    assert "backupRestore?: {" in first_run_types
    assert "nextScenarios?: Array" in first_run_types
    assert "databaseInstallHandoff?: {" in first_run_types
    assert "toolSlicePromotionHandoff?: {" in first_run_types
    assert "acceptanceEvidenceContract?: {" in first_run_types
    assert "evidencePointers?: Record" in first_run_types
    assert "requiredEvidence?: string[]" in first_run_types
    assert "requestFields?: string[]" in first_run_types
    assert "prefillFields?: string[]" in first_run_types
    assert "packOptions?: Array" in first_run_types
    assert "registrationScriptPath?: string" in first_run_types
    assert "acceptedEvidenceType?: string" in first_run_types
    assert "downloadFirstRunHandoffManifest" not in first_run_api
    assert "packageExports.find((item) => item.packageExportId === statusPackageExportId)" in first_run_evidence_state
    assert "const latestPackage = readyPackage || (status ? statusPackageFallback : packageExports[0])" in first_run_evidence_state
    assert "const packageReady = status?.evidence?.resultPackage?.ready === true" in first_run_evidence_state
    assert "const validationEligible = firstRunEvidence.validationEligible" in first_run_page
    assert "const validationEligible = validationReady" in first_run_evidence_state
    assert 'const validationReady = status?.status === "ready" || status?.evidence?.validation?.ready === true' in first_run_evidence_state
    assert "runCompleted && packageReady" not in first_run_evidence_state
    assert "firstRunValidationCardPassed" not in first_run_evidence_state
    assert "firstRunValidationCardPassed" not in first_run_page
    assert "firstRunValidationCardPassed" not in first_run_completion + first_run_trust_summary + first_run_validation
    assert "target: string" in first_run_progress
    assert "data-step-target={step.target}" in first_run_page
    assert "href={step.target}" in first_run_page
    assert '"#result-package"' in first_run_progress
    assert '"#evidence-bundle"' in first_run_progress
    assert "if (!ready) return null" in first_run_completion
    assert "const workflowRevisionId = status" in first_run_evidence_state
    assert ": workflowRevisionIdFor(run, runDetail, latestPackage)" in first_run_evidence_state
    assert "/api/v1/first-run/runs/${encodeURIComponent(runId)}/validation-card" in first_run_api
    assert "/api/v1/first-run/runs/${encodeURIComponent(runId)}/finalize" in first_run_api
    assert "export async function fetchFirstRunStatus" in first_run_api
    assert "/api/v1/first-run/status${queryString(query)}" in first_run_api
    assert "pilotHandoff?: FirstRunPilotHandoff" in first_run_types
    assert "export type FirstRunStatus" in first_run_types
    assert "latestEligibleRun?: FirstRunStatusRunSummary | null" in first_run_types
    assert "export type FirstRunEvidenceBundle" in first_run_types
    assert "evidenceBundle?: FirstRunEvidenceBundle" in first_run_types
    assert "href?: string;" in first_run_types
    assert "export async function finalizeFirstRun" in first_run_api
    assert "const firstRunRunId = status ? statusRun?.runId || \"\" : run?.runId || \"\"" in first_run_evidence_state
    assert "const runStatus = status ? statusRun?.status || \"\" : run?.status || \"\"" in first_run_evidence_state
    assert "finalizeFirstRun(firstRunRunId" in first_run_evidence_state
    assert "finalizeFirstRun(run.runId" not in first_run_evidence_state
    assert "finalizeFirstRun(run.runId" not in first_run_page
    assert 'actor: "first-run-ui"' in first_run_evidence_state
    assert "sampleData?: FirstRunSampleDataEvidence" in first_run_types
    assert "FirstRunSamplePrepProofItem" in first_run_types
    assert "prepProof?: FirstRunSamplePrepProofItem" in first_run_types
    assert "cachePolicy?: string;" in first_run_types
    assert "export type FirstRunSoftwareEnvironment" in first_run_types
    assert "softwareEnvironment?: FirstRunSoftwareEnvironment" in first_run_types
    assert "expectedSha256?: string" in first_run_types
    assert "fetchFirstRunValidationCard(firstRunRunId" in first_run_evidence_state
    assert "fetchFirstRunValidationCard(run.runId" not in first_run_evidence_state
    assert "const sampleData = card?.sampleData" in first_run_validation
    assert "const softwareEnvironment = card?.softwareEnvironment" in first_run_validation
    assert "reportInterpretation" in first_run_validation
    assert "first-run-validation-card-evidence" in first_run_validation
    assert "FirstRunTrustSummary" in first_run_validation
    assert "first-run-trust-summary" in first_run_trust_summary
    assert "data-summary-ready" in first_run_trust_summary
    assert "evidence?.validation?.ready === true" in first_run_trust_summary
    assert "这次结果为什么可信" in first_run_trust_summary
    assert "官方样例输入" in first_run_trust_summary
    assert "软件环境" in first_run_trust_summary
    assert "Moving Pictures 首跑不需要外部参考数据库" in first_run_trust_summary
    assert "关键结果" in first_run_trust_summary
    assert "结果包" in first_run_trust_summary
    assert "可信性检查已通过" in first_run_validation
    assert "可信性检查未全部通过" in first_run_validation
    assert "data-validation-eligible" in first_run_validation
    assert "data-validation-passed" in first_run_validation
    assert "const validationEvidence = firstRunStatus?.evidence?.validation" in first_run_validation
    assert "const validationPassed = validationEvidence?.ready === true" in first_run_validation
    assert "firstRunValidationCardPassed" not in first_run_validation
    assert "checksPassed && bundleReady" not in first_run_validation
    assert "from \"../_domain/first-run-validation-state\"" not in first_run_validation
    assert "from \"../_domain/first-run-display\"" in first_run_validation
    assert "from \"./workflow-first-run-validation\"" not in first_run_completion
    assert "from \"./workflow-first-run-validation\"" not in first_run_report
    assert "from \"./workflow-first-run-validation\"" not in first_run_sample_submit
    assert "`${passedChecks}/${totalChecks} passed checks`" in first_run_validation
    assert "ValidationCardEvidenceSummary" in first_run_validation
    assert "ValidationCardEvidenceBundle" in first_run_validation
    assert "first-run-validation-card-evidence-bundle" in first_run_validation
    assert "证据包清单已生成" in first_run_validation
    assert 'id="evidence-bundle"' in first_run_validation
    assert 'KeyValue label="bundle"' in first_run_validation
    assert 'KeyValue label="bundle files"' in first_run_validation
    assert "card.keyResults" in first_run_validation
    assert "card.resultPackage" in first_run_validation
    assert "FIRST_RUN_SAMPLE_INPUTS_VERIFIED" in first_run_validation
    assert "first-run-validation-card-software" in first_run_validation
    assert "软件环境已锁定" in first_run_validation
    assert "softwareRuntimeLabel(softwareEnvironment)" in first_run_validation
    assert "runtimeLabel(server)" not in first_run_validation
    assert "{sampleData ? <ValidationCardSampleData sampleData={sampleData} /> : null}" in first_run_validation
    assert "first-run-validation-card-sample-data" in first_run_validation
    assert "官方样例输入已验证" in first_run_validation
    assert "sampleData.source" in first_run_validation
    assert "item.sha256 || item.expectedSha256" in first_run_validation
    assert "formatBytes(item.expectedSizeBytes || item.sizeBytes)" in first_run_validation
    assert "item.integrityStatus" in first_run_validation
    assert 'item.integrityStatus || "unknown"' in first_run_validation
    assert "item.prepProof" in first_run_validation
    assert "prepProof.cacheStatus" in first_run_validation
    assert "prepProof.downloadStatus" in first_run_validation
    assert "first-run-validation-card-interpretation" in first_run_validation
    assert "first-run-validation-card-output-interpretation" in first_run_validation
    assert "output.interpretation" in first_run_validation
    assert "export type FirstRunValidationCard" in first_run_types
    assert not (FIRST_RUN_DOMAIN / "first-run-markdown.ts").exists()
    assert "export type FirstRunValidationCard" not in first_run_api
    assert "export function firstRunValidationCardMarkdown(card" not in first_run_api
    assert "firstRunValidationCardMarkdown(" not in first_run_api
    assert "downloadTextFile" not in first_run_api
    assert "Blob" not in first_run_api
    assert "URL.createObjectURL" not in first_run_api
    assert "apiBase()" not in first_run_api
    assert "apiBase()" in first_run_evidence_bundle
    assert 'href.startsWith("/api/v1/")' in first_run_evidence_bundle
    assert "firstRunValidationCardJsonDownloadPath" not in first_run_api
    assert "firstRunValidationCardMarkdownDownloadPath" not in first_run_api
    assert "firstRunPilotHandoffMarkdownDownloadPath" not in first_run_api
    assert "firstRunDownloadPath" not in first_run_api
    assert "downloadLocalApiFile" not in first_run_api
    assert "firstRunEvidenceBundleFileDownloadHref" in first_run_validation
    assert "serverId: firstRunServerId" in first_run_evidence_state
    assert "fetchWorkflowServerExecutionDiagnostics" in first_run_page
    assert "RunnerRepairPanel" in first_run_page
    assert 'data-testid="first-run-runner-repair"' in first_run_page
    assert "sshStatus={ssh.status}" in first_run_page
    assert 'className="shadow-none"' in first_run_page
    assert "executionDiagnostics?.readiness?.ok === true" in first_run_page
    assert "const firstRunCanSubmit = Boolean(" in first_run_page
    assert 'firstRunStatusSnapshot?.nextAction?.code === "SUBMIT_RUN"' in first_run_page
    assert "statusServerEvidence?.ready === true" in first_run_page
    assert "statusExecutionEvidence?.ready === true" in first_run_page
    assert "statusWorkflowEvidence?.ready === true" in first_run_page
    assert "serverConnected &&" not in first_run_page
    assert 'id="runner-readiness"' in first_run_page
    assert 'id="sample-data"' in first_run_sample_submit
    assert 'id="run-report"' in first_run_report
    assert 'id="result-package"' in first_run_validation
    assert 'id="validation-card"' in first_run_validation
    assert 'data-testid="first-run-finalize"' in first_run_validation
    assert "first-run-finalization-next-action" in first_run_validation
    assert "first-run-finalization-next-action-link" in first_run_validation
    assert "finalizationAction.target" in first_run_validation
    assert "first-run-execution-diagnostics-blockers" in first_run_page
    assert "eligible={validationEligible}" in first_run_page
    assert "ready={validationReady}" in first_run_page
    assert "buildValidationCardPayload" not in first_run_source
    assert "QIIME 2 Moving Pictures tutorial" in first_run_source
    assert 'FIRST_RUN_EXPECTED_SAMPLE_ROLES = ["metadata", "barcodes", "sequences"] as const' in first_run_sample_submit
    assert "export function sampleUploadRoleAudit" in first_run_sample_submit
    assert "missingRoles" in first_run_sample_submit
    assert "unexpectedRoles" in first_run_sample_submit
    assert "duplicateRoles" in first_run_sample_submit
    assert "first-run-sample-role-audit" in first_run_sample_submit
    assert "样本输入角色不可信" in first_run_sample_submit
    assert "roleAudit.unexpectedRoles.length === 0" in first_run_sample_submit
    assert "roleAudit.duplicateRoles.length === 0" in first_run_sample_submit
    assert "samplePrepProofLabel(upload)" in first_run_sample_submit
    assert "prep proof pending" in first_run_sample_submit
    assert "prepProof?: {" in models
    assert "cacheStatus?: string;" in models
    assert "downloadStatus?: string;" in models
    assert "sampleDataPrepProofFromUploads(uploads)" in (COMPONENTS / "workflow-pipeline-run-spec.ts").read_text(encoding="utf-8")
    assert "checksum verified" in first_run_sample_submit
    assert "first-run-sample-selection" in first_run_sample_submit
    assert "state.selectedWorkflow?.description" not in first_run_page
    assert "fetchWorkflowResultPackageExports(resultId, { serverId })" in first_run_evidence_state
    assert "fetchWorkflowResultPackageExports(resultId)" not in first_run_page
    assert "setRunHistoryError(workflowErrorMessage(err, \"读取运行历史失败\"))" in hook
    assert "state.runHistoryError" in first_run_page
    assert "latestRunForPipeline" not in hook
    assert "const reportReady = runCompleted && artifacts.length > 0" not in first_run_page
    assert "firstRunStatusSnapshot?.latestEligibleRun?.runId" in first_run_page
    assert "selectRun(latestEligibleRunId)" in first_run_page
    assert "firstRunStatus: firstRunStatusSnapshot || null" in first_run_page
    assert "statusAction: firstRunStatusSnapshot?.nextAction || null" not in first_run_page
    assert "workflowResultPackageDownloadHref" in first_run_validation
    assert "refreshRunDetail" in hook
    assert "export async function uploadWorkflowSampleData" in api
    assert "export async function fetchWorkflowServerExecutionDiagnostics" in api
    assert "/api/v1/servers/${encodeURIComponent(serverId)}/execution-diagnostics" in api
    assert "uploadWorkflowSampleData(selectedPipelineId, serverId)" in hook
    assert "sampleUploadIntegrityPassed" in hook
    assert "WORKFLOW_SAMPLE_DATA_INTEGRITY_REQUIRED" in api


def _function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    parameters_start = source.index("(", start)
    parameters_end = _matching_delimiter_end(source, parameters_start, "(", ")")
    brace = source.index("{", parameters_end)
    return _balanced_block(source, brace)


def _type_body(source: str, name: str) -> str:
    start = source.index(f"export type {name} = {{")
    brace = source.index("{", start)
    return _balanced_block(source, brace)


def _matching_delimiter_end(source: str, start: int, open_char: str, close_char: str) -> int:
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError(f"matching {close_char} not found")


def _balanced_block(source: str, brace: int) -> str:
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    raise AssertionError("balanced block not found")


def test_workflows_page_uses_live_builder_modules() -> None:
    page = (COMPONENTS / "workflows-page.tsx").read_text(encoding="utf-8")
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    scenario_section_path = COMPONENTS / "workflow-scenario-pack-section.tsx"
    generated_model = (COMPONENTS / "generated-workflow-model.ts").read_text(encoding="utf-8")
    readiness = (COMPONENTS / "tool-rule-readiness.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    ui = (COMPONENTS / "workflows-page-ui.tsx").read_text(encoding="utf-8")

    assert "const workflowTemplates = [" not in page
    assert "requestLocalApiJson" not in page
    assert "useWorkflowsPageState" in page
    assert "fetchWorkflowTemplates" not in api
    assert '"/api/v1/runs"' in api
    assert '"/api/v1/uploads"' in api
    assert '"/api/v1/workflow-scenario-packs"' in api
    assert "/api/v1/servers" in api
    assert "serverId" in api
    assert "contentBase64" in api
    assert "generated-tool-run-v1" in generated_model
    assert "ruleReadyToolScore" in model
    assert "WORKFLOW_TOOL_NOT_READY" in model
    assert "所选工具还未通过合同验证" in model
    assert "commandTemplate" in readiness
    assert "ruleActionFields(template)" in readiness
    assert "wrapperRefLocked" in readiness
    assert "targetPlatformSupported === true" in readiness
    assert "ruleSpecReadinessForTool(entry.tool).workflowReady" in model
    assert "submitWorkflowDesignRun" in api
    assert scenario_section_path.exists()
    scenario_section = scenario_section_path.read_text(encoding="utf-8")
    assert all(token in page for token in ("WorkflowScenarioPackSection", "fetchWorkflowScenarioPacks"))
    assert all(token in scenario_section for token in ("data-testid=\"workflow-scenario-pack-section\"", "data-scenario-pack={pack.scenarioId}", "pack.status === \"ready\"", "data-testid=\"workflow-scenario-readiness-checks\"", "data-scenario-check-status={check.status}", "check.requirement", "data-testid=\"workflow-scenario-practice-anchors\"", "pack.externalPracticeAnchors.slice(0, 2)", "target=\"_blank\"", "data-scenario-action={action.code}", "data-scenario-action=\"TOOL_SLICE_PROMOTION\"", "toolSliceNeedsOperator(pack)", "data-scenario-action=\"DATABASE_HANDOFF_WALKTHROUGH\"", "databaseHandoffNeedsOperator(pack)", "pack.nextActions.slice(0, 3)", "sampleDataLabel(pack)", "item.templates?.length", "data-testid=\"workflow-scenario-tool-slice-handoff\"", "data-testid=\"workflow-scenario-tool-slice-handoff-checklist\"", "data-testid=\"workflow-scenario-tool-slice-promotion-contract\"", "pack.toolSliceHandoff", "toolSliceHandoffText(pack)", "promotionContract?.requiredEvidence", "acceptanceEvidenceContract?.status !== \"accepted\"", "pendingEvidenceCount", "data-testid=\"workflow-scenario-sample-data-handoff\"", "data-testid=\"workflow-scenario-sample-data-handoff-checklist\"", "pack.sampleDataHandoff", "visibleItems = checklist.slice(0, 2)", "sampleDataHandoffInputText(pack)", "data-testid=\"workflow-scenario-database-handoff\"", "data-testid=\"workflow-scenario-database-handoff-checklist\"", "data-testid=\"workflow-scenario-database-ready-scan-contract\"", "pack.databaseHandoff", "checklist.slice(0, 3)", "databaseHandoffTemplateText(pack)", "data-testid=\"workflow-scenario-database-pack-options\"", "pack.databaseHandoff?.packOptions", "data-testid=\"workflow-scenario-database-missing-packs\"", "data-testid=\"workflow-scenario-pilot-readiness-plan\"", "data-testid=\"workflow-scenario-pilot-readiness-checklist\"", "pack.pilotReadinessPlan", "pilotReadinessPlanText(pack)", "acceptanceChecklist", "blockingGateCodes", "acceptanceEvidence"))
    assert all(token in model for token in ("noAutomaticExecution", "WorkflowScenarioToolSliceHandoff", "toolSliceHandoff?: WorkflowScenarioToolSliceHandoff", "acceptanceEvidenceContract?: WorkflowScenarioToolAcceptanceEvidenceContract", "export type WorkflowScenarioToolAcceptanceEvidenceContract", "evidencePointers?: Record", "promotionContract?: {", "perToolChecklist?: Array", "scenarioRunEvidence?:", "WorkflowScenarioSampleDataHandoff", "sampleDataHandoff?: WorkflowScenarioSampleDataHandoff", "WorkflowScenarioDatabasePackOption", "packOptions?: WorkflowScenarioDatabasePackOption[]", "missingPackTemplates?: string[]", "WorkflowScenarioDatabaseHandoff", "databaseHandoff?: WorkflowScenarioDatabaseHandoff", "schemaVersion?: string", "requestFields?: string[]", "prefillFields?: string[]", "auditAction?: string", "WorkflowScenarioPilotReadinessPlan", "pilotReadinessPlan?: WorkflowScenarioPilotReadinessPlan"))
    assert all(token not in scenario_section for token in ("uploadWorkflowSampleData", "downloadSampleData", "generateFixture", "addDatabase", "createToolPrepareJob", "prepareTool", "validateTool", "scanDatabasePackReady", "databasePackManualText", "databasePackRegistrationCommand", "onStartAddingFromPack"))
    assert "export function useWorkflowsPageState" in hook
    assert "export { WorkflowCatalogTable }" in ui
    assert "export function WorkflowRunBuilder" in ui


def test_generated_workflow_builder_uses_server_tool_recommendations() -> None:
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    builder_ui = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    recommendation_engine = (COMPONENTS / "workflow-tool-recommendation-engine.ts").read_text(encoding="utf-8")
    recommendations_path = COMPONENTS / "generated-workflow-tool-recommendations.tsx"

    assert recommendations_path.exists()
    recommendations_ui = recommendations_path.read_text(encoding="utf-8")
    assert "export async function fetchWorkflowToolRecommendations" in api
    assert "fetchCapabilityGraphSnapshot" in api
    assert "/api/v1/tool-capabilities/candidate-recommendations" not in api
    assert "workflowRecommendationsFromCapabilityGraph" in api
    assert "workflow-tool-recommendation-engine" in api
    assert "export function workflowRecommendationsFromCapabilityGraph" in recommendation_engine
    assert "portCompatibilityDecision" in recommendation_engine
    assert "capabilityPortSpec" in recommendation_engine
    assert "decision.matchedFields" in recommendation_engine
    assert "decision.advisoryFields" in recommendation_engine
    assert "decision.advisoryChecks" in recommendation_engine
    assert "const fields: Array<keyof RuleOutputSpec>" not in api
    assert "agentSelectable === true" in recommendation_engine
    assert "node.capabilityBundle?.capabilityId" in recommendation_engine
    assert "candidateKind: \"capability-bundle\"" in recommendation_engine
    assert "sourceOfTruth: \"capability-bundle-v1\"" in recommendation_engine
    assert "capabilityBundle?: CapabilityBundleSummary" in api
    assert "capabilityId?: string" in api
    assert "CapabilityGraphSemanticNode" in recommendation_engine
    assert "GeneratedWorkflowToolRecommendations" in builder_ui
    assert "outputCandidates={outputCandidates}" in builder_ui
    assert "onAddTool={onAddRecommendedTool || builder.addStep}" in builder_ui
    assert "onAddRecommendedTool?: (toolRevisionId: string, options?: GeneratedWorkflowAddStepOptions) => void" in builder_ui
    assert "fetchWorkflowToolRecommendations" in recommendations_ui
    assert "createToolPrepareJob" in recommendations_ui
    assert "useToolPrepareTasks" in recommendations_ui
    assert "trackToolPrepareJob" in recommendations_ui
    assert "handlePrepareRecommendation" in recommendations_ui
    assert "recommendation.preparePayload" in recommendations_ui
    assert "useEffect" in recommendations_ui
    assert "selectedOutputCandidate" in recommendations_ui
    assert "matchingWorkflowReadyTool" in recommendations_ui
    assert "executionGate" in api
    assert "requiredState?: string" in api
    assert "canAddStep?: boolean" in api
    assert "sourceOfTruth?: string" in api
    assert "validationPlan?: WorkflowToolRecommendationValidationPlan" in api
    assert "latestPrepareJob?: WorkflowToolRecommendationLatestPrepareJob" in api
    assert "advisoryFields: string[]" in api
    assert "advisoryChecks: string[]" in api
    assert "export type WorkflowToolRecommendationLatestPrepareJob" in api
    assert "validationResultId?: string" in _type_body(api, "WorkflowToolRecommendationLatestPrepareJob")
    assert "evidenceId?: string" in _type_body(api, "WorkflowToolRecommendationLatestPrepareJob")
    assert "toolRevisionId?: string" in api
    assert "toolId?: string" in api
    assert "WorkflowToolRecommendationPreparePayload" in api
    assert "preparePayload?: WorkflowToolRecommendationPreparePayload" in api
    assert "preparePayload?: WorkflowToolRecommendationPreparePayload" in _type_body(api, "WorkflowToolRecommendationCandidate")
    assert "ToolProfileWrapperEvidence" in api
    assert "snakemakeWrappers?: ToolProfileWrapperEvidence[]" in api
    assert "snakemakeWrapperCount?: number" in api
    assert "ruleSpecDraft?: RuleSpecDraft" in api
    assert "需验证到" in recommendations_ui
    assert "recommendation.executionGate.requiredState" in recommendations_ui
    assert "recommendation.executionGate?.sourceOfTruth" in recommendations_ui
    assert "recommendationFieldSummary" in recommendations_ui
    assert "recommendation.validationPlan?.stages?.length" in recommendations_ui
    assert "recommendation.latestPrepareJob?.status" in recommendations_ui
    assert "activePrepareJob" in recommendations_ui
    assert "recommendationAddStepRevisionId" in recommendations_ui
    assert "const addStepRevisionId = recommendationAddStepRevisionId(recommendation, tool)" in recommendations_ui
    assert "const canAddStep = Boolean(recommendation.executionGate?.canAddStep && addStepRevisionId)" in recommendations_ui
    assert "onAddTool(addStepRevisionId, {" in recommendations_ui
    assert "recommendation.preparePayload || recommendation.candidate.preparePayload" in _function_body(
        recommendations_ui,
        "addedToolFromRecommendation",
    )
    assert "!canAddStep && !tool && recommendation.executionGate?.requiredState" in recommendations_ui
    assert "recommendation.executionGate?.toolRevisionId" in recommendations_ui
    assert "recommendation.executionGate?.toolId" in recommendations_ui
    assert "准备并验证工具" in recommendations_ui
    assert "先加入工具库" not in recommendations_ui
    assert "builder.addStep" not in recommendations_ui
    assert "recommendationCandidateName(recommendation)" in _function_body(recommendations_ui, "recommendationLabel")
    assert "recommendationCandidateName(recommendation)" in _function_body(recommendations_ui, "recommendationSearchQuery")
    candidate_name_body = _function_body(recommendations_ui, "recommendationCandidateName")
    assert "recommendation.candidate.toolNames?.[0]" in candidate_name_body
    assert "recommendation.candidate.profileId" in candidate_name_body
    assert "recommendation.candidate.candidateId" in candidate_name_body
    assert "recommendation.candidate.profileId" in candidate_name_body
    assert "recommendation.candidate.candidateId" in candidate_name_body


def test_generated_workflow_builder_has_explicit_dag_contract() -> None:
    model_path = COMPONENTS / "generated-workflow-model.ts"
    design_model_path = COMPONENTS / "workflow-design-draft-model.ts"
    hook_path = COMPONENTS / "use-generated-workflow-builder.ts"
    ui_path = COMPONENTS / "generated-workflow-builder.tsx"
    globals_path = ROOT / "apps" / "web" / "app" / "globals.css"
    history_path = COMPONENTS / "generated-workflow-history.ts"
    graph_node_path = COMPONENTS / "generated-workflow-graph-node-card.tsx"
    graph_canvas_path = COMPONENTS / "generated-workflow-graph-canvas.tsx"
    graph_adapter_path = COMPONENTS / "generated-workflow-react-flow-adapter.ts"
    port_connection_path = COMPONENTS / "generated-workflow-port-connection.ts"
    node_settings_path = COMPONENTS / "generated-workflow-node-settings.tsx"
    command_contract_path = COMPONENTS / "generated-workflow-command-contract.ts"
    param_contract_path = COMPONENTS / "generated-workflow-param-contract.ts"
    port_contract_path = COMPONENTS / "generated-workflow-port-contract.ts"
    converter_contract_path = COMPONENTS / "generated-workflow-converter-recommendation.ts"
    recommendation_contract_path = COMPONENTS / "generated-workflow-recommendation-contract.ts"
    rule_action_contract_path = COMPONENTS / "generated-workflow-rule-action-contract.ts"
    snakefile_preview_path = COMPONENTS / "generated-workflow-snakefile-preview.tsx"
    runtime_contract_path = COMPONENTS / "generated-workflow-runtime-contract.ts"
    rule_spec_panel_path = COMPONENTS / "generated-workflow-rule-spec-panel.tsx"
    step_params_editor_path = COMPONENTS / "generated-workflow-step-params-editor.tsx"
    subflow_controls_path = COMPONENTS / "generated-workflow-subflow-controls.tsx"
    runtime_editor_path = COMPONENTS / "generated-workflow-runtime-editor.tsx"
    port_bindings_editor_path = COMPONENTS / "generated-workflow-port-bindings-editor.tsx"
    page_model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    page_hook = (COMPONENTS / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    page_ui = (COMPONENTS / "workflows-page-ui.tsx").read_text(encoding="utf-8")
    detail_page = (COMPONENTS / "workflow-detail-page.tsx").read_text(encoding="utf-8")

    assert model_path.exists()
    assert design_model_path.exists()
    assert hook_path.exists()
    assert ui_path.exists()
    assert globals_path.exists()
    assert history_path.exists()
    assert graph_node_path.exists()
    assert graph_canvas_path.exists()
    assert port_connection_path.exists()
    assert node_settings_path.exists()
    assert command_contract_path.exists()
    assert param_contract_path.exists()
    assert port_contract_path.exists()
    assert converter_contract_path.exists()
    assert recommendation_contract_path.exists()
    assert rule_action_contract_path.exists()
    assert snakefile_preview_path.exists()
    assert runtime_contract_path.exists()
    assert rule_spec_panel_path.exists()
    assert step_params_editor_path.exists()
    assert subflow_controls_path.exists()
    assert runtime_editor_path.exists()
    assert port_bindings_editor_path.exists()

    model = model_path.read_text(encoding="utf-8")
    design_model = design_model_path.read_text(encoding="utf-8")
    builder_hook = hook_path.read_text(encoding="utf-8")
    builder_ui = ui_path.read_text(encoding="utf-8")
    globals_css = globals_path.read_text(encoding="utf-8")
    history_contract = history_path.read_text(encoding="utf-8")
    graph_node_ui = graph_node_path.read_text(encoding="utf-8")
    graph_canvas_ui = graph_canvas_path.read_text(encoding="utf-8")
    graph_adapter_ui = graph_adapter_path.read_text(encoding="utf-8")
    port_connection_contract = port_connection_path.read_text(encoding="utf-8")
    node_settings_ui = node_settings_path.read_text(encoding="utf-8")
    command_contract = command_contract_path.read_text(encoding="utf-8")
    param_contract = param_contract_path.read_text(encoding="utf-8")
    port_contract = port_contract_path.read_text(encoding="utf-8")
    converter_contract = converter_contract_path.read_text(encoding="utf-8")
    recommendation_contract = recommendation_contract_path.read_text(encoding="utf-8")
    rule_action_contract = rule_action_contract_path.read_text(encoding="utf-8")
    snakefile_preview_ui = snakefile_preview_path.read_text(encoding="utf-8")
    runtime_contract = runtime_contract_path.read_text(encoding="utf-8")
    rule_spec_panel_ui = rule_spec_panel_path.read_text(encoding="utf-8")
    step_params_editor_ui = step_params_editor_path.read_text(encoding="utf-8")
    subflow_controls_ui = subflow_controls_path.read_text(encoding="utf-8")
    runtime_editor_ui = runtime_editor_path.read_text(encoding="utf-8")
    port_bindings_editor_ui = port_bindings_editor_path.read_text(encoding="utf-8")

    assert "export type GeneratedWorkflowDraft" in model
    assert "export type GeneratedWorkflowStepRuntime" in model
    assert "export type GeneratedWorkflowGraphDraft" in model
    assert "export type GeneratedWorkflowGraphNode" in model
    assert "export type GeneratedWorkflowGraphEdge" in model
    assert "export type GeneratedWorkflowGraphNodeMetadata" in model
    assert "WORKFLOW_NODE_SUBFLOW_ID_METADATA_KEY" in model
    assert "WORKFLOW_NODE_SUBFLOW_LABEL_METADATA_KEY" in model
    assert "graphNodeMetadataWithSubflow" in model
    assert "temp?: boolean" in model
    assert "protected?: boolean" in model
    assert "directory?: boolean" in model
    assert "path?: string" in model
    assert "readOutputSemantics" in model
    assert "outputSemanticTags" in model
    assert "steps: []" in model
    assert "steps: first ? [createStepDraft(first, [])] : []" not in model
    assert "createGeneratedWorkflowGraphDraft" in model
    assert "generatedWorkflowDraftToGraphDraft" in model
    assert "graphDraftToGeneratedWorkflowDraft" in model
    assert "metadata: { ...(step.metadata || {}) }" in model
    assert "metadata: { ...(node.metadata || {}) }" in model
    assert "export type GeneratedWorkflowInputBinding" in model
    assert "fromUpload" in model
    assert "fromUpload" not in design_model.split("export function buildWorkflowDesignDraft", 1)[0]
    assert "fromInput" in design_model
    assert "fromStep" in model
    assert "GeneratedWorkflowExposedOutput" in model
    assert "buildWorkflowDesignDraft" in design_model
    assert "readToolRuleTemplate" in model
    readiness = (COMPONENTS / "tool-rule-readiness.ts").read_text(encoding="utf-8")
    assert "tool.ruleSpecDraft" in readiness
    assert "draft?.ruleTemplate" in readiness
    assert "readToolRuleSpecDraft" not in model
    assert "hasRuleAction" not in model
    assert "validateGeneratedWorkflowDraft" in model
    assert "portsCompatible" in model
    assert "portCompatibilityScore" in model
    assert "findCompatibleOutputBinding" in model
    assert "capabilityPortsForTool" not in model
    assert "capabilitySlotForRulePort" not in port_contract
    assert "capabilityPortItemsForTool" not in port_contract
    assert "tool?.capabilities" not in port_contract
    assert "WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE" in model
    assert "WORKFLOW_STEP_INPUT_PORT_UNKNOWN" in model
    assert "declaredInputNames" in model
    assert "WORKFLOW_OUTPUT_ALIAS_DUPLICATE" in model
    assert "WORKFLOW_OUTPUT_TEMP_EXPOSED" in model
    assert "WORKFLOW_STEP_OUTPUT_PATH_REQUIRED" in model
    assert "outputIsExposable" in model
    assert "validateDefaultExposedOutputs" in model
    assert "validateStepCommandPortBindings" in model
    assert "commandPortReferences" in command_contract
    assert "commandRuntimeReferences" in command_contract
    assert "WORKFLOW_STEP_INPUT_TOKEN_UNKNOWN" in command_contract
    assert "WORKFLOW_STEP_INPUT_TOKEN_UNBOUND" in command_contract
    assert "WORKFLOW_STEP_OUTPUT_TOKEN_UNKNOWN" in command_contract
    assert "WORKFLOW_STEP_THREADS_TOKEN_UNBOUND" in command_contract
    assert "WORKFLOW_STEP_RESOURCE_TOKEN_UNKNOWN" in command_contract
    assert "WORKFLOW_STEP_LOG_TOKEN_UNKNOWN" in command_contract
    assert "inputBindings" in command_contract
    assert "runtimeDefaultsForRuleTemplate" in command_contract
    assert "validateStepParamBindings" in model
    assert "validateStepRuntime" in model
    assert "readPortCompatibility" in port_contract
    assert "describePortCompatibility" in port_contract
    assert "HARD_COMPATIBILITY_FIELDS" in port_contract
    assert "ADVISORY_COMPATIBILITY_FIELDS" in port_contract
    assert "normalizedCompatibilityValue" in port_contract
    assert "portCompatibilityScore" in port_contract
    assert "matchedPortCompatibilityFields" in port_contract
    assert "mismatchedPortCompatibilityField" in port_contract
    assert "export function findOneHopPortConverters" in converter_contract
    assert "RulePortConverterCandidate" in converter_contract
    assert "RulePortConverterInsertionRequest" in converter_contract
    assert "confirmationRequired: true" in converter_contract
    assert 'insertionMode: "explicit-user-confirmed"' in converter_contract
    assert "autoInsertionBlockedReasons" in converter_contract
    assert "CONVERTER_CONFIRMATION_REQUIRED_REASON" in converter_contract
    assert "CONVERTER_GRAPH_MUTATION_REQUIRES_USER_ACTION_REASON" in converter_contract
    assert "CONVERTER_TOOL_NOT_WORKFLOW_READY_REASON" in converter_contract
    assert "CONVERTER_DATABASE_RESOURCE_REQUIRED_REASON" in converter_contract
    assert "export function blockedOneHopPortConverterReasons" in converter_contract
    assert "export function buildConverterInsertionPatch" in converter_contract
    assert "generatedWorkflowDraftToGraphDraft" in converter_contract
    assert "graphDraftToGeneratedWorkflowDraft" in converter_contract
    assert "hasStrongPortEvidence(converterInput, output)" in converter_contract
    assert "hasStrongPortEvidence(input, converterOutput)" in converter_contract
    assert "matchedPortCompatibilityFields(input, output)" in converter_contract
    assert 'field !== "type"' in converter_contract
    assert "requiresDatabaseResource(tool)" in converter_contract
    assert "requiredInputs.some" in converter_contract
    assert "buildConverterInsertionPatch" not in model
    assert "converterPath" not in design_model
    assert "COMPATIBILITY_FIELDS" not in model
    assert "portCompatibilityScore as scorePortCompatibility" in model
    assert "portCompatibilityDecision" in recommendation_contract
    assert "compatibilityDecision.matchedFields" in recommendation_contract
    assert "compatibilityDecision.mismatchedField" in recommendation_contract
    assert 'field !== "type"' in recommendation_contract
    assert "COMPATIBILITY_FIELDS" not in recommendation_contract
    assert "export type RulePortRecommendationDecision" in recommendation_contract
    assert "export type RulePortRecommendation" in recommendation_contract
    assert "decision: RulePortRecommendationDecision" in recommendation_contract
    assert "hardChecks: string[]" in recommendation_contract
    assert "evidence: string[]" in recommendation_contract
    assert "confidence: number" in recommendation_contract
    assert "explainPortRecommendation" in recommendation_contract
    assert "isAutoBindablePortRecommendation" in recommendation_contract
    assert "export type RulePortEdgeAudit" in recommendation_contract
    assert "autoEdgeAudit" in recommendation_contract
    assert "manualEdgeAudit" in recommendation_contract
    assert 'source: "auto"' in recommendation_contract
    assert 'source: "manual"' in recommendation_contract
    assert "类型证据不足，保留为手动连接" in recommendation_contract
    assert '"recommended"' in recommendation_contract
    assert '"blocked"' in recommendation_contract
    assert '"ambiguous"' in recommendation_contract
    assert "validateRuleActionContract" in model
    assert "isAutoBindablePortRecommendation" in model
    assert "explainPortRecommendation(input, output)" in model
    assert "export function readToolRuleTemplate" in model
    assert "WORKFLOW_RULE_ACTION_REQUIRED" in rule_action_contract
    assert "WORKFLOW_RULE_ACTION_CONFLICT" in rule_action_contract
    assert '["commandTemplate", "wrapper", "script", "module"]' in rule_action_contract
    assert "workflowDesignDraftToGraphDraft" in design_model
    assert "audit?: RulePortEdgeAudit" in model
    assert "audit: edge.audit" in model
    assert "audit: binding.audit" in model
    assert "contractVersion:" in design_model
    assert "nodes: graphDraft.nodes.map" in design_model
    assert "edges: graphDraft.edges.map" in design_model
    assert "audit: workflowDesignEdgeAuditForDraft(edge.audit)" in design_model
    assert "function workflowDesignEdgeAuditForDraft" in design_model
    assert "hardChecks: JSON.stringify(audit.hardChecks)" in design_model
    assert "evidence: JSON.stringify(audit.evidence)" in design_model
    assert "WORKFLOW_DESIGN_EDGE_AUDIT_KEYS" in design_model
    assert "workflowDesignValidateScalarRecord" in design_model
    assert "Object.entries(audit).find" in design_model
    assert "!WORKFLOW_DESIGN_EDGE_AUDIT_KEYS.has(key)" in design_model
    assert "function workflowDesignAuditStringArray" in design_model
    assert "JSON.parse(value)" in design_model
    assert "if (audit === undefined) return undefined" in design_model
    assert 'typeof audit !== "object" || Array.isArray(audit)' in design_model
    assert "outputs: graphDraft.outputs.map" in design_model
    assert "runtime: workflowDesignRuntimeForDraft(node.runtime)" in design_model
    assert "function workflowDesignRuntimeForDraft" in design_model
    assert "resources: { ...(runtime.resources || {}) }" in design_model
    assert "schedulerResources: { ...(runtime.schedulerResources || {}) }" in design_model
    assert "WORKFLOW_DESIGN_NODE_INPUT_EDGE_UNSUPPORTED" in design_model
    assert "WORKFLOW_DESIGN_INPUT_ROLE_UNKNOWN" in design_model
    assert '"fromInput" in binding' not in design_model
    assert "existingDraft?: WorkflowDesignDraft" in design_model
    assert "description: existingDraft?.metadata.description" in design_model
    assert "tags: existingDraft?.metadata.tags" in design_model
    assert "item.id === node.id && item.toolRevisionId === node.toolRevisionId" in design_model
    assert "existingNodeOutputEntries" in design_model
    assert "exposedOutputNames.has(outputName)" in design_model
    assert "metadata: { ...(existingNode?.metadata || {}), ...(node.metadata || {}) }" in design_model
    assert "metadata: node.metadata || {}" in design_model
    assert "provenance: existingNode?.provenance || { source: \"workflow-builder\" }" in design_model
    assert "metadata: existingOutput?.metadata || {}" in design_model
    assert "provenance: existingDraft?.provenance || { createdBy: \"workflow-builder\" }" in design_model
    assert "return binding as WorkflowDesignInputBinding" not in design_model
    assert "ruleSpecDraft: readToolRuleSpecDraft(tool)" not in model
    assert "resourceBindings" in design_model
    assert "databases" not in model
    assert "WORKFLOW_STEP_PARAM_REQUIRED" in param_contract
    assert "commandParamNames" in param_contract
    assert "export function validateStepRuntime" in runtime_contract
    assert "WORKFLOW_STEP_THREADS_INVALID" in runtime_contract
    assert "WORKFLOW_STEP_RESOURCES_INVALID" in runtime_contract
    assert "WORKFLOW_STEP_LOG_INVALID" in runtime_contract

    assert "useReducer" in builder_hook
    assert "useGeneratedWorkflowBuilder" in builder_hook
    assert "graphDraft" in builder_hook
    assert "findCompatibleOutputBinding" in builder_hook
    assert "validation" in builder_hook
    assert "resourceBindings" in builder_hook
    assert "setStepRuntime" in builder_hook
    assert "audit: manualEdgeAudit()" in builder_hook
    assert "buildConverterInsertionPatch" in builder_hook
    assert "insertConverter" in builder_hook
    assert "type: \"insert_converter\"" in builder_hook
    assert "setNodeSubflow" in builder_hook
    assert "type: \"set_node_subflow\"" in builder_hook
    assert "graphNodeMetadataWithSubflow" in builder_hook
    assert "WorkflowEditorHistory" in history_contract
    assert "commitWorkflowEditorHistory" in history_contract
    assert "undoWorkflowEditorHistory" in history_contract
    assert "redoWorkflowEditorHistory" in history_contract
    assert "replaceWorkflowEditorHistory" in history_contract
    assert "graphHistory" in builder_hook
    assert "canUndo" in builder_hook
    assert "canRedo" in builder_hook
    assert "undo: () => dispatch({ type: \"undo_graph\" })" in builder_hook
    assert "redo: () => dispatch({ type: \"redo_graph\" })" in builder_hook
    assert "commitWorkflowEditorHistory(state.graphHistory" in builder_hook
    assert "graphHistoryToolsAvailable" in builder_hook
    assert "graphToolsAvailable" in builder_hook
    assert "replaceWorkflowEditorHistory(state.graphHistory, state.graphHistory.present)" in builder_hook
    assert "graphHistory" not in model
    assert "searchQuery" not in model
    assert "graphZoom" not in model
    assert "graphHistory" not in design_model
    assert "searchQuery" not in design_model
    assert "graphZoom" not in design_model
    assert "graphHistory" not in api
    assert "evaluateGeneratedWorkflowPortConnection" in port_connection_contract
    assert "portsCompatible(input, output)" in port_connection_contract
    assert "wouldCreateCycle" in port_connection_contract
    assert "manualCanvasEdgeAudit" in port_connection_contract
    assert "WORKFLOW_GRAPH_CONNECTION_INCOMPATIBLE" in port_connection_contract
    assert "WORKFLOW_GRAPH_CONNECTION_CYCLE" in port_connection_contract

    assert "GeneratedWorkflowBuilder" in builder_ui
    assert "WorkflowGraphWorkbench" in builder_ui
    assert "GeneratedWorkflowNodeSettings" in builder_ui
    assert "GeneratedWorkflowSubflowControls" in builder_ui
    assert "onChange={builder.setNodeSubflow}" in builder_ui
    assert "graphNodeSubflowLabel" in subflow_controls_ui
    assert "onBlur={commit}" in subflow_controls_ui
    assert "子流程" in subflow_controls_ui
    assert "StepParamsEditor" in builder_ui
    assert "function StepParamsEditor" not in builder_ui
    assert "export function StepParamsEditor" in step_params_editor_ui
    assert "coerceParamValue" in step_params_editor_ui
    assert "export function GeneratedWorkflowNodeSettings" in node_settings_ui
    assert "节点设置" in node_settings_ui
    assert "节点 ID" in node_settings_ui
    assert "onStepIdChange" in node_settings_ui
    assert "onStepToolChange" in node_settings_ui
    assert "GeneratedWorkflowRuleSpecPanel" in builder_ui
    assert "GeneratedWorkflowSnakefilePreview" in builder_ui
    assert "GeneratedWorkflowGraphSnakefilePreview" in builder_ui
    assert "selectedNode.params" in builder_ui
    assert "export function GeneratedWorkflowRuleSpecPanel" in rule_spec_panel_ui
    assert "commandTemplate" in rule_spec_panel_ui
    assert "ruleTemplateForTool" in rule_spec_panel_ui
    assert "moduleActionDisplay" in rule_spec_panel_ui
    assert "module:" in rule_spec_panel_ui
    assert "readRuleSpecProvenance" in rule_spec_panel_ui
    assert "ruleSpecDraft" in rule_spec_panel_ui
    assert "wrapperRef" in rule_spec_panel_ui
    assert "wrapperPath" in rule_spec_panel_ui
    assert "wrapperIdentifier" in rule_spec_panel_ui
    assert "parseWrapperIdentifier" in rule_spec_panel_ui
    assert "Object.keys(objectValue(template.module)).length > 0" in rule_spec_panel_ui
    assert "snakemakeWrappers" in rule_spec_panel_ui
    assert "官方 wrapper 已锁定" in rule_spec_panel_ui
    assert "environment" in rule_spec_panel_ui
    assert "RuleSpecContractSummary" in rule_spec_panel_ui
    assert "输入端口" in rule_spec_panel_ui
    assert "输出端口" in rule_spec_panel_ui
    assert "参数默认值" in rule_spec_panel_ui
    assert "调度资源 / log" in rule_spec_panel_ui
    assert "formatRuleOutputSemantics" in rule_spec_panel_ui
    assert "export function GeneratedWorkflowSnakefilePreview" in snakefile_preview_ui
    assert "export function GeneratedWorkflowGraphSnakefilePreview" in snakefile_preview_ui
    assert "Snakefile preview" in snakefile_preview_ui
    assert "Workflow Snakefile preview" in snakefile_preview_ui
    assert "graphPreviewLines" in snakefile_preview_ui
    assert "rulePreviewLines" in snakefile_preview_ui
    assert "rule all:" in snakefile_preview_ui
    assert "inputPathForRulePort" in snakefile_preview_ui
    assert "renderOutputValue" in snakefile_preview_ui
    assert "shell:" in snakefile_preview_ui
    assert "wrapper:" in snakefile_preview_ui
    assert "script:" in snakefile_preview_ui
    assert "module " in snakefile_preview_ui
    assert "use rule" in snakefile_preview_ui
    assert "conda:" in snakefile_preview_ui
    assert "hasRunnableCondaEnvironment" in snakefile_preview_ui
    assert "tool?.selectedPackageSpec || tool?.packageSpec" in snakefile_preview_ui
    assert "GeneratedWorkflowRuntimeEditor" in builder_ui
    assert "GeneratedWorkflowPortBindingsEditor" in builder_ui
    assert "function PortBindingsEditor" not in builder_ui
    assert "export function GeneratedWorkflowPortBindingsEditor" in port_bindings_editor_ui
    assert "PortBindingRow" in port_bindings_editor_ui
    assert "PortBindingValueEditor" in port_bindings_editor_ui
    assert "defaultBinding(nextType, recommendedOutputCandidates)" in port_bindings_editor_ui
    assert "defaultBinding(nextType, compatibleOutputCandidates)" not in port_bindings_editor_ui
    assert "recommendedCandidates[0]" in port_bindings_editor_ui
    assert "manualOnlyCandidate" in port_bindings_editor_ui
    assert "RuleGraphNodeCard" in graph_canvas_ui
    assert "const nodeIssues = validationIssues.filter" in graph_canvas_ui
    assert "validationIssues: nodeIssues" in graph_canvas_ui
    assert "validationIssues={data.validationIssues}" in graph_canvas_ui
    assert "validationIssues={builder.validation.errors}" in builder_ui
    assert "GeneratedWorkflowGraphCanvas" in builder_ui
    assert "export function GeneratedWorkflowGraphCanvas" in graph_canvas_ui
    assert '@import "@xyflow/react/dist/style.css";' in globals_css
    assert "graphSearchQuery" in builder_ui
    assert "graphLayoutRevision" in builder_ui
    assert "builder.undo" in builder_ui
    assert "builder.redo" in builder_ui
    assert "searchQuery={graphSearchQuery}" in builder_ui
    assert "layoutRevision={graphLayoutRevision}" in builder_ui
    assert "onBindInput={builder.setInputBinding}" in builder_ui
    assert "@xyflow/react" in graph_canvas_ui
    assert "ReactFlow" in graph_canvas_ui
    assert "graphNodeSubflowId" in graph_canvas_ui
    assert "graphNodeSubflowLabel" in graph_canvas_ui
    assert "buildSubflowGroupNodes" in graph_canvas_ui
    assert "WorkflowSubflowGroupNode" in graph_canvas_ui
    assert "SUBFLOW_GROUP_NODE_PREFIX" in graph_canvas_ui
    assert "subflowGroup" in graph_canvas_ui
    assert "Background" in graph_canvas_ui
    assert "Controls" in graph_canvas_ui
    assert "MiniMap" in graph_canvas_ui
    assert "applyNodeChanges" in graph_canvas_ui
    assert "isValidConnection" in graph_canvas_ui
    assert "onConnect" in graph_canvas_ui
    assert "onConnectEnd" in graph_canvas_ui
    assert "onEdgesChange" in graph_canvas_ui
    assert "sourceHandle" in graph_adapter_ui
    assert "targetHandle" in graph_adapter_ui
    assert "MarkerType.ArrowClosed" in graph_canvas_ui
    assert "evaluateGeneratedWorkflowPortConnection" in graph_canvas_ui
    assert "reactFlowConnectionToGraphConnection" in graph_canvas_ui
    assert "generated-workflow-react-flow-adapter" in graph_canvas_ui
    assert "data-workflow-react-flow-canvas" in graph_canvas_ui
    assert "fitView" in graph_canvas_ui
    assert "matchedGraphNodeIds" in graph_canvas_ui
    assert "无法添加工具：拖拽数据缺少工具修订 ID。" in graph_canvas_ui
    assert "无法添加工具：画布尚未初始化。" in graph_canvas_ui
    assert "nodeIssues.length === 0" in graph_canvas_ui
    assert "ring-2 ring-amber-300" in graph_canvas_ui
    assert "从工具库添加 RuleSpec 节点" in graph_canvas_ui
    assert "edges={edges}" in builder_ui
    assert "function RuleGraphNodeCard" not in builder_ui
    assert "export function RuleGraphNodeCard" in graph_node_ui
    assert "graphNodeSubflowLabel" in graph_node_ui
    assert "Handle" in graph_node_ui
    assert "Position.Left" in graph_node_ui
    assert "Position.Right" in graph_node_ui
    assert "isConnectableStart" in graph_node_ui
    assert "isConnectableEnd" in graph_node_ui
    assert "RulePortColumn" in graph_node_ui
    assert "GeneratedWorkflowValidationIssue" in graph_node_ui
    assert "unknownInputIssues" in graph_node_ui
    assert "data-port-error" in graph_node_ui
    assert "data-node-state" in graph_node_ui
    assert "data-rule-node-id" in graph_node_ui
    assert "rule-graph-handle-" in graph_node_ui
    assert "rule-graph-port-" in graph_node_ui
    assert "未知输入端口" in graph_node_ui
    assert "portBindingState" in graph_node_ui
    assert "outputFanoutCount" in graph_node_ui
    assert "data-port-state" in graph_node_ui
    assert "已连接" in graph_node_ui
    assert "待绑定" in graph_node_ui
    assert "fan-out" in graph_node_ui
    assert "输入端口" in graph_node_ui
    assert "输出端口" in graph_node_ui
    assert "data-port-direction" in graph_node_ui
    assert "export function GeneratedWorkflowRuntimeEditor" in runtime_editor_ui
    assert "线程" in runtime_editor_ui
    assert "调度资源" in runtime_editor_ui
    assert "日志" in runtime_editor_ui
    assert "updateLog" in runtime_editor_ui
    assert "logDefaults" in runtime_editor_ui
    assert "namedLogEntries" in runtime_editor_ui
    assert "updateLogPath" in runtime_editor_ui
    assert "ruleTemplateForTool" in runtime_editor_ui
    assert "未声明 log" in runtime_editor_ui
    assert "builder.graphDraft.nodes" in builder_ui
    assert "defaultThreadsForTemplate" in runtime_editor_ui
    assert "schedulerResourceDefaults(template)" in runtime_editor_ui
    assert "ruleSpecResourceDefaults" in runtime_editor_ui
    assert "template.resources" in runtime_editor_ui
    assert "selectedNodeId" in builder_ui
    assert "工具库" in builder_ui
    assert "RulePaletteCard" in builder_ui
    assert "规则节点库" not in builder_ui
    assert "ruleActionLabelForTool" in builder_ui
    assert "rulePortsLabelForTool" in builder_ui
    assert "ruleEnvironmentLabelForTool" in builder_ui
    assert "RuleSpec 节点" in builder_ui
    assert "运行环境" in builder_ui
    assert "Inspector" in builder_ui
    assert "GeneratedWorkflowPortBindingsEditor" in builder_ui
    assert "function InputBindingRow" not in builder_ui
    assert "builder.draft.steps.map((step, index)" not in builder_ui
    assert "Step {index + 1}" not in builder_ui
    assert "inputCount={inputCount}" in builder_ui
    assert "上传文件" in port_bindings_editor_ui
    assert "inputCount={state.generatedInputCount}" in detail_page
    assert "removeGraphEdge" in builder_ui
    assert "builder.removeStep(selectedNode.id)" in builder_ui
    assert "删除节点" in builder_ui
    assert "删除连线" in builder_ui
    assert "EdgeAuditBadge" in builder_ui
    assert 'data-testid="workflow-graph-edge-row"' in builder_ui
    assert 'data-workflow-edge-id={edge.id}' in builder_ui
    assert 'data-workflow-edge-audit-source={edge.audit?.source || "none"}' in builder_ui
    assert 'data-testid="workflow-graph-edge-delete"' in builder_ui
    assert 'data-testid="workflow-graph-edge-audit"' in builder_ui
    assert "自动推荐" in builder_ui
    assert "手动连接" in builder_ui
    assert "edgeForInput" in port_bindings_editor_ui
    assert "compatibleOutputCandidates" in port_bindings_editor_ui
    assert "recommendedOutputCandidates" in port_bindings_editor_ui
    assert "candidate.recommendation?.decision === \"recommended\"" in port_bindings_editor_ui
    assert "compatibilityReason" in port_bindings_editor_ui
    assert "explainPortRecommendation" in port_bindings_editor_ui
    assert "recommendation.evidence" in port_bindings_editor_ui
    assert "recommendation.confidence" in port_bindings_editor_ui
    assert "推荐原因" in port_bindings_editor_ui
    assert "推荐证据" in port_bindings_editor_ui
    assert "手动连接提示" in port_bindings_editor_ui
    assert "confidence" in port_bindings_editor_ui
    assert "compatibilityScore" in port_bindings_editor_ui
    assert "converterSuggestionsForInput" in port_bindings_editor_ui
    assert "一跳转换建议" in port_bindings_editor_ui
    assert "需确认，不会自动插入" in port_bindings_editor_ui
    assert "确认插入转换" in port_bindings_editor_ui
    assert "suggestion.insertionMode" in port_bindings_editor_ui
    assert "suggestion.autoInsertionBlockedReasons" in port_bindings_editor_ui
    assert "suggestion.evidence" in port_bindings_editor_ui
    assert "onInsertConverter" in port_bindings_editor_ui
    assert "builder.insertConverter" in builder_ui
    assert "semanticPortPlan={semanticPortPlan}" in builder_ui
    assert "onInsertConverter={builder.insertConverter}" in builder_ui
    assert "sourceStepId: suggestion.sourceStepId" not in builder_ui
    assert "targetStepId: selectedNode.id" not in builder_ui
    assert "backendPlanConverterInsertionForSuggestion" in port_bindings_editor_ui
    assert "onInsertConverter(backendInsertion.request)" in port_bindings_editor_ui
    assert "保存并验证后可使用后端转换建议" in port_bindings_editor_ui
    assert "tools={tools}" in builder_ui
    assert "应用推荐" in port_bindings_editor_ui
    assert "autoEdgeAudit(recommended.recommendation)" in port_bindings_editor_ui
    assert "（推荐）" in port_bindings_editor_ui
    assert "解绑" in port_bindings_editor_ui
    assert "Select" in port_bindings_editor_ui
    assert "Alert" in builder_ui
    assert "fromStep" in builder_ui
    assert "portsCompatible" in port_bindings_editor_ui
    assert "不兼容" in port_bindings_editor_ui
    assert "OutputExposureEditor" in builder_ui
    assert "script:" in builder_ui
    assert "module:" in builder_ui

    assert "buildGeneratedRunSpec" not in page_model
    assert "submitWorkflowDesignRun" in api
    assert "compileWorkflowDesignDraft" in api
    assert "/compile" in api
    assert "WorkflowDesignCompileResult" in api
    assert "workflowRevisionId?: string" in design_model
    assert "export type WorkflowRevisionSummary" in design_model
    assert "WorkflowRevision" in builder_ui
    assert "result.workflowRevisionId" in builder_ui
    assert "workflowRevisionId: string" in api
    assert "WORKFLOW_REVISION_ID_REQUIRED" in api
    assert "workflowRevisionId: normalizedWorkflowRevisionId" in api
    assert "currentWorkflowDesignCompileResult?.workflowRevisionId" in page_hook
    assert "workflowDesignDraftsCacheKey(options.serverId)" in api
    assert "requireWorkflowDesignPlannedInputs" in api
    assert "role: plannedInputs[index].role" in api
    assert "filename: plannedInputs[index].filename" in api
    upload_file_body = _function_body(api, "uploadWorkflowFile")
    workflow_submit_body = _function_body(api, "submitWorkflowDesignRun")
    pipeline_submit_body = _function_body(api, "submitPipelineWorkflowRun")
    assert workflow_submit_body.index("const plannedInputs = requireWorkflowDesignPlannedInputs(plannedRunSpec)") < workflow_submit_body.index("uploadWorkflowFile(file, server.serverId)")
    assert workflow_submit_body.index("plannedInputs.length !== files.length") < workflow_submit_body.index("uploadWorkflowFile(file, server.serverId)")
    assert "plannedInputs.length !== uploads.length" not in workflow_submit_body
    assert "filename: upload.filename" not in workflow_submit_body
    assert 'typeof roleValue !== "string"' in api
    assert 'typeof filenameValue !== "string"' in api
    assert "serverId?: string" in api
    assert "serverId ? { serverId } : {}" in upload_file_body
    assert "uploadWorkflowFile(file, server.serverId)" in workflow_submit_body
    assert "uploadWorkflowFile(file, server.serverId)" in pipeline_submit_body
    assert "WORKFLOW_DESIGN_RUN_INPUTS_MISMATCH" in api
    assert "WorkflowDesignPlan" in api
    assert "WORKFLOW_DESIGN_PLAN_RUN_SPEC_REQUIRED" in api
    assert "workflowDesign.draftId" in api
    assert "workflowDesign.revision" in api
    assert "useGeneratedWorkflowBuilder" in page_hook
    assert "addRecommendedWorkflowTool" in page_hook
    assert "fetchWorkflowTools({ forceRefresh: true })" in page_hook
    assert "generatedBuilder.addStep(toolRevisionId, options)" in page_hook
    assert "setTools(nextTools)" in page_hook
    assert "buildWorkflowDesignDraft" in page_hook
    assert "existingDraft: activeWorkflowDesignDraft?.draft" in page_hook
    assert "saveAndValidateGeneratedWorkflowDesign" in page_hook
    assert "currentWorkflowDesignPlan?.valid === true" in page_hook
    assert "currentWorkflowDesignPlan ? workflowDesignCompileResult : null" in page_hook
    assert "workflowDesignCompileResult: currentWorkflowDesignCompileResult" in page_hook
    assert "currentWorkflowDesignDraftError" in page_hook
    assert "workflowErrorMessage(err, \"WORKFLOW_DESIGN_DRAFT_INVALID\")" in page_hook
    assert "workflowDesignError: currentWorkflowDesignDraftError || workflowDesignError" in page_hook
    assert "catch {\n      return null;" not in page_hook
    assert "workflowDesignPlanSignature !== currentWorkflowDesignSignature" in page_hook
    assert "stableWorkflowDesignStringify(draft)" in page_hook
    assert "function stableWorkflowDesignStringify" in page_hook
    assert "Object.keys(value).sort()" in page_hook
    assert "return JSON.stringify(draft)" not in page_hook
    assert "setWorkflowDesignPlanSignature(\"\")" in page_hook
    assert "const plan = currentWorkflowDesignPlan" in page_hook
    assert "const plan = await saveAndValidateGeneratedWorkflowDesign()" not in page_hook
    assert "compileGeneratedWorkflowDesign" in page_hook
    assert "workflowDesignCompileResult" in page_hook
    assert "fetchWorkflowDesignDrafts({ ...options, serverId })" in page_hook
    assert 'serverResult.status === "rejected"' in page_hook
    assert "读取工作流运行服务失败" in page_hook
    assert 'serverResult.status === "fulfilled" ? serverResult.value.serverId : ""' not in page_hook
    assert "catch {\n        setWorkflowDesignDrafts([])" not in page_hook
    assert "WORKFLOW_DESIGN_DRAFT_NOT_FOUND: ${draftId}" in page_hook
    assert "throw new Error(message)" in page_hook
    assert "编译导出" in builder_ui
    assert "WorkflowDesignCompileSummary" in builder_ui
    assert "GeneratedWorkflowBuilder" in detail_page
    assert "onAddRecommendedTool={state.addRecommendedWorkflowTool}" in detail_page
    assert "onCompile" in detail_page
    assert "generatedBuilder" in page_ui
    assert "!isGeneratedToolRun ? dagPreview : null" in page_ui


def test_tools_page_surfaces_snakemake_wrapper_matches() -> None:
    model = _tools_page_model_source()
    ui = _tools_page_ui_source()
    api = (COMPONENTS / "tools-page-api.ts").read_text(encoding="utf-8")

    assert "SnakemakeWrapperMatch" in model
    assert "snakemakeWrappers" in model
    assert "snakemakeWrapperCount" in model
    assert "ruleSpecDraft" in model
    assert "syncRuleSpecDraftPackageLock" in model
    assert "applySelectedPackageLock" in model
    assert "WrapperBadge" in ui
    assert "Snakemake wrapper" in ui
    assert "RulePortPreview" in ui
    assert "rulePortItems" in ui
    assert "hasRuleAction" in ui
    assert "formatRulePortLabel" in ui
    assert "输入端口" in ui
    assert "输出端口" in ui
    assert "生成自定义 RuleSpec" in ui
    assert "snakemakeWrappers" in api
    assert "ruleSpecDraft" in api
    hook = (COMPONENTS / "use-tools-page-state.ts").read_text(encoding="utf-8")
    assert "const baseSelected" in hook
    assert "applySelectedPackageLock(baseSelected" in hook


def test_workflow_sample_data_upload_uses_long_running_timeout() -> None:
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    sample_api = (FIRST_RUN_API / "workflow-sample-data-api.ts").read_text(encoding="utf-8")
    sample_panel = (FIRST_RUN_COMPONENTS / "workflow-first-run-sample-submit.tsx").read_text(encoding="utf-8")

    assert "WORKFLOW_SAMPLE_DATA_TIMEOUT_MS" in api
    assert "timeoutMs: WORKFLOW_SAMPLE_DATA_TIMEOUT_MS" in api
    assert "/api/v1/workflow-sample-data/" in api
    assert "body: { serverId }" in api
    assert "integrityStatus?: \"passed\" | string" in model
    assert "expectedSha256?: string" in model
    assert "expectedSizeBytes?: number" in model
    assert "export type WorkflowSampleDataStatus" in sample_api
    assert "fetchWorkflowSampleDataStatus" in sample_api
    assert "/api/v1/workflow-sample-data/${encodeURIComponent(normalizedPipelineId)}/status" in sample_api
    assert "useWorkflowSampleDataStatus" in sample_panel
    assert "first-run-sample-data-status" in sample_panel
    assert "data-sample-data-status={summary.state}" in sample_panel
    assert "item.cacheStatus" in sample_panel
