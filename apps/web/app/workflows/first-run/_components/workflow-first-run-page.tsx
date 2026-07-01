"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Rocket,
  Server,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useSshShell } from "@/app/components/ssh-shell";
import { RunnerRepairPanel } from "@/app/components/ssh-runner-repair-panel";
import type { SSHStatus } from "@/app/components/ssh-shell-model";
import { useWorkflowsPageState } from "@/app/components/use-workflows-page-state";
import { WorkflowFirstRunConductorPanel, useFirstRunConductor } from "./workflow-first-run-conductor";
import { FirstRunCompletionPanel } from "./workflow-first-run-completion";
import { SampleAndSubmitPanel, sampleUploadsReady } from "./workflow-first-run-sample-submit";
import { WorkflowPageHeader } from "@/app/components/workflow-page-header";
import { WorkflowWorkspaceTabs } from "@/app/components/workflow-workspace-tabs";
import { RunReportPanel } from "./workflow-first-run-report";
import { ResultPackagePanel, ValidationCard } from "./workflow-first-run-validation";
import { fetchWorkflowServerExecutionDiagnostics } from "@/app/components/workflows-page-api";
import { runWorkflowServerRunnerRepairAction } from "@/app/components/workflow-runner-repair-state";
import { submitFirstRun } from "../_api/workflow-first-run-api";
import {
  workflowErrorMessage,
  type WorkflowExecutionDiagnostics,
  type WorkflowServer,
} from "@/app/components/workflows-page-model";
import {
  FIRST_RUN_PIPELINE_ID,
  FIRST_RUN_PIPELINE_NAME,
  buildFirstRunSteps,
  executionDiagnosticsDetail,
  resultPackageDisabledReason,
  runnerChecks,
  type FirstRunStep,
  type FirstRunStepState,
} from "../_domain/first-run-progress";
import { useFirstRunEvidence } from "../_state/use-first-run-evidence";
import { useFirstRunStatus } from "../_state/use-first-run-status";

