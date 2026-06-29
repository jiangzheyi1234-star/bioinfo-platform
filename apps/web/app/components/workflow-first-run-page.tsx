"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { cn } from "@/lib/utils";

import { useSshShell } from "./ssh-shell";
import { useWorkflowsPageState } from "./use-workflows-page-state";
import { FirstRunCompletionPanel, firstRunValidationCardPassed } from "./workflow-first-run-completion";
import {
  downloadFirstRunHandoffManifest,
  downloadFirstRunValidationCard,
  downloadFirstRunValidationCardMarkdown,
  finalizeFirstRun,
  fetchFirstRunValidationCard,
  type FirstRunFinalizationNextAction,
  type FirstRunPilotHandoff,
  type FirstRunValidationCard,
} from "./workflow-first-run-api";
import { SampleAndSubmitPanel, sampleUploadsReady } from "./workflow-first-run-sample-submit";
import { WorkflowPageHeader } from "./workflow-page-header";
import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";
import { RunReportPanel } from "./workflow-first-run-report";
import {
  ResultPackagePanel,
  ValidationCard,
  firstRunResultPackageReady,
} from "./workflow-first-run-validation";
import {
  exportWorkflowResultPackage,
  fetchWorkflowScenarioPacks,
  fetchWorkflowServerExecutionDiagnostics,
  fetchWorkflowResultPackageExports,
} from "./workflows-page-api";
import {
  workflowErrorMessage,
  type WorkflowExecutionDiagnostics,
  type WorkflowResultPackageExport,
  type WorkflowRun,
  type WorkflowRunDetail,
  type WorkflowScenarioPack,
} from "./workflows-page-model";

const FIRST_RUN_PIPELINE_ID = "moving-pictures-16s-rulegraph-v1";
const FIRST_RUN_PIPELINE_NAME = "Moving Pictures 16S";

type StepState = "done" | "current" | "waiting" | "blocked";
type FirstRunState = ReturnType<typeof useWorkflowsPageState>;

type FirstRunStep = { id: string; label: string; detail: string; state: StepState; target: string };

