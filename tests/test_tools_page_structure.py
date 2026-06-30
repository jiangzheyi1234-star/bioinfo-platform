from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _component_source(*names: str) -> str:
    return "\n".join((COMPONENTS / name).read_text(encoding="utf-8") for name in names)


def _tools_page_model_source() -> str:
    return _component_source(
        "tools-page-core-model.ts",
        "tools-page-catalog-model.ts",
        "tools-page-model.ts",
    )


def _tools_page_ui_source() -> str:
    return _component_source(
        "tools-page-ui.tsx",
        "tools-page-catalog-quality-strip.tsx",
    )


def _type_body(source: str, name: str) -> str:
    start = source.index(f"export type {name} = {{")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    raise AssertionError(f"type body not found: {name}")


def _function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    raise AssertionError(f"function body not found: {name}")


def test_tools_page_has_focused_support_modules() -> None:
    api = (COMPONENTS / "tools-page-api.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-tools-page-state.ts").read_text(encoding="utf-8")
    library = (COMPONENTS / "tools-page-library-section.tsx").read_text(encoding="utf-8")
    model = _tools_page_model_source()
    package_lock = (COMPONENTS / "tools-page-package-lock.ts").read_text(encoding="utf-8")
    completion = (COMPONENTS / "tools-page-rule-spec-completion.ts").read_text(encoding="utf-8")
    editor = (COMPONENTS / "tools-page-rule-spec-editor.tsx").read_text(encoding="utf-8")
    readiness = (COMPONENTS / "tool-rule-readiness.ts").read_text(encoding="utf-8")
    ui = _tools_page_ui_source()
    wrapper_selector = (COMPONENTS / "tools-page-wrapper-selector.tsx").read_text(encoding="utf-8")
    task_context = (COMPONENTS / "tool-prepare-task-context.tsx").read_text(encoding="utf-8")
    task_bar = (COMPONENTS / "tool-prepare-task-bar.tsx").read_text(encoding="utf-8")
    page = (COMPONENTS / "tools-page.tsx").read_text(encoding="utf-8")
    runner_repair = (COMPONENTS / "workflow-runner-repair-state.tsx").read_text(encoding="utf-8")
    route_page = (ROOT / "apps/web/app/workflows/tools/page.tsx").read_text(encoding="utf-8")
    recommendation_ui = (COMPONENTS / "generated-workflow-tool-recommendations.tsx").read_text(encoding="utf-8")

    assert "export async function fetchAddedTools" in api
    assert "export async function searchToolCapabilities" in api
    assert "export async function fetchSnakemakeWrapperCatalog" in api
    assert "/api/v1/tool-capabilities/snakemake-wrappers?page=1&pageSize=1" in api
    assert "export async function fetchToolProfileCatalog" in api
    assert "/api/v1/tool-capabilities/tool-profiles?page=1&pageSize=50" in api
    assert "export async function fetchCapabilityGraphSnapshot" in api
    assert "/api/v1/tool-capabilities/capability-graph" in api
    assert "export async function searchToolCandidates" not in api
    assert "/api/v1/tool-capabilities/candidates" not in api
    assert "export async function createToolPrepareJob" in api
    assert "export async function prepareToolValidationQueue" in api
    assert "/api/v1/tool-capabilities/validation-queue/prepare" in api
    assert "export async function fetchToolPrepareJob" in api
    assert "export async function updateToolRuleTemplate" in api
    assert "/api/v1/tools/prepare-jobs" in api
    assert "/api/v1/tools/${encodeURIComponent(id)}/rule-template" in api
    assert "invalidateWorkflowToolCaches" in api
    assert "invalidateAsyncCachePrefix(\"workflow:\")" in api
    assert api.count("invalidateWorkflowToolCaches();") >= 3
    assert "TOOL_SEARCH_REQUEST_TIMEOUT_MS" in api
    assert "timeoutMs: TOOL_SEARCH_REQUEST_TIMEOUT_MS" in api
    assert "export function useToolsPageState" in hook
    assert "items.flatMap(installableCandidateItem)" in hook
    assert "function installableCandidateItem" in hook
    assert "const payload = candidate.preparePayload" in _function_body(hook, "installableCandidateItem")
    assert "candidateId: candidate.candidateId" in _function_body(hook, "installableCandidateItem")
    assert "sourceRef: candidate.sourceRef" in _function_body(hook, "installableCandidateItem")
    assert "initialQuery" in hook
    assert "const initialSearchQuery = initialQuery || searchParams.get(\"q\") || \"\"" in page
    assert "useToolsPageState(initialSearchQuery)" in page
    assert "useWorkflowRunnerRepairState()" in page
    assert "WorkflowRunnerRepairNotice controller={runnerRepair} mode=\"compact\"" in page
    assert "requestLocalApiJson" not in page
    assert "data-testid=\"workflow-runner-repair-notice\"" in runner_repair
    assert "diagnosticsOnly={compact}" in runner_repair
    assert "const catalogQualityStrip = (" in page
    assert page.count("{catalogQualityStrip}") == 2
    assert "useSearchParams" in page
    assert 'import { Suspense } from "react"' in route_page
    assert "export default function Page" in route_page
    assert "<Suspense fallback={null}>" in route_page
    assert "<ToolsPage />" in route_page
    assert 'useState<"library" | "search">(() => initialQuery ? "search" : "library")' in hook
    assert "fetchSnakemakeWrapperCatalog" in hook
    assert "wrapperCatalog" in hook
    assert "wrapperCatalogLoading" in hook
    assert "wrapperCatalogError" in hook
    assert "setWrapperCatalogError" in hook
    assert "editingRuleSpecToolId" in hook
    assert "ruleSpecSavingId" in hook
    assert "checkingToolId" in hook
    assert "preparingToolIds" in hook
    assert "checkTool" in hook
    assert "saveToolRuleTemplate" in hook
    assert "export type ToolSearchItem" in model
    assert "candidateId?: string" in model
    assert "candidateKind?: string" in model
    assert "qualityTier?: ToolCandidateQualityTier" in model
    assert "sourceRef?: ToolCandidateSourceRef" in model
    assert "export type ToolCandidateSourceRef" in model
    assert "export type ToolCandidateQualityTier" in model
    assert "export type ToolCatalogQualityCounts" in model
    assert "export type SnakemakeWrapperCatalogResponse" in model
    assert "export type ToolProfileCatalog" in model
    assert "export type ToolProfileCatalogResponse" in model
    assert "export type ToolProfileWrapperEvidence" in model
    assert "snakemakeWrappers?: ToolProfileWrapperEvidence[]" in model
    assert "snakemakeWrapperCount?: number" in model
    assert "export type ToolCandidatePreparePayload" in model
    assert "profileId?: string" in _type_body(model, "ToolCandidatePreparePayload")
    assert "packageName?: string" in _type_body(model, "ToolCandidatePreparePayload")
    assert "validationTarget?: string" in _type_body(model, "ToolCandidatePreparePayload")
    assert "preparePayload?: ToolCandidatePreparePayload" in _type_body(model, "ToolSearchItem")
    assert "preparePayload?: ToolCandidatePreparePayload" in _type_body(model, "ToolProfileCandidate")
    assert "preparePayload?: ToolCandidatePreparePayload" in _type_body(model, "ToolCatalogValidationQueueItem")
    assert "export type ToolCandidateCatalog" in model
    assert "export type ToolCandidateCatalogResponse" in model
    assert "sourceCounts: ToolCandidateSourceCounts" in model
    assert "export type ToolCandidateSourceCounts" in model
    assert "profileId: string" in model
    assert "preferredWrapperPaths: string[]" in model
    assert "contractState?: ToolContractState | string" in model
    assert "localIndexAvailable?: boolean" in model
    assert "export type RuleSpecTemplate" in model
    assert "export type RuleSpecEnvironment" in model
    assert "artifactCount?: string" in model
    assert "artifactNames?: string" in model
    assert "evidenceType?: string" in model
    assert "databaseId?: string" in model
    assert "templateId?: string" in model
    assert "package?: ToolContractPackage" in model
    assert "export type ToolContractPackage" in model
    assert "productionEnabled?: boolean" in model
    assert "ruleSpec?: ToolContractRuleSpec" in model
    assert "environment?: ToolContractEnvironment" in model
    assert "smokeTest?: ToolContractSmokeTest" in model
    assert "export type ToolContractRuleSpec" in model
    assert "export type ToolContractEnvironment" in model
    assert "export type ToolContractSmokeTest" in model
    assert "TOOL_PACKAGE_VERSION_REQUIRED" in model
    assert "TOOL_PACKAGE_VERSION_MISMATCH" in model
    assert "TOOL_PACKAGE_SOURCE_MISMATCH" in model
    assert "TOOL_PACKAGE_NAME_MISMATCH" in model
    assert "TOOL_RULE_SMOKE_TEST_REQUIRED" in model
    assert "WORKFLOW_TOOL_NOT_READY" in model
    assert "OUTPUT_ARTIFACT_MISSING" in model
    assert "artifactCount" in library
    assert "artifactNames" in library
    assert "evidenceType" in library
    assert "databaseId" in library
    assert "templateId" in library
    assert "CapabilityBundleStatusChip" in library
    assert "tool.capabilityBundleStatus" in library
    assert "blockedReasons" in library
    assert "nextAction" in library
    assert "schedulerResources?: Record" in model
    assert "export type RuleSpecLock" in model
    assert "ruleTemplate?: RuleSpecTemplate" in model
    assert "module?: RuleSpecModule" in model
    assert "moduleAssets?: Array<{ path: string; content: string }>" in model
    assert "lock?: RuleSpecLock" in model
    assert "packageSpecLocked" in model
    assert "export function packageSpecLocked" in package_lock
    assert "applySelectedWrapperLock" in model
    assert "buildExecutableRuleSpecForSelectedTool" in model
    assert "isExecutableRuleSpec" in model
    assert "missingRuleSpecFields" in model
    assert "export function applySelectedWrapperLock" in completion
    assert "export function buildExecutableRuleSpecForSelectedTool" in completion
    assert "export function isExecutableRuleSpec" in completion
    assert "export function missingRuleSpecFields" in completion
    assert "缺少输出文件路径" in completion
    assert "wrapper ref 不能使用 latest/master" in completion
    assert "RuleSpec 需要补全并确认" in completion
    assert "canAutoConfirmRuleSpec" in completion
    assert "requiresUserCompletion" in completion
    assert "outputPathSpecified" in completion
    assert 'Object.prototype.hasOwnProperty.call(options, "outputPath")' in completion
    assert "uniqueDependencies" in model
    assert "export function uniqueDependencies" in package_lock
    assert 'title="工具"' in page
    assert "添加工具" in page
    assert "返回工具库" in page
    assert "工具节点库" not in page
    assert "添加工具节点" not in page
    assert "返回节点库" not in page
    assert "在线搜索 Bioconda / conda-forge 工具" in page
    assert "加入工具失败" in hook
    assert "addAndCheckSelectedTool" not in hook
    assert "selectedWrapperPath" in hook
    assert "updateSelectedWrapper" in hook
    assert "missingSelectedRuleSpecFields" in hook
    assert "启动工具验证失败" in hook
    assert "createToolPrepareJob(nextTool)" in hook
    assert "trackToolPrepareJob(job)" in hook
    assert "waitForToolPrepareJob(job.jobId)" not in hook
    assert "useToolPrepareTasks" in hook
    assert "createToolPrepareJob(tool)" in hook
    assert "await addToolDependency(nextTool)" in hook
    assert "selectedPackageLocked" in hook
    assert "请选择一个明确版本" in hook
    assert "加入工具节点失败" not in hook
    assert "export function SourceBadge" in ui
    assert "export function ResultRow" in ui
    assert "export function ToolsLibrarySection" in library
    assert "ToolRuleSpecEditor" in library
    assert "补全 RuleSpec" in library
    assert "验证工具" in library
    assert "export function ToolRuleSpecEditor" in editor
    assert "保存 RuleSpec" in editor
    assert "RuleSpec 合同确认" in editor
    assert "JSON.parse" not in editor
    assert "textarea" not in editor
    assert "Command" in editor
    assert "Input" in editor
    assert "Output" in editor
    assert "Params" in editor
    assert "Environment" in editor
    assert "Smoke" in editor
    assert "preserveAdditionalPorts" in editor
    assert "demoqc" not in readiness
    assert "--outdir {output.qc_dir:q}" not in readiness
    assert "directory: true" not in readiness
    assert "qc_dir" not in readiness
    assert "export function ToolSearchResults" in ui
    assert "export function ToolCatalogQualityStrip" in ui
    assert 'export { ToolCatalogQualityStrip } from "./tools-page-catalog-quality-strip";' in ui
    assert "discovered" in ui
    assert "draft-runnable" in ui
    assert "workflow-ready" in ui
    assert "production-enabled" in ui
    assert "ToolCatalogTargetAcceptance" in model
    assert "fetchToolCandidateTargetAcceptance" not in api
    assert "graph.targetAcceptance" in hook
    assert "targetAcceptance" in hook
    assert "setTargetAcceptance" in hook
    assert "targetAcceptance={state.targetAcceptance}" in page
    assert "Catalog v1 targets" in ui
    assert "remaining" in ui
    assert "Snakemake wrapper catalog" in ui
    assert "ToolCatalogQualityStrip" in page
    assert "wrapperCatalog={state.wrapperCatalog}" in page
    assert "searchNotice" not in hook
    assert "searchNotice" not in ui
    assert "searchNoticeMessage" not in model
    assert "onlineUnavailableReason" in model
    assert "export function ToolPreviewPanel" in ui
    assert "RuleNodeSummary" in ui
    assert "RuleSpecContractPreview" in ui
    assert "export function ToolPrepareTaskProvider" in task_context
    assert "export function ToolPrepareTaskBar" in task_bar
    assert "Snakemake dry-run" in task_bar
    assert "Smoke run" in task_bar
    assert "暂无日志" in task_bar
    assert "ToolWrapperSelector" in ui
    assert "加入并验证" not in ui
    assert "添加工具" in ui
    assert "仅依赖，缺 RuleSpec" in ui
    assert "还不能加入流程" not in ui
    assert "ruleSpecEnvironmentItems" in ui
    assert "ruleSpecResourceItems" in ui
    assert "template.schedulerResources" in ui
    assert "ruleSpecParamItems" in ui
    assert "运行环境" in ui
    assert "运行资源" in ui
    assert "参数 schema" in ui
    assert "outputSemanticTags" in ui
    assert '["directory", "protected", "temp"]' in ui
    assert "...port.semantics" in ui
    assert ">工具</h2>" in library
    assert "ToolContractRow" in library
    assert "RuleSpecNodeReadinessBadge" in library
    assert "ToolContractStatusRow" in library
    assert "RuleSpecNodeStatusChip" in library
    assert 'label="Runtime"' in library
    assert "rowState.runtimeLabel" in library
    assert 'label="Smoke"' in library
    assert "validation.smokeRun" in library
    assert "ruleSpecReadinessForTool" in library
    assert "可加入流程" in readiness
    assert "待验证" in readiness
    assert "待确认 RuleSpec" in readiness
    assert "仅依赖" in readiness
    assert "Action" in library
    assert "Dry-run" in library
    assert "Output" in library
    assert "Env" in library
    assert "RuleSpecNodeFact" not in library
    assert "ToolContractStatusDot" in library
    assert "ContractStageRail" in library
    assert "工具预览" in ui
    assert "加入工具" in ui
    assert "请选择版本" in ui
    assert "不锁版本" not in ui
    assert "module:" in ui
    assert "export function ToolWrapperSelector" in wrapper_selector
    assert "推荐 wrapper ref" in wrapper_selector
    assert "wrapperPath" in wrapper_selector
    assert "onWrapperChange" in wrapper_selector
    assert "规则节点库" not in library
    assert "规则节点库" not in ui
    assert "工具节点预览" not in ui
    assert "加入工具节点" not in ui
    assert 'targetPlatform: "linux-64"' in api
    assert "formatPlatformBadgeText" in ui
    assert "export function PlatformChips" in ui
    assert "支持平台" in ui
    assert "line-clamp-2" not in ui
    assert "function SourceBadge" not in page
    assert "function ResultRow" not in page
    assert "function uniqueDependencies" not in page
    assert "requestLocalApiJson" not in page
    assert "useEffect" not in page
    assert "useState" not in page
    assert "项目依赖" not in page
    assert "依赖预览" not in page
    assert "项目依赖" not in ui
    assert "依赖预览" not in ui
    assert "加入依赖" not in ui
    assert "连接流程" not in library
    assert "添加到流程" not in library
    assert "href={toolSearchHref(recommendation)}" in recommendation_ui
    assert 'pathname: "/workflows/tools"' in recommendation_ui
    assert "query: { q: recommendationSearchQuery(recommendation) }" in recommendation_ui