export function WorkflowFirstRunPage() {
  const ssh = useSshShell();
  const state = useWorkflowsPageState(FIRST_RUN_PIPELINE_ID);
  const [ensuringRunner, setEnsuringRunner] = useState(false);
  const [runnerError, setRunnerError] = useState("");
  const [executionDiagnostics, setExecutionDiagnostics] = useState<WorkflowExecutionDiagnostics | null>(null);
  const [executionDiagnosticsLoading, setExecutionDiagnosticsLoading] = useState(false);
  const [executionDiagnosticsError, setExecutionDiagnosticsError] = useState("");
  const [submittingFirstRun, setSubmittingFirstRun] = useState(false);
  const [firstRunSubmitError, setFirstRunSubmitError] = useState("");
  const sshConnectionRefreshRef = useRef("");
  const autoFinalizeFirstRunRef = useRef("");

  const run = state.runDetail?.run || state.submittedRun;
  const result = state.runDetail?.results;
  const activeRunId = state.activeRunId;
  const submittedRunId = state.submittedRun?.runId || "";
  const runDetailRunId = state.runDetail?.run?.runId || "";
  const selectRun = state.selectRun;
  const firstRunStatus = useFirstRunStatus({
    runId: activeRunId || run?.runId,
    serverId: state.server?.serverId,
  });
  const firstRunStatusSnapshot = firstRunStatus.status;
  const firstRunStatusStage = firstRunStatusSnapshot?.stage || "";
  const firstRunNextActionCode = firstRunStatusSnapshot?.nextAction?.code || "";
  const firstRunNextActionBlockedCode = firstRunStatusSnapshot?.nextAction?.blockedCode || "";
  const statusServerEvidence = firstRunStatusSnapshot?.evidence?.server;
  const statusExecutionEvidence = firstRunStatusSnapshot?.evidence?.execution;
  const statusWorkflowEvidence = firstRunStatusSnapshot?.evidence?.workflow;
  const statusRun = firstRunStatusSnapshot?.evidence?.run || firstRunStatusSnapshot?.latestEligibleRun || null;
  const resultId = result?.resultId || statusRun?.resultId || (run?.runId ? `res_${run.runId}` : "");
  const artifacts = result?.artifacts || [];
  const inputArtifacts = result?.inputArtifacts || [];
  const previews = state.runDetail?.previews || [];
  const movingPicturesWorkflow = state.catalog.find((item) => item.id === FIRST_RUN_PIPELINE_ID) || null;
  const selectedWorkflowReady = firstRunStatusSnapshot ? statusWorkflowEvidence?.ready === true : Boolean(movingPicturesWorkflow?.runnable);
  const serverConnected = firstRunStatusSnapshot ? statusServerEvidence?.connected === true : Boolean(state.server?.connected);
  const workspaceConnectionPrompt = firstRunWorkspaceConnectionPrompt(state.error, serverConnected);
  const visibleWorkspaceError = workspaceConnectionPrompt ? "" : state.error;
  const executionReady = firstRunStatusSnapshot ? statusExecutionEvidence?.ready === true : executionDiagnostics?.readiness?.ok === true;
  const serverReady = firstRunStatusSnapshot ? statusServerEvidence?.ready === true && statusExecutionEvidence?.ready === true : Boolean(state.server?.ready) && executionReady;
  const localSampleReady = sampleUploadsReady(state.sampleUploads);
  const statusSampleReady = firstRunStatusSnapshot?.evidence?.sampleCache?.status === "ready";
  const sampleReady = firstRunStatusSnapshot ? statusSampleReady || localSampleReady : localSampleReady;
  const firstRunCanSubmit = Boolean(
    firstRunStatusSnapshot?.nextAction?.code === "SUBMIT_RUN" &&
      firstRunStatusSnapshot.stage === "submit_run" &&
      statusServerEvidence?.ready === true &&
      statusExecutionEvidence?.ready === true &&
      statusWorkflowEvidence?.ready === true &&
      sampleReady &&
      !submittingFirstRun &&
      !state.submitting &&
      !state.sampleLoading
  );
  const runSubmitted = Boolean(run?.runId || statusRun?.runId);
  const firstRunEvidence = useFirstRunEvidence({
    refreshRunDetail: state.refreshRunDetail,
    resultId,
    run,
    runDetail: state.runDetail,
    status: firstRunStatusSnapshot || null,
    serverId: state.server?.serverId,
  });
  const latestPackage = firstRunEvidence.latestPackage;
  const validationEligible = firstRunEvidence.validationEligible;
  const validationReady = firstRunEvidence.validationReady;
  const workflowRevisionId = firstRunEvidence.workflowRevisionId;
  const finalizeFirstRun = firstRunEvidence.finalizeRun;
  const exportFirstRunPackage = firstRunEvidence.exportPackage;
  const refreshFirstRunStatus = firstRunStatus.refreshStatus;
  const finalizeAndRefreshStatus = useCallback(async () => {
    await finalizeFirstRun();
    await refreshFirstRunStatus({ forceRefresh: true });
  }, [finalizeFirstRun, refreshFirstRunStatus]);
  const exportPackageAndRefreshStatus = useCallback(async () => {
    await exportFirstRunPackage();
    await refreshFirstRunStatus({ forceRefresh: true });
  }, [exportFirstRunPackage, refreshFirstRunStatus]);

  const steps = useMemo(
    () =>
      buildFirstRunSteps({
        firstRunStatus: firstRunStatusSnapshot || null,
        runSubmitted,
        sampleReady,
        selectedWorkflowReady,
        serverConnected,
        serverReady,
      }),
    [
      firstRunStatusSnapshot,
      runSubmitted,
      sampleReady,
      selectedWorkflowReady,
      serverConnected,
      serverReady,
    ]
  );

  const loadExecutionDiagnostics = useCallback(async () => {
    const serverId = state.server?.serverId || "";
    if (!serverId) {
      setExecutionDiagnostics(null);
      setExecutionDiagnosticsError("");
      return;
    }
    setExecutionDiagnosticsLoading(true);
    setExecutionDiagnosticsError("");
    try {
      setExecutionDiagnostics(await fetchWorkflowServerExecutionDiagnostics(serverId));
    } catch (err) {
      setExecutionDiagnostics(null);
      setExecutionDiagnosticsError(workflowErrorMessage(err, "execution diagnostics 读取失败"));
    } finally {
      setExecutionDiagnosticsLoading(false);
    }
  }, [state.server?.serverId]);

  const refreshWorkspaceAndFirstRunStatus = useCallback(async () => {
    await state.loadWorkspace({ forceRefresh: true });
    await loadExecutionDiagnostics();
    await firstRunStatus.refreshStatus({ forceRefresh: true });
  }, [firstRunStatus, loadExecutionDiagnostics, state]);

  useEffect(() => {
    void loadExecutionDiagnostics();
  }, [loadExecutionDiagnostics]);

  useEffect(() => {
    const latestEligibleRunId = firstRunStatusSnapshot?.latestEligibleRun?.runId || "";
    if (!latestEligibleRunId || activeRunId || submittedRunId || runDetailRunId) return;
    selectRun(latestEligibleRunId);
  }, [
    activeRunId,
    firstRunStatusSnapshot?.latestEligibleRun?.runId,
    runDetailRunId,
    selectRun,
    submittedRunId,
  ]);

  useEffect(() => {
    const sshConnectedServerId = ssh.status?.connected === true ? ssh.status.serverId || "" : "";
    if (!sshConnectedServerId) {
      if (ssh.status?.connected !== true) sshConnectionRefreshRef.current = "";
      return;
    }
    const connectionKey = [
      sshConnectedServerId,
      ssh.status?.host || "",
      ssh.status?.port || "",
      ssh.status?.user || "",
    ].join("|");
    if (sshConnectionRefreshRef.current === connectionKey) return;
    sshConnectionRefreshRef.current = connectionKey;
    void refreshWorkspaceAndFirstRunStatus();
  }, [
    ssh.status?.connected,
    ssh.status?.host,
    ssh.status?.port,
    ssh.status?.serverId,
    ssh.status?.user,
    refreshWorkspaceAndFirstRunStatus,
  ]);

  useEffect(() => {
    const finalizedRunId = statusRun?.runId || "";
    const blockedCode = firstRunNextActionBlockedCode;
    const finalizeKey = `${finalizedRunId}|${blockedCode}`;
    const runCompleted = String(statusRun?.status || "").toLowerCase() === "completed";
    if (
      firstRunStatusStage !== "export_result_package" ||
      firstRunNextActionCode !== "FINALIZE_FIRST_RUN" ||
      !finalizedRunId ||
      !blockedCode ||
      !runCompleted ||
      firstRunEvidence.finalizingFirstRun ||
      firstRunEvidence.validationReady
    ) {
      return;
    }
    if (autoFinalizeFirstRunRef.current === finalizeKey) return;
    autoFinalizeFirstRunRef.current = finalizeKey;
    void finalizeAndRefreshStatus();
  }, [
    finalizeAndRefreshStatus,
    firstRunEvidence.finalizingFirstRun,
    firstRunEvidence.validationReady,
    firstRunNextActionBlockedCode,
    firstRunNextActionCode,
    firstRunStatusStage,
    statusRun?.runId,
    statusRun?.status,
  ]);

  const firstRunConductor = useFirstRunConductor({
    busy:
      ensuringRunner ||
      firstRunStatus.loading ||
      state.sampleLoading ||
      submittingFirstRun ||
      state.submitting ||
      firstRunEvidence.packageLoading ||
      firstRunEvidence.exportingPackage ||
      firstRunEvidence.finalizingFirstRun ||
      firstRunEvidence.validationCardFetchLoading,
    input: {
      canSubmit: firstRunCanSubmit,
      firstRunStatus: firstRunStatusSnapshot || null,
      runSubmitted,
      sampleReady,
      selectedWorkflowReady,
      serverConnected,
      serverReady,
    },
    onConnect: openConnectDialog,
    onEnsureRunner: ensureRunner,
    onFinalize: async () => {
      await finalizeAndRefreshStatus();
    },
    onPrepareSampleData: prepareSampleDataAndRefreshStatus,
    onRefreshRun: async () => {
      await state.refreshRunDetail();
      await firstRunStatus.refreshStatus({ forceRefresh: true });
    },
    onRefreshWorkspace: refreshWorkspaceAndFirstRunStatus,
    onSubmitRun: submitFirstRunAndRefreshStatus,
  });

  function openConnectDialog() {
    ssh.clearFormError();
    ssh.setDialogOpen(true);
  }

  async function ensureRunner() {
    if (!state.server?.serverId || ensuringRunner) return;
    setEnsuringRunner(true);
    setRunnerError("");
    try {
      await runWorkflowServerRunnerRepairAction(state.server);
      await state.loadWorkspace({ forceRefresh: true });
      await loadExecutionDiagnostics();
      await firstRunStatus.refreshStatus({ forceRefresh: true });
    } catch (err) {
      setRunnerError(workflowErrorMessage(err, "运行环境检查失败"));
    } finally {
      setEnsuringRunner(false);
    }
  }

  async function prepareSampleDataAndRefreshStatus() {
    await state.loadSampleData();
    await firstRunStatus.refreshStatus({ forceRefresh: true });
  }

  async function submitFirstRunAndRefreshStatus() {
    const serverId = state.server?.serverId || "";
    if (!serverId || submittingFirstRun) return;
    setSubmittingFirstRun(true);
    setFirstRunSubmitError("");
    try {
      const submission = await submitFirstRun({
        actor: "first-run-ui",
        idempotencyKey: `idem_first_run_${Date.now()}`,
        serverId,
      });
      const runId = submission.submittedRun?.runId || "";
      if (submission.status !== "submitted" || !runId) {
        setFirstRunSubmitError(submission.nextAction?.detail || "首跑提交未达到 submitted 状态。");
        await firstRunStatus.refreshStatus({ forceRefresh: true });
        return;
      }
      state.selectRun(runId);
      await firstRunStatus.refreshStatus({ forceRefresh: true });
    } catch (err) {
      setFirstRunSubmitError(workflowErrorMessage(err, "提交首跑失败"));
    } finally {
      setSubmittingFirstRun(false);
    }
  }

  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-8 py-10 text-slate-800" data-testid="first-successful-run-page">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-6xl space-y-6">
        <WorkflowPageHeader
          title="首跑向导"
          leading={
            <span className="inline-flex h-8 items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 text-xs font-medium text-emerald-700">
              <Rocket strokeWidth={1.5} className="h-3.5 w-3.5" />
              {FIRST_RUN_PIPELINE_NAME}
            </span>
          }
          actions={
            <Button
              variant="outline"
              className="h-9 bg-white px-3 text-slate-600"
              disabled={state.loading}
              onClick={() => void refreshWorkspaceAndFirstRunStatus()}
            >
              {state.loading ? (
                <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw strokeWidth={1.5} className="mr-2 h-4 w-4" />
              )}
              刷新状态
            </Button>
          }
        />

        {workspaceConnectionPrompt ? (
          <Alert>
            <Server strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{workspaceConnectionPrompt}</AlertDescription>
          </Alert>
        ) : null}

        {visibleWorkspaceError ? (
          <Alert variant="destructive">
            <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{visibleWorkspaceError}</AlertDescription>
          </Alert>
        ) : null}

        {state.runHistoryError ? (
          <Alert variant="destructive">
            <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{state.runHistoryError}</AlertDescription>
          </Alert>
        ) : null}

        {firstRunStatus.error ? (
          <Alert variant="destructive">
            <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{firstRunStatus.error}</AlertDescription>
          </Alert>
        ) : null}

        <FirstRunCompletionPanel
          card={firstRunEvidence.validationCard}
          firstRunStatus={firstRunStatusSnapshot || null}
          latestPackage={latestPackage}
          loadingValidationCard={firstRunEvidence.validationCardFetchLoading}
          nextScenarioPacks={firstRunEvidence.nextScenarioPacks}
          nextScenarioPacksError={firstRunEvidence.nextScenarioPacksError}
          nextScenarioPacksLoading={firstRunEvidence.nextScenarioPacksLoading}
          ready={validationReady}
          resultId={resultId}
          run={run}
          workflowRevisionId={workflowRevisionId}
          pilotHandoff={firstRunEvidence.pilotHandoff}
        />

        <WorkflowFirstRunConductorPanel
          action={firstRunConductor.action}
          busy={firstRunConductor.busy}
          error={firstRunConductor.error}
          onContinue={() => void firstRunConductor.continueFirstRun()}
        />

        <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="space-y-5">
            <FirstRunSteps steps={steps} />
            <RunnerReadinessPanel
              canEnsure={Boolean(state.server?.serverId)}
              connected={serverConnected}
              diagnostics={executionDiagnostics}
              diagnosticsError={executionDiagnosticsError}
              diagnosticsLoading={executionDiagnosticsLoading}
              ensuring={ensuringRunner}
              error={runnerError}
              loading={state.loading}
              server={state.server}
              sshStatus={ssh.status}
              onConnect={openConnectDialog}
              onEnsure={() => void ensureRunner()}
              onRefresh={refreshWorkspaceAndFirstRunStatus}
            />
            <SampleAndSubmitPanel
              canSubmit={firstRunCanSubmit}
              loading={state.loading}
              pipelineReady={selectedWorkflowReady}
              sampleCacheEvidence={firstRunStatusSnapshot?.evidence?.sampleCache}
              sampleLoading={state.sampleLoading}
              sampleUploads={state.sampleUploads}
              submitError={firstRunSubmitError || state.submitError}
              submitting={submittingFirstRun || state.submitting}
              workflow={movingPicturesWorkflow}
              workflowLoading={state.loading}
              onPrepareSample={() => void prepareSampleDataAndRefreshStatus()}
              onSubmit={() => void submitFirstRunAndRefreshStatus()}
            />
            <RunReportPanel
              artifacts={artifacts}
              detail={state.runDetail}
              packageLoading={firstRunEvidence.packageLoading}
              previews={previews}
              reportEvidence={firstRunStatusSnapshot?.evidence?.report}
              run={run}
              statusRun={statusRun}
              onRefreshRun={() => void state.refreshRunDetail()}
            />
          </div>

          <div className="space-y-5">
            <ResultPackagePanel
              disabledReason={resultPackageDisabledReason({
                firstRunStatus: firstRunStatusSnapshot || null,
                resultId,
                run,
                workflowRevisionId,
              })}
              error={firstRunEvidence.packageError}
              exporting={firstRunEvidence.exportingPackage}
              finalizationAction={firstRunEvidence.finalizationAction}
              finalizing={firstRunEvidence.finalizingFirstRun}
              latestPackage={latestPackage}
              loading={firstRunEvidence.packageLoading}
              resultId={resultId}
              serverId={state.server?.serverId}
              onFinalize={() => void finalizeAndRefreshStatus()}
              onExport={() => void exportPackageAndRefreshStatus()}
              onRefresh={() => void firstRunEvidence.loadPackageExports()}
            />
            <ValidationCard
              artifacts={artifacts}
              card={firstRunEvidence.validationCard}
              error={firstRunEvidence.validationCardFetchError}
              inputArtifacts={inputArtifacts}
              loadingCard={firstRunEvidence.validationCardFetchLoading}
              packageExport={latestPackage}
              firstRunStatus={firstRunStatusSnapshot || null}
              eligible={validationEligible}
              resultId={resultId}
              run={run}
              sampleUploads={state.sampleUploads}
              server={state.server}
              workflowRevisionId={workflowRevisionId}
            />
          </div>
        </section>
      </div>
    </div>
  );
}