export function WorkflowFirstRunPage() {
  const ssh = useSshShell();
  const state = useWorkflowsPageState(FIRST_RUN_PIPELINE_ID, { autoResumeLatestRun: true });
  const [ensuringRunner, setEnsuringRunner] = useState(false);
  const [runnerError, setRunnerError] = useState("");
  const [executionDiagnostics, setExecutionDiagnostics] = useState<WorkflowExecutionDiagnostics | null>(null);
  const [executionDiagnosticsLoading, setExecutionDiagnosticsLoading] = useState(false);
  const [executionDiagnosticsError, setExecutionDiagnosticsError] = useState("");
  const [packageExports, setPackageExports] = useState<WorkflowResultPackageExport[]>([]);
  const [packageLoading, setPackageLoading] = useState(false);
  const [packageError, setPackageError] = useState("");
  const [exportingPackage, setExportingPackage] = useState(false);
  const [finalizingFirstRun, setFinalizingFirstRun] = useState(false);
  const [finalizationAction, setFinalizationAction] = useState<FirstRunFinalizationNextAction | null>(null);
  const [pilotHandoff, setPilotHandoff] = useState<FirstRunPilotHandoff | null>(null);
  const [validationCard, setValidationCard] = useState<FirstRunValidationCard | null>(null);
  const [validationCardFetchLoading, setValidationCardFetchLoading] = useState(false);
  const [validationCardFetchError, setValidationCardFetchError] = useState("");
  const [validationCardLoading, setValidationCardLoading] = useState(false);
  const [validationCardError, setValidationCardError] = useState("");
  const [nextScenarioPacks, setNextScenarioPacks] = useState<WorkflowScenarioPack[]>([]);
  const [nextScenarioPacksLoading, setNextScenarioPacksLoading] = useState(false);
  const [nextScenarioPacksError, setNextScenarioPacksError] = useState("");

  const run = state.runDetail?.run || state.submittedRun;
  const result = state.runDetail?.results;
  const resultId = result?.resultId || (run?.runId ? `res_${run.runId}` : "");
  const artifacts = result?.artifacts || [];
  const inputArtifacts = result?.inputArtifacts || [];
  const previews = state.runDetail?.previews || [];
  const readyPackage = packageExports.find(firstRunResultPackageReady);
  const latestPackage = readyPackage || packageExports[0];
  const workflowRevisionId = workflowRevisionIdFor(run, state.runDetail, latestPackage);
  const movingPicturesWorkflow = state.catalog.find((item) => item.id === FIRST_RUN_PIPELINE_ID) || null;
  const selectedWorkflowReady = Boolean(movingPicturesWorkflow?.runnable);
  const serverConnected = Boolean(state.server?.connected);
  const executionReady = executionDiagnostics?.readiness?.ok === true;
  const serverReady = Boolean(state.server?.ready) && executionReady;
  const sampleReady = sampleUploadsReady(state.sampleUploads);
  const runSubmitted = Boolean(run?.runId);
  const runTerminal = isTerminalRun(run);
  const runCompleted = run?.status === "completed";
  const runFailed = run?.status === "failed" || run?.status === "error";
  const reportReady = runCompleted && artifacts.length > 0;
  const packageReady = Boolean(readyPackage);
  const validationEligible = runCompleted && packageReady && Boolean(workflowRevisionId);
  const validationReady = validationEligible && firstRunValidationCardPassed(validationCard);

  const steps = useMemo(
    () =>
      buildFirstRunSteps({
        packageReady,
        reportReady,
        runFailed,
        runSubmitted,
        sampleReady,
        selectedWorkflowReady,
        serverConnected,
        serverReady,
        validationReady,
      }),
    [
      packageReady,
      reportReady,
      runFailed,
      runSubmitted,
      sampleReady,
      selectedWorkflowReady,
      serverConnected,
      serverReady,
      validationReady,
    ]
  );

  const loadPackageExports = useCallback(async () => {
    if (!resultId || !runTerminal) {
      setPackageExports([]);
      setPackageError("");
      return;
    }
    setPackageLoading(true);
    setPackageError("");
    try {
      setPackageExports(await fetchWorkflowResultPackageExports(resultId));
    } catch (err) {
      setPackageError(workflowErrorMessage(err, "结果包记录加载失败"));
    } finally {
      setPackageLoading(false);
    }
  }, [resultId, runTerminal]);

  useEffect(() => {
    void loadPackageExports();
  }, [loadPackageExports]);

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

  useEffect(() => {
    void loadExecutionDiagnostics();
  }, [loadExecutionDiagnostics]);

  const loadValidationCard = useCallback(async () => {
    if (!run?.runId || !validationEligible) {
      setValidationCard(null);
      setValidationCardFetchError("");
      return;
    }
    setValidationCardFetchLoading(true);
    setValidationCardFetchError("");
    try {
      setValidationCard(await fetchFirstRunValidationCard(run.runId, { serverId: state.server?.serverId }));
    } catch (err) {
      setValidationCard(null);
      setValidationCardFetchError(workflowErrorMessage(err, "验证卡加载失败"));
    } finally {
      setValidationCardFetchLoading(false);
    }
  }, [run?.runId, state.server?.serverId, validationEligible]);

  useEffect(() => {
    void loadValidationCard();
  }, [loadValidationCard]);

  const loadNextScenarioPacks = useCallback(async () => {
    if (!validationReady) {
      setNextScenarioPacks([]);
      setNextScenarioPacksError("");
      return;
    }
    setNextScenarioPacksLoading(true);
    setNextScenarioPacksError("");
    try {
      const packs = await fetchWorkflowScenarioPacks();
      setNextScenarioPacks(packs.filter((pack) => pack.scenarioId !== "moving-pictures-16s"));
    } catch (err) {
      setNextScenarioPacks([]);
      setNextScenarioPacksError(workflowErrorMessage(err, "下一批试点场景读取失败"));
    } finally {
      setNextScenarioPacksLoading(false);
    }
  }, [validationReady]);

  useEffect(() => {
    void loadNextScenarioPacks();
  }, [loadNextScenarioPacks]);

  function openConnectDialog() {
    ssh.clearFormError();
    ssh.setDialogOpen(true);
  }

  async function ensureRunner() {
    if (!state.server?.serverId || ensuringRunner) return;
    setEnsuringRunner(true);
    setRunnerError("");
    try {
      await requestLocalApiJson("POST", `/api/v1/servers/${encodeURIComponent(state.server.serverId)}/ensure-runner`, {
        cache: "no-store",
      });
      await state.loadWorkspace({ forceRefresh: true });
      await loadExecutionDiagnostics();
    } catch (err) {
      setRunnerError(workflowErrorMessage(err, "runner readiness 准备失败"));
    } finally {
      setEnsuringRunner(false);
    }
  }

  async function exportPackage() {
    if (!resultId || exportingPackage) return;
    setExportingPackage(true);
    setPackageError("");
    try {
      const exported = await exportWorkflowResultPackage(resultId, true);
      setPackageExports((current) => mergePackageExport(exported, current));
      await state.refreshRunDetail();
    } catch (err) {
      setPackageError(workflowErrorMessage(err, "结果包导出失败"));
    } finally {
      setExportingPackage(false);
    }
  }

  async function finalizeRun() {
    if (!run?.runId || finalizingFirstRun) return;
    setFinalizingFirstRun(true);
    setPackageError("");
    setValidationCardError("");
    setFinalizationAction(null);
    try {
      const finalized = await finalizeFirstRun(run.runId, {
        actor: "first-run-ui",
        serverId: state.server?.serverId,
      });
      if (finalized.status !== "ready" || !finalized.validationCard) {
        setFinalizationAction(finalized.nextAction || null);
        if (!finalized.nextAction) setPackageError("首跑完成被阻塞");
        return;
      }
      const packageExport = finalized.resultPackage;
      if (packageExport?.packageExportId) {
        setPackageExports((current) => mergePackageExport(packageExport, current));
      }
      setPilotHandoff(finalized.pilotHandoff || null);
      setValidationCard(finalized.validationCard);
      await state.refreshRunDetail();
    } catch (err) {
      setPackageError(workflowErrorMessage(err, "首跑完成失败"));
    } finally {
      setFinalizingFirstRun(false);
    }
  }

  async function downloadValidationCard() {
    if (!run?.runId || validationCardLoading) return;
    setValidationCardLoading(true);
    setValidationCardError("");
    try {
      await downloadFirstRunValidationCard({
        card: validationCard,
        resultId,
        runId: run.runId,
        serverId: state.server?.serverId,
      });
    } catch (err) {
      setValidationCardError(workflowErrorMessage(err, "验证卡生成失败"));
    } finally {
      setValidationCardLoading(false);
    }
  }

  async function downloadValidationCardMarkdown() {
    if (!run?.runId || validationCardLoading) return;
    setValidationCardLoading(true);
    setValidationCardError("");
    try {
      await downloadFirstRunValidationCardMarkdown({
        card: validationCard,
        resultId,
        runId: run.runId,
        serverId: state.server?.serverId,
      });
    } catch (err) {
      setValidationCardError(workflowErrorMessage(err, "验证卡 Markdown 生成失败"));
    } finally {
      setValidationCardLoading(false);
    }
  }

  async function downloadHandoffManifest() {
    if (!run?.runId || validationCardLoading) return;
    setValidationCardLoading(true);
    setValidationCardError("");
    try {
      await downloadFirstRunHandoffManifest({
        card: validationCard,
        resultId,
        runId: run.runId,
        serverId: state.server?.serverId,
      });
    } catch (err) {
      setValidationCardError(workflowErrorMessage(err, "交接清单生成失败"));
    } finally {
      setValidationCardLoading(false);
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
              onClick={() => void state.loadWorkspace({ forceRefresh: true })}
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

        {state.error ? (
          <Alert variant="destructive">
            <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{state.error}</AlertDescription>
          </Alert>
        ) : null}

        {state.runHistoryError ? (
          <Alert variant="destructive">
            <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
            <AlertDescription>{state.runHistoryError}</AlertDescription>
          </Alert>
        ) : null}

        <FirstRunCompletionPanel
          card={validationCard}
          downloadingValidationCard={validationCardLoading}
          latestPackage={latestPackage}
          loadingValidationCard={validationCardFetchLoading}
          nextScenarioPacks={nextScenarioPacks}
          nextScenarioPacksError={nextScenarioPacksError}
          nextScenarioPacksLoading={nextScenarioPacksLoading}
          ready={validationReady}
          resultId={resultId}
          run={run}
          workflowRevisionId={workflowRevisionId}
          onDownloadValidationCard={() => void downloadValidationCard()}
          onDownloadValidationCardMarkdown={() => void downloadValidationCardMarkdown()}
          onDownloadHandoffManifest={() => void downloadHandoffManifest()}
          pilotHandoff={pilotHandoff}
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
              onConnect={openConnectDialog}
              onEnsure={() => void ensureRunner()}
              onRefresh={() => {
                void state.loadWorkspace({ forceRefresh: true });
                void loadExecutionDiagnostics();
              }}
            />
            <SampleAndSubmitPanel
              canSubmit={state.canSubmit && executionReady && selectedWorkflowReady && sampleReady}
              loading={state.loading}
              pipelineReady={selectedWorkflowReady}
              sampleLoading={state.sampleLoading}
              sampleUploads={state.sampleUploads}
              submitError={state.submitError}
              submitting={state.submitting}
              workflow={movingPicturesWorkflow}
              workflowLoading={state.loading}
              onPrepareSample={() => void state.loadSampleData()}
              onSubmit={() => void state.submitRun()}
            />
            <RunReportPanel
              artifacts={artifacts}
              detail={state.runDetail}
              packageLoading={packageLoading}
              previews={previews}
              run={run}
              onRefreshRun={() => void state.refreshRunDetail()}
            />
          </div>

          <div className="space-y-5">
            <ResultPackagePanel
              disabledReason={resultPackageDisabledReason({ resultId, run, workflowRevisionId })}
              error={packageError}
              exporting={exportingPackage}
              finalizationAction={finalizationAction}
              finalizing={finalizingFirstRun}
              latestPackage={latestPackage}
              loading={packageLoading}
              resultId={resultId}
              onFinalize={() => void finalizeRun()}
              onExport={() => void exportPackage()}
              onRefresh={() => void loadPackageExports()}
            />
            <ValidationCard
              artifacts={artifacts}
              card={validationCard}
              error={validationCardError || validationCardFetchError}
              inputArtifacts={inputArtifacts}
              loadingCard={validationCardFetchLoading}
              packageExport={latestPackage}
              eligible={validationEligible}
              resultId={resultId}
              run={run}
              sampleUploads={state.sampleUploads}
              server={state.server}
              downloading={validationCardLoading}
              workflowRevisionId={workflowRevisionId}
              onDownload={() => void downloadValidationCard()}
              onDownloadMarkdown={() => void downloadValidationCardMarkdown()}
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
  onRefresh: () => void;
  server: FirstRunState["server"];
}) {
  const checks = runnerChecks(server);
  const executionReadiness = diagnostics?.readiness;
  return (
    <section id="runner-readiness" className="scroll-mt-24 rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <Server strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            连接远端与 runner readiness
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

function StepStateIcon({ state }: { state: StepState }) {
  if (state === "done") return <CheckCircle2 strokeWidth={1.5} className="h-4 w-4 text-emerald-500" />;
  if (state === "blocked") return <XCircle strokeWidth={1.5} className="h-4 w-4 text-red-500" />;
  if (state === "current") return <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin text-blue-500" />;
  return <span className="h-4 w-4 rounded-full border border-slate-300" />;
}

function buildFirstRunSteps(input: {
  packageReady: boolean;
  reportReady: boolean;
  runFailed: boolean;
  runSubmitted: boolean;
  sampleReady: boolean;
  selectedWorkflowReady: boolean;
  serverConnected: boolean;
  serverReady: boolean;
  validationReady: boolean;
}): FirstRunStep[] {
  const base = [
    ["connect", "连接远端", input.serverConnected, "SSH 连接可用", "#runner-readiness"],
    ["readiness", "runner readiness", input.serverReady, "运行时、Snakemake、profile 与 pipeline registry 就绪", "#runner-readiness"],
    ["select", "选择示例", input.selectedWorkflowReady, FIRST_RUN_PIPELINE_ID, "#sample-data"],
    ["sample", "准备示例数据", input.sampleReady, "metadata、barcodes、sequences 三个输入", "#sample-data"],
    ["submit", "提交运行", input.runSubmitted, "固定 pipeline run 已进入队列", "#sample-data"],
    ["report", "看懂报告", input.reportReady, "产物、预览、rule 状态可读", "#run-report"],
    ["package", "导出结果包", input.packageReady, "完整结果包包含 manifest、产物和证据", "#result-package"],
    ["card", "生成验证卡", input.validationReady, "客户可读的输入、版本、hash、下载摘要", "#validation-card"],
  ] as const;
  const firstIncomplete = base.findIndex(([, , done]) => !done);
  return base.map(([id, label, done, detail, target], index) => ({
    id,
    label,
    detail,
    target,
    state: done ? "done" : input.runFailed && index > 4 ? "blocked" : index === firstIncomplete ? "current" : "waiting",
  }));
}

function runnerChecks(server: FirstRunState["server"]) {
  const runtime = server?.health?.workflowRuntime;
  const registry = server?.health?.pipelineRegistry;
  return [
    {
      label: "Snakemake",
      ok: Boolean(runtime?.snakemakeVersion),
      detail: runtime?.snakemakeVersion || runtime?.message || "",
    },
    {
      label: "Profile",
      ok: runtime?.workflowProfileOk === true || Boolean(server?.runner?.bootstrapMetadata?.workflow_profile?.written),
      detail: runtime?.workflowProfileMessage || runtime?.workflowProfilePath || "",
    },
    {
      label: "Pipelines",
      ok: Boolean(registry?.ok),
      detail: typeof registry?.count === "number" ? `${registry.count} 个 pipeline` : registry?.message || "",
    },
    {
      label: "Canary",
      ok: Boolean(server?.runner?.bootstrapMetadata?.canary?.ok),
      detail: server?.runner?.bootstrapMetadata?.canary?.status || server?.runner?.bootstrapMetadata?.canary?.message || "",
    },
  ];
}

function executionDiagnosticsDetail(diagnostics: WorkflowExecutionDiagnostics | null, loading: boolean) {
  if (loading) return "checking execution readiness";
  const readiness = diagnostics?.readiness;
  if (!readiness) return "未检查 execution diagnostics";
  if (readiness.ok) return readiness.status || "ok";
  return readiness.reasonCode || readiness.blockingReasons?.[0]?.code || readiness.status || "not ready";
}

function resultPackageDisabledReason({
  resultId,
  run,
  workflowRevisionId,
}: {
  resultId: string;
  run: WorkflowRun | null;
  workflowRevisionId: string;
}) {
  if (!resultId) return "等待运行产出 resultId";
  if (!run || !isTerminalRun(run)) return "仅 completed/failed 运行可导出";
  if (!workflowRevisionId) return "缺少 WorkflowRevision，当前 runner 需要升级到首跑 revision 绑定版本";
  return "";
}

function workflowRevisionIdFor(
  run: WorkflowRun | null | undefined,
  detail: WorkflowRunDetail | null | undefined,
  packageExport?: WorkflowResultPackageExport
) {
  return (
    run?.workflowRevisionId ||
    run?.runSpec?.workflowRevisionId ||
    detail?.run.workflowRevisionId ||
    detail?.run.runSpec?.workflowRevisionId ||
    packageExport?.workflowRevisionId ||
    ""
  );
}

function isTerminalRun(run: WorkflowRun | null | undefined) {
  return run?.status === "completed" || run?.status === "failed" || run?.status === "error";
}

function mergePackageExport(
  item: WorkflowResultPackageExport,
  current: WorkflowResultPackageExport[]
): WorkflowResultPackageExport[] {
  const packageExportId = item.packageExportId || "";
  if (!packageExportId) return [item, ...current];
  return [item, ...current.filter((candidate) => candidate.packageExportId !== packageExportId)];
}
