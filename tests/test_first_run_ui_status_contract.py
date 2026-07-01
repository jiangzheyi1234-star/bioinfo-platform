from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIRST_RUN_ROUTE = ROOT / "apps" / "web" / "app" / "workflows" / "first-run"
FIRST_RUN_COMPONENTS = FIRST_RUN_ROUTE / "_components"
FIRST_RUN_DOMAIN = FIRST_RUN_ROUTE / "_domain"


def test_first_run_ui_steps_and_report_are_status_contract_driven() -> None:
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    first_run_report = (FIRST_RUN_COMPONENTS / "workflow-first-run-report.tsx").read_text(encoding="utf-8")
    first_run_progress = (FIRST_RUN_DOMAIN / "first-run-progress.ts").read_text(encoding="utf-8")
    first_run_types = (FIRST_RUN_DOMAIN / "first-run-types.ts").read_text(encoding="utf-8")

    assert 'import type { FirstRunStatus } from "./first-run-types"' in first_run_progress
    assert "reportEvidence?: FirstRunStatusEvidence[\"report\"]" in first_run_report
    assert "ready: reportEvidence?.ready === true" in first_run_report
    assert 'run?.status === "completed" && outputs.every' not in first_run_report
    assert "firstRunStepIdForStage" in first_run_progress
    assert 'stage === "inspect_failed_run"' in first_run_progress
    assert "hasStatus ? evidence?.sampleCache?.status === \"ready\" : input.sampleReady" in first_run_progress
    assert "hasStatus ? Boolean(statusRun?.runId) : input.runSubmitted" in first_run_progress
    assert "hasStatus ? evidence?.server?.connected === true : input.serverConnected" in first_run_progress
    assert "hasStatus ? evidence?.workflow?.ready === true : input.selectedWorkflowReady" in first_run_progress
    assert "action?.code === \"FINALIZE_FIRST_RUN\"" in first_run_progress
    assert "firstRunStatus: firstRunStatusSnapshot || null" in first_run_page
    assert "input.reportReady" not in first_run_progress
    assert "input.packageReady" not in first_run_progress
    assert "input.validationReady" not in first_run_progress
    assert "input.runFailed" not in first_run_progress
    assert "runCompleted" not in first_run_progress
    assert "runTerminal" not in first_run_progress
    assert "includeArtifacts?: boolean;" in first_run_types
    assert "const reportReady = runCompleted && artifacts.length > 0" not in first_run_page
    assert "const reportReady =" not in first_run_page
    assert "evidence?.report?.ready === true" in first_run_progress
    assert "reportEvidence={firstRunStatusSnapshot?.evidence?.report}" in first_run_page
    assert "statusRun={statusRun}" in first_run_page
    assert "statusRun?: FirstRunStatusRunSummary | null" in first_run_report
    assert "const effectiveRunId = statusRun?.runId || run?.runId || \"\"" in first_run_report
    assert "const effectiveRunStatus = statusRun?.status || run?.status || \"\"" in first_run_report
    assert "const effectiveRunStage = statusRun?.stage || run?.stage || \"\"" in first_run_report
    assert "disabled={!effectiveRunId || packageLoading}" in first_run_report
    assert "run={run}" not in first_run_report
    assert "firstRunStatus={firstRunStatusSnapshot || null}" in first_run_page
    assert 'firstRunStatus.stage === "export_result_package"' not in first_run_progress