def test_tools_search_surfaces_unified_candidate_catalog() -> None:
    api = (COMPONENTS / "tools-page-api.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-tools-page-state.ts").read_text(encoding="utf-8")
    model = _tools_page_model_source()
    page = (COMPONENTS / "tools-page.tsx").read_text(encoding="utf-8")
    ui = _tools_page_ui_source()

    assert "signal?: AbortSignal" in api
    assert "fetchCapabilityGraphSnapshot" in hook
    assert "searchToolCapabilities" not in hook
    assert "const [capabilityGraph" in hook
    assert "const [candidateCatalog" in hook
    assert "setCandidateCatalogLoading" in hook
    assert "setCandidateCatalogError" in hook
    assert 'if (view !== "search")' in hook
    assert "const canSearchTools = normalized.length >= 2" in hook
    assert 'query: canSearchTools ? normalized : ""' in hook
    assert "page: canSearchTools ? searchPage : 1" in hook
    assert "if (!canSearchTools)" in hook
    assert "installableCandidateItems" in hook
    assert "candidateCatalog={state.candidateCatalog}" in page
    assert "capabilityGraph" in hook
    assert "candidateCatalogLoading={state.candidateCatalogLoading}" in page
    assert "candidateCatalogError={state.candidateCatalogError}" in page
    assert "candidateCatalog?: ToolCandidateCatalog | null" in ui
    assert "Tool candidate catalog" in ui
    assert "sourceCounts" in ui
    assert "addableDraftCounts" in model
    assert "addableDraftCounts" in ui
    assert "addable drafts" in ui
    assert "conda packages" in ui
    assert "wrappers" in ui
    assert "profiles" in ui