function FirstRunSteps({ steps }: { steps: FirstRunStep[] }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white" data-testid="first-run-step-list">
      <div className="grid divide-y divide-slate-100 md:grid-cols-4 md:divide-x md:divide-y-0 xl:grid-cols-8">
        {steps.map((step, index) => (
          <a
            key={step.id}
            href={step.target}
            className="block min-w-0 px-3 py-3 transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-200"
            data-first-run-step={step.id}
            data-step-state={step.state}
            data-step-target={step.target}
          >
            <div className="flex items-center gap-2">
              <StepStateIcon state={step.state} />
              <span className="text-[11px] font-medium text-slate-400">{String(index + 1).padStart(2, "0")}</span>
            </div>
            <div className={cn("mt-2 truncate text-xs font-semibold", step.state === "blocked" ? "text-red-700" : "text-slate-900")}>
              {step.label}
            </div>
            <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{step.detail}</div>
          </a>
        ))}
      </div>
    </section>
  );
}

function RunnerReadinessPanel({
  canEnsure,
  connected,
  diagnostics,
  diagnosticsError,
  diagnosticsLoading,
  ensuring,
  error,
  loading,
  onConnect,
  onEnsure,
  onRefresh,
  server,
  sshStatus,
}: {
  canEnsure: boolean;
  connected: boolean;
  diagnostics: WorkflowExecutionDiagnostics | null;
  diagnosticsError: string;
  diagnosticsLoading: boolean;
  ensuring: boolean;
  error: string;
  loading: boolean;
  onConnect: () => void;
  onEnsure: () => void;
  onRefresh: () => Promise<void>;
  server: WorkflowServer | null;
  sshStatus: SSHStatus | null;
}) {
  const checks = runnerChecks(server);
  const executionReadiness = diagnostics?.readiness;
  return (
    <section id="runner-readiness" className="scroll-mt-24 rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <Server strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            连接远端与运行环境检查
          </div>
          <div className="mt-1 truncate font-mono text-[11px] text-slate-400">
            {server?.label || server?.serverId || "no server selected"}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button variant="outline" size="sm" className="h-8 px-2.5 text-xs" onClick={onConnect} data-testid="first-run-open-connect">
            <Server strokeWidth={1.5} className="h-3.5 w-3.5" />
            连接远端
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 px-2.5 text-xs"
            disabled={!canEnsure || ensuring || loading}
            onClick={onEnsure}
          >
            {ensuring ? <Loader2 strokeWidth={1.5} className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5" />}
            准备 runner
          </Button>
          <Button variant="ghost" size="sm" className="h-8 px-2 text-xs text-slate-500" disabled={loading} onClick={onRefresh}>
            <RefreshCw strokeWidth={1.5} className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
            刷新
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive" className="mt-3">
          <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {diagnosticsError ? (
        <Alert variant="destructive" className="mt-3">
          <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
          <AlertDescription>{diagnosticsError}</AlertDescription>
        </Alert>
      ) : null}

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <ReadinessCheck label="SSH" ok={connected} detail={connected ? "connected" : "未连接"} />
        <ReadinessCheck label="Runner" ok={Boolean(server?.ready)} detail={server?.runner?.message || server?.message || server?.reasonCode || "未检查"} />
        <ReadinessCheck
          label="Execution"
          ok={executionReadiness?.ok === true}
          detail={executionDiagnosticsDetail(diagnostics, diagnosticsLoading)}
        />
        {checks.map((check) => (
          <ReadinessCheck key={check.label} label={check.label} ok={check.ok} detail={check.detail} />
        ))}
      </div>
      {executionReadiness?.blockingReasons?.length ? (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700" data-testid="first-run-execution-diagnostics-blockers">
          {executionReadiness.blockingReasons.slice(0, 3).map((reason) => reason.code || reason.message || "EXECUTION_NOT_READY").join(" / ")}
        </div>
      ) : null}
      <div className="mt-4" data-testid="first-run-runner-repair">
        <RunnerRepairPanel
          status={sshStatus}
          ensureRunnerBusy={ensuring}
          onEnsureRunner={onEnsure}
          onRefreshStatus={onRefresh}
          className="shadow-none"
        />
      </div>
    </section>
  );
}

function ReadinessCheck({ detail, label, ok }: { detail: string; label: string; ok: boolean }) {
  return (
    <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-800">
        {ok ? (
          <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
        ) : (
          <XCircle strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-red-500" />
        )}
        <span>{label}</span>
      </div>
      <div className="mt-1 truncate text-[11px] text-slate-500">{detail || "未检查"}</div>
    </div>
  );
}

function StepStateIcon({ state }: { state: FirstRunStepState }) {
  if (state === "done") return <CheckCircle2 strokeWidth={1.5} className="h-4 w-4 text-emerald-500" />;
  if (state === "blocked") return <XCircle strokeWidth={1.5} className="h-4 w-4 text-red-500" />;
  if (state === "current") return <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin text-blue-500" />;
  return <span className="h-4 w-4 rounded-full border border-slate-300" />;
}

function firstRunWorkspaceConnectionPrompt(error: string, connected: boolean) {
  if (!/serverId is required/i.test(String(error || ""))) return "";
  return connected ? "远端已连接，正在读取运行环境检查。" : "请先连接远端后继续首跑。";
}