def test_first_run_validation_and_trust_summary_are_status_contract_driven() -> None:
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    first_run_completion = (FIRST_RUN_COMPONENTS / "workflow-first-run-completion.tsx").read_text(encoding="utf-8")
    first_run_trust_summary = (FIRST_RUN_COMPONENTS / "workflow-first-run-trust-summary.tsx").read_text(encoding="utf-8")
    first_run_validation = (FIRST_RUN_COMPONENTS / "workflow-first-run-validation.tsx").read_text(encoding="utf-8")

    assert "firstRunStatus={firstRunStatusSnapshot || null}" in first_run_page
    assert "firstRunStatus: FirstRunStatus | null" in first_run_completion
    assert "firstRunStatus?: FirstRunStatus | null" not in first_run_completion
    assert "status: FirstRunStatus | null" in first_run_trust_summary
    assert "status?: FirstRunStatus | null" not in first_run_trust_summary
    assert "const validationEvidence = firstRunStatus?.evidence?.validation" in first_run_validation
    assert "const resultPackageEvidence = firstRunStatus?.evidence?.resultPackage" in first_run_validation
    assert "const statusRun = firstRunStatus?.evidence?.run || firstRunStatus?.latestEligibleRun || null" in first_run_validation
    assert 'const effectiveRunId = firstRunStatus ? statusRun?.runId || "" : run?.runId || ""' in first_run_validation
    assert 'const effectiveRunStatus = firstRunStatus ? statusRun?.status || "" : run?.status || ""' in first_run_validation
    assert "const packageExportId = firstRunStatus ? resultPackageEvidence?.packageExportId : packageExport?.packageExportId" in first_run_validation
    assert "const validationPassed = validationEvidence?.ready === true" in first_run_validation
    assert "data-validation-passed={validationPassed ? \"true\" : \"false\"}" in first_run_validation
    assert "evidence?.validation?.ready === true" in first_run_trust_summary
    assert "evidence?.sampleCache?.status === \"ready\"" in first_run_trust_summary
    assert "evidence?.report?.ready === true" in first_run_trust_summary
    assert "resultPackage?.ready === true" in first_run_trust_summary
    assert "FirstRunTrustSummary status={firstRunStatus}" in first_run_validation
    assert "FirstRunTrustSummary status={firstRunStatus}" in first_run_completion
    assert "firstRunValidationCardPassed" not in first_run_validation
    assert "?? checks.filter" not in first_run_trust_summary
    assert "|| packageExport?.sha256" not in first_run_trust_summary
    assert "|| packageExport?.manifestSha256" not in first_run_trust_summary
    assert "latestPackage?.sha256 || resultPackageEvidence?.sha256" not in first_run_completion
    assert "latestPackage?.manifestSha256 || resultPackageEvidence?.manifestSha256" not in first_run_completion
    assert "const statusRun = firstRunStatus?.evidence?.run || firstRunStatus?.latestEligibleRun || null" in first_run_completion
    assert 'const effectiveRunId = firstRunStatus ? statusRun?.runId || "" : run?.runId || ""' in first_run_completion
    assert "const effectiveResultId = firstRunStatus ? statusRun?.resultId || resultId : resultId" in first_run_completion
    assert "firstRunEvidenceBundleFiles(evidenceBundle)" in first_run_completion
    assert "firstRunEvidenceBundleFileDownloadHref(file)" in first_run_completion
    assert "workflowResultPackageDownloadHref(latestPackage" not in first_run_completion
    assert "validationChecksPassed ?? checks.filter" not in first_run_validation
    assert not (FIRST_RUN_DOMAIN / "first-run-validation-state.ts").exists()


def test_first_run_refreshes_workspace_after_ssh_connect_success() -> None:
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")

    assert "useRef" in first_run_page
    assert 'const sshConnectionRefreshRef = useRef("")' in first_run_page
    assert 'const sshConnectedServerId = ssh.status?.connected === true ? ssh.status.serverId || "" : ""' in first_run_page
    assert "sshConnectionRefreshRef.current = connectionKey" in first_run_page
    assert "void refreshWorkspaceAndFirstRunStatus()" in first_run_page
    assert "ssh.status?.serverId" in first_run_page
    assert "firstRunWorkspaceConnectionPrompt(state.error, serverConnected)" in first_run_page
    assert "const visibleWorkspaceError = workspaceConnectionPrompt ? \"\" : state.error" in first_run_page
    assert "请先连接远端后继续首跑。" in first_run_page
    assert "远端已连接，正在读取运行环境检查。" in first_run_page
    assert "<AlertDescription>{state.error}</AlertDescription>" not in first_run_page


def test_first_run_conductor_uses_status_contract_before_local_run_hints() -> None:
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    first_run_conductor = (FIRST_RUN_COMPONENTS / "workflow-first-run-conductor.tsx").read_text(encoding="utf-8")

    assert "firstRunStatus: firstRunStatusSnapshot || null" in first_run_page
    assert "statusAction: firstRunStatusSnapshot?.nextAction || null" not in first_run_page
    assert "firstRunStatus: FirstRunStatus | null" in first_run_conductor
    assert "statusAction?: FirstRunNextAction | null" not in first_run_conductor
    assert "const status = input.firstRunStatus" in first_run_conductor
    assert "hasStatus ? evidence?.sampleCache?.status === \"ready\" : input.sampleReady" in first_run_conductor
    assert "hasStatus ? Boolean(statusRun?.runId) : input.runSubmitted" in first_run_conductor
    assert "if (status?.nextAction)" in first_run_conductor
    assert "continueActionFromStatus(status.nextAction)" in first_run_conductor
    assert "statusAllowsSubmit" in first_run_conductor
    assert "status.evidence?.server?.ready === true" in first_run_conductor
    assert "status.evidence?.execution?.ready === true" in first_run_conductor
    assert "status.evidence?.workflow?.ready === true" in first_run_conductor
    assert first_run_conductor.index("if (status?.nextAction)") < first_run_conductor.index("if (!input.serverConnected)")
    assert "if (!status?.nextAction)" not in first_run_conductor