def test_tools_page_surfaces_target_validation_queue_priority() -> None:
    page = (COMPONENTS / "tools-page.tsx").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-tools-page-state.ts").read_text(encoding="utf-8")
    model = _tools_page_model_source()
    ui = _tools_page_ui_source()
    capability_gate = (COMPONENTS / "tools-page-capability-gate.tsx").read_text(encoding="utf-8")
    validation_queue = (COMPONENTS / "tools-page-validation-queue.tsx").read_text(encoding="utf-8")
    production_evidence = (COMPONENTS / "tools-page-production-evidence.tsx").read_text(encoding="utf-8")

    assert "export type ToolCatalogValidationQueueItem" in model
    assert "priority?: ToolCatalogValidationPriority" in model
    assert "export type ToolCatalogValidationPlan" in model
    assert "export type ToolCatalogExecutionGate" in model
    assert "export type ToolCatalogLatestPrepareJob" in model
    assert "validationPlan?: ToolCatalogValidationPlan" in model
    assert "executionGate?: ToolCatalogExecutionGate" in model
    assert "latestPrepareJob?: ToolCatalogLatestPrepareJob" in model
    assert "semanticPortFields?: string[]" in model
    assert "wrapperContractHintCount?: number" in model
    assert "wrapperContractHintFields?: string[]" in model
    assert "wrapperCondaDependencies?: string[]" in model
    assert "validationQueue?: ToolCatalogValidationQueue" in model
    assert "export type CapabilityGraphSnapshot" in model
    assert "export type CapabilityBundleSummary" in model
    assert "export type CapabilityBundleStatus" in model
    assert "export type CapabilityBundleGate" in model
    assert "capabilityBundleVersion" in model
    assert "capabilityBundles?: CapabilityBundleSummary[]" in model
    assert "capabilityBundleGate?: CapabilityBundleGate" in model
    assert "capabilityBundle?: CapabilityBundleSummary" in model
    assert "capabilityBundleStatus?: CapabilityBundleStatus" in model
    assert "approval?: { required?: boolean; approved?: boolean; policyVersion?: string; reason?: string }" in model
    assert "export type CapabilityAdmissionEvidence" in model
    assert "admissionEvidence?: CapabilityAdmissionEvidence" in model
    assert "export type ToolCatalogProductionQueue" in model
    assert "productionQueue?: ToolCatalogProductionQueue" in model
    assert "export type ToolPrepareJobQueue" in model
    assert "prepareJobQueue?: ToolPrepareJobQueue" in model
    assert "export type ToolValidationBatchPlan" in model
    assert "batchPlan?: ToolValidationBatchPlan" in model
    assert 'import { ToolCatalogValidationQueueStrip } from "./tools-page-validation-queue";' in ui
    assert 'import { CapabilityBundleGatePanel } from "./tools-page-capability-gate";' in ui
    assert "CapabilityBundleGatePanel" in capability_gate
    assert "DATABASE_RESOURCE_REQUIRED" in capability_gate
    assert "acceptedTemplates" in capability_gate
    assert "blockedTools.slice(0, 4)" not in capability_gate
    assert "visibleBlockedTools" in capability_gate
    assert "showAllBlocked" in capability_gate
    assert "capabilityReasonCounts" in capability_gate
    assert "capabilityGraph={state.capabilityGraph}" in page
    assert "validationQueueItems" in ui
    assert "targetAcceptance?.validationQueue?.items ?? []" in ui
    assert "targetAcceptance?.validationQueue?.items?.slice(0, 3)" not in ui
    assert "prepareJobQueue={targetAcceptance?.prepareJobQueue}" in ui
    assert "onQueueChanged={state.refreshToolCatalogTargets}" in page
    assert "onQueueChanged" in ui
    assert "onQueueChanged" in validation_queue
    assert "refreshToolCatalogTargets" in hook
    assert "loadTargetAcceptance({ silent: true })" in hook
    assert "validation queue" in validation_queue
    assert "productionQueue" in validation_queue
    assert "production evidence queue" in production_evidence
    assert "prepareJobQueue" in validation_queue
    assert "prepare job queue" in validation_queue
    assert "prepareQueueMetricItems" in validation_queue
    assert 'import { ToolProductionEvidencePanel } from "./tools-page-production-evidence";' in validation_queue
    assert "ToolProductionEvidencePanel productionQueue={productionQueue}" in validation_queue
    assert "submit-production-evidence" in production_evidence
    assert "submitToolProductionEvidence" in production_evidence
    assert "fetchRunsList({ forceRefresh: true })" in production_evidence
    assert "fetchWorkflowRunDetail" in production_evidence
    assert "GENERATED_TOOL_RUN_PIPELINE_ID" in production_evidence
    assert "real-database-acceptance" in production_evidence
    assert "runDetailReady" in production_evidence
    assert "missingSubmitField(form, activeRunId, runDetailReady)" in production_evidence
    assert "artifact.artifactId" in production_evidence
    assert "artifactEvidenceName" in production_evidence
    assert "firstDatabaseBindingPatch" in production_evidence
    assert "resourceBindings" in production_evidence
    assert "data-field=\"production-evidence-message\"" in production_evidence
    assert "data-field=\"production-evidence-artifact\"" in production_evidence
    assert "inputScopeFromRun" in production_evidence
    assert "payload.inputScope = inputScope" in production_evidence
    assert "artifactDigest" in production_evidence
    assert "policyVersion" in production_evidence
    assert "packChecksum" in production_evidence
    assert "visibleLimit, setVisibleLimit" in validation_queue
    assert "visibleItems = items.slice(0, visibleLimit)" in validation_queue
    assert "hiddenItemCount" in validation_queue
    assert "items.map((item)" not in validation_queue
    assert "createToolPrepareJob(tool)" in validation_queue
    assert "prepareToolValidationQueue(Math.min(items.length, 30))" in validation_queue
    assert "prepareToolValidationQueue(3)" not in validation_queue
    assert "trackToolPrepareJob(queueJobToPrepareTask(item))" in validation_queue
    assert "await onQueueChanged?.()" in validation_queue
    assert "batchPreparing" in validation_queue
    assert "批量验证" in validation_queue
    assert "queuedCount" in validation_queue
    assert "result.batchPlan?.status" in validation_queue
    assert "result.batchPlan?.jobIds.length" in validation_queue
    assert "trackToolPrepareJob(job)" in validation_queue
    assert "waitForToolPrepareJob" not in validation_queue
    assert "addedToolFromValidationQueueItem" in validation_queue
    assert "preparingCandidateId" in validation_queue
    assert "priority?.score" in validation_queue
    assert "executionGate?.nextAction" in validation_queue
    assert "activePrepareJob" in validation_queue
    assert "isActivePrepareJob(item)" in validation_queue
    assert "latestPrepareJob?.status" in validation_queue
    assert "latestPrepareJob?.errorCode" in validation_queue
    assert "validationResultId?: string" in model
    assert "evidenceId?: string" in model
    assert "validationPlan?.stages?.length" in validation_queue
    assert "prepare stages" in validation_queue
    assert "semanticPortFields" in validation_queue
    assert "snakemakeWrapperCount" in validation_queue
    assert "wrapperContractHintCount" in validation_queue
    assert "wrapperContractHintFields" in validation_queue
    assert "wrapperCondaDependencies" in validation_queue


def test_tools_page_candidate_catalog_knows_registered_tool_index_source() -> None:
    model = _tools_page_model_source()

    assert "registeredToolIndex?: number" in model
    assert "RegisteredToolIndexCandidate" in model
    assert '"registered-tool-index"' in model