def test_first_run_submit_uses_status_sample_cache_without_local_upload_gate() -> None:
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    first_run_api = (FIRST_RUN_ROUTE / "_api" / "workflow-first-run-api.ts").read_text(encoding="utf-8")
    first_run_sample_submit = (FIRST_RUN_COMPONENTS / "workflow-first-run-sample-submit.tsx").read_text(encoding="utf-8")
    workflows_state = (ROOT / "apps" / "web" / "app" / "components" / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    first_run_status_state = (FIRST_RUN_ROUTE / "_state" / "use-first-run-status.ts").read_text(encoding="utf-8")

    assert 'const statusSampleReady = firstRunStatusSnapshot?.evidence?.sampleCache?.status === "ready"' in first_run_page
    assert "const sampleReady = firstRunStatusSnapshot ? statusSampleReady || localSampleReady : localSampleReady" in first_run_page
    assert "const firstRunCanSubmit = Boolean(" in first_run_page
    assert 'firstRunStatusSnapshot?.nextAction?.code === "SUBMIT_RUN"' in first_run_page
    assert 'firstRunStatusSnapshot.stage === "submit_run"' in first_run_page
    assert "statusServerEvidence?.ready === true" in first_run_page
    assert "statusExecutionEvidence?.ready === true" in first_run_page
    assert "statusWorkflowEvidence?.ready === true" in first_run_page
    assert "serverConnected &&" not in first_run_page
    assert "executionReady &&" not in first_run_page
    assert "selectedWorkflowReady &&" not in first_run_page
    assert "state.missingRequiredResourceKeys.length" not in first_run_page
    assert "canSubmit: firstRunCanSubmit" in first_run_page
    assert "canSubmit={firstRunCanSubmit}" in first_run_page
    assert "onSubmitRun: submitFirstRunAndRefreshStatus" in first_run_page
    assert "import { submitFirstRun } from \"../_api/workflow-first-run-api\"" in first_run_page
    assert "const submission = await submitFirstRun({" in first_run_page
    assert 'actor: "first-run-ui"' in first_run_page
    assert "idempotencyKey: `idem_first_run_${Date.now()}`" in first_run_page
    assert "state.selectRun(runId)" in first_run_page
    assert "await state.submitRun({ sampleUploads: uploads })" not in first_run_page
    assert "const uploads = localSampleReady ? state.sampleUploads : await state.loadSampleData()" not in first_run_page
    assert "export async function submitFirstRun" in first_run_api
    assert 'confirmation: "submit-first-run"' in first_run_api
    assert '"/api/v1/first-run/runs"' in first_run_api
    assert "sampleCacheEvidence={firstRunStatusSnapshot?.evidence?.sampleCache}" in first_run_page
    assert "state.canSubmit && executionReady && selectedWorkflowReady && sampleReady" not in first_run_page
    assert "sampleCacheEvidence?: FirstRunStatusEvidence[\"sampleCache\"]" in first_run_sample_submit
    assert "const ready = localReady || cacheReady" in first_run_sample_submit
    assert "cache verified" in first_run_sample_submit
    assert "sampleDataStatusSummary(status, ready, loading, error, sampleCacheEvidence)" in first_run_sample_submit
    assert "type SubmitRunOptions = {" in workflows_state
    assert "async function submitRun(options: SubmitRunOptions = {})" in workflows_state
    assert "const selectedSampleUploads = options.sampleUploads ?? sampleUploads" in workflows_state
    assert "sampleUploads: selectedSampleUploads" in workflows_state
    assert "return uploads" in workflows_state
    assert "if (!normalizedServerId)" not in first_run_status_state
    assert "serverId: normalizedServerId || undefined" in first_run_status_state


def test_first_run_evidence_actions_use_status_run_id_before_local_run() -> None:
    first_run_evidence_state = (FIRST_RUN_ROUTE / "_state" / "use-first-run-evidence.ts").read_text(encoding="utf-8")

    assert 'const firstRunRunId = status ? statusRun?.runId || "" : run?.runId || ""' in first_run_evidence_state
    assert 'const runStatus = status ? statusRun?.status || "" : run?.status || ""' in first_run_evidence_state
    assert "const validationEligible = validationReady" in first_run_evidence_state
    assert "fetchFirstRunValidationCard(firstRunRunId" in first_run_evidence_state
    assert "finalizeFirstRun(firstRunRunId" in first_run_evidence_state
    assert "downloadFirstRunValidationCard" not in first_run_evidence_state
    assert "runId: firstRunRunId" not in first_run_evidence_state
    assert "if (!run?.runId" not in first_run_evidence_state
    assert "fetchFirstRunValidationCard(run.runId" not in first_run_evidence_state
    assert "finalizeFirstRun(run.runId" not in first_run_evidence_state
    assert "validationReady && Boolean(workflowRevisionId)" not in first_run_evidence_state


def test_first_run_result_package_uses_selected_server_boundary() -> None:
    first_run_page = (FIRST_RUN_COMPONENTS / "workflow-first-run-page.tsx").read_text(encoding="utf-8")
    first_run_evidence_state = (FIRST_RUN_ROUTE / "_state" / "use-first-run-evidence.ts").read_text(encoding="utf-8")
    first_run_validation = (FIRST_RUN_COMPONENTS / "workflow-first-run-validation.tsx").read_text(encoding="utf-8")
    first_run_completion = (FIRST_RUN_COMPONENTS / "workflow-first-run-completion.tsx").read_text(encoding="utf-8")
    first_run_api = (FIRST_RUN_ROUTE / "_api" / "workflow-first-run-api.ts").read_text(encoding="utf-8")
    workflows_api = (ROOT / "apps" / "web" / "app" / "components" / "workflows-page-api.ts").read_text(encoding="utf-8")

    assert "fetchWorkflowResultPackageExports(resultId, { serverId })" in first_run_evidence_state
    assert "exportWorkflowResultPackage(resultId, true, { serverId })" in first_run_evidence_state
    assert "packageExports.find((item) => item.packageExportId === statusPackageExportId)" in first_run_evidence_state
    assert "packageBytesState: \"available\"" in first_run_evidence_state
    assert "download: {" not in first_run_evidence_state
    assert "`/api/v1/results/${encodeURIComponent(resultId)}/exports/${encodeURIComponent(statusPackageExportId)}/download`" not in first_run_evidence_state
    assert "const firstRunServerId = status?.serverId || serverId" in first_run_evidence_state
    assert "serverId: firstRunServerId" in first_run_evidence_state
    assert "card: validationCard" not in first_run_evidence_state
    assert "serverId={state.server?.serverId}" in first_run_page
    assert "serverId?: string;" in first_run_validation
    assert "workflowResultPackageDownloadHref(latestPackage, { serverId })" in first_run_validation
    assert "firstRunEvidenceBundleFileByRole(evidenceBundle, \"validation-card-markdown\")" in first_run_validation
    assert "firstRunEvidenceBundleFileByRole(evidenceBundle, \"validation-card-json\")" in first_run_validation
    assert "firstRunEvidenceBundleFileDownloadHref(validationMarkdownFile)" in first_run_validation
    assert "firstRunEvidenceBundleFileDownloadHref(validationJsonFile)" in first_run_validation
    assert "workflowResultPackageDownloadHref(latestPackage, { serverId: packageServerId })" not in first_run_completion
    assert "downloadFirstRunValidationCard" not in first_run_api
    assert "firstRunDownloadPath" not in first_run_api
    assert "downloadLocalApiFile" not in first_run_api
    assert "options: { serverId?: string } = {}" in workflows_api
    assert "...(options.serverId ? { serverId: options.serverId } : {})" in workflows_api
    assert "`/api/v1/results/${encodeURIComponent(resultId)}/exports${refreshQuery(options)}`" in workflows_api
    assert "serverId=${encodeURIComponent(serverId)}" in workflows_api
    assert "fetchWorkflowResultPackageExports(resultId)" not in first_run_evidence_state
    assert "exportWorkflowResultPackage(resultId, true)" not in first_run_evidence_state
