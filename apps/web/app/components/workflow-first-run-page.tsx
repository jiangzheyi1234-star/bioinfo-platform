"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  FileCheck2,
  Loader2,
  Package,
  Play,
  RefreshCw,
  Rocket,
  Server,
  ShieldCheck,
  UploadCloud,
  XCircle,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { cn } from "@/lib/utils";

import { useSshShell } from "./ssh-shell";
import { useWorkflowsPageState } from "./use-workflows-page-state";
import { downloadFirstRunValidationCard } from "./workflow-first-run-api";
import { WorkflowPageHeader } from "./workflow-page-header";
import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";
import {
  ResultPackagePanel,
  ValidationCard,
  artifactName,
  formatBytes,
  firstRunResultPackageReady,
} from "./workflow-first-run-validation";
import {
  exportWorkflowResultPackage,
  fetchWorkflowResultPackageExports,
} from "./workflows-page-api";
import {
  workflowErrorMessage,
  type WorkflowArtifact,
  type WorkflowArtifactPreview,
  type WorkflowResultPackageExport,
  type WorkflowRun,
  type WorkflowRunDetail,
  type WorkflowUpload,
} from "./workflows-page-model";

const FIRST_RUN_PIPELINE_ID = "moving-pictures-16s-rulegraph-v1";
const FIRST_RUN_PIPELINE_NAME = "Moving Pictures 16S";
const EXPECTED_SAMPLE_ROLES = ["metadata", "barcodes", "sequences"];

type StepState = "done" | "current" | "waiting" | "blocked";
type FirstRunState = ReturnType<typeof useWorkflowsPageState>;
type RulesSummary = NonNullable<NonNullable<WorkflowRunDetail["rules"]>["summary"]>;

type FirstRunStep = { id: string; label: string; detail: string; state: StepState };

export function WorkflowFirstRunPage() {
  const ssh = useSshShell();
  const state = useWorkflowsPageState(FIRST_RUN_PIPELINE_ID);
  const [ensuringRunner, setEnsuringRunner] = useState(false);
  const [runnerError, setRunnerError] = useState("");
  const [packageExports, setPackageExports] = useState<WorkflowResultPackageExport[]>([]);
  const [packageLoading, setPackageLoading] = useState(false);
  const [packageError, setPackageError] = useState("");
  const [exportingPackage, setExportingPackage] = useState(false);
  const [validationCardLoading, setValidationCardLoading] = useState(false);
  const [validationCardError, setValidationCardError] = useState("");

  const run = state.runDetail?.run || state.submittedRun;
  const result = state.runDetail?.results;
  const resultId = result?.resultId || (run?.runId ? `res_${run.runId}` : "");
  const artifacts = result?.artifacts || [];
  const inputArtifacts = result?.inputArtifacts || [];
  const previews = state.runDetail?.previews || [];
  const workflowRevisionId = workflowRevisionIdFor(run, state.runDetail, packageExports[0]);
  const selectedWorkflowReady = state.selectedWorkflow?.id === FIRST_RUN_PIPELINE_ID && state.selectedWorkflow.runnable;
  const serverConnected = Boolean(state.server?.connected);
  const serverReady = Boolean(state.server?.ready);
  const sampleReady = sampleUploadsReady(state.sampleUploads);
  const runSubmitted = Boolean(run?.runId);
  const runTerminal = isTerminalRun(run);
  const runCompleted = run?.status === "completed";
  const runFailed = run?.status === "failed" || run?.status === "error";
  const reportReady = runCompleted && artifacts.length > 0;
  const packageReady = packageExports.some(firstRunResultPackageReady);
  const validationReady = runCompleted && packageReady && Boolean(workflowRevisionId);
  const tablePreview = preferredTablePreview(previews);
  const reportPreview = preferredReportPreview(previews);
  const latestPackage = packageExports[0];

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

  async function downloadValidationCard() {
    if (!run?.runId || validationCardLoading) return;
    setValidationCardLoading(true);
    setValidationCardError("");
    try {
      await downloadFirstRunValidationCard({
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

        <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="space-y-5">
            <FirstRunSteps steps={steps} />
            <RunnerReadinessPanel
              canEnsure={Boolean(state.server?.serverId)}
              connected={serverConnected}
              ensuring={ensuringRunner}
              error={runnerError}
              loading={state.loading}
              ready={serverReady}
              server={state.server}
              onConnect={openConnectDialog}
              onEnsure={() => void ensureRunner()}
              onRefresh={() => void state.loadWorkspace({ forceRefresh: true })}
            />
            <SampleAndSubmitPanel
              canSubmit={state.canSubmit}
              loading={state.loading}
              pipelineReady={selectedWorkflowReady}
              sampleLoading={state.sampleLoading}
              sampleUploads={state.sampleUploads}
              selectedWorkflowDescription={state.selectedWorkflow?.description}
              submitError={state.submitError}
              submitting={state.submitting}
              onPrepareSample={() => void state.loadSampleData()}
              onSubmit={() => void state.submitRun()}
            />
            <RunReportPanel
              artifacts={artifacts}
              detail={state.runDetail}
              packageLoading={packageLoading}
              reportPreview={reportPreview}
              run={run}
              tablePreview={tablePreview}
              onRefreshRun={() => void state.refreshRunDetail()}
            />
          </div>

          <div className="space-y-5">
            <ResultPackagePanel
              disabledReason={resultPackageDisabledReason({ resultId, run, workflowRevisionId })}
              error={packageError}
              exporting={exportingPackage}
              latestPackage={latestPackage}
              loading={packageLoading}
              resultId={resultId}
              onExport={() => void exportPackage()}
              onRefresh={() => void loadPackageExports()}
            />
            <ValidationCard
              artifacts={artifacts}
              error={validationCardError}
              inputArtifacts={inputArtifacts}
              packageExport={latestPackage}
              ready={validationReady}
              resultId={resultId}
              run={run}
              sampleUploads={state.sampleUploads}
              server={state.server}
              downloading={validationCardLoading}
              workflowRevisionId={workflowRevisionId}
              onDownload={() => void downloadValidationCard()}
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
          <div key={step.id} className="min-w-0 px-3 py-3" data-first-run-step={step.id} data-step-state={step.state}>
            <div className="flex items-center gap-2">
              <StepStateIcon state={step.state} />
              <span className="text-[11px] font-medium text-slate-400">{String(index + 1).padStart(2, "0")}</span>
            </div>
            <div className={cn("mt-2 truncate text-xs font-semibold", step.state === "blocked" ? "text-red-700" : "text-slate-900")}>
              {step.label}
            </div>
            <div className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">{step.detail}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function RunnerReadinessPanel({
  canEnsure,
  connected,
  ensuring,
  error,
  loading,
  onConnect,
  onEnsure,
  onRefresh,
  ready,
  server,
}: {
  canEnsure: boolean;
  connected: boolean;
  ensuring: boolean;
  error: string;
  loading: boolean;
  onConnect: () => void;
  onEnsure: () => void;
  onRefresh: () => void;
  ready: boolean;
  server: FirstRunState["server"];
}) {
  const checks = runnerChecks(server);
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
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

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <ReadinessCheck label="SSH" ok={connected} detail={connected ? "connected" : "未连接"} />
        <ReadinessCheck label="Runner" ok={ready} detail={server?.runner?.message || server?.message || server?.reasonCode || "未检查"} />
        {checks.map((check) => (
          <ReadinessCheck key={check.label} label={check.label} ok={check.ok} detail={check.detail} />
        ))}
      </div>
    </section>
  );
}

function SampleAndSubmitPanel({
  canSubmit,
  loading,
  onPrepareSample,
  onSubmit,
  pipelineReady,
  sampleLoading,
  sampleUploads,
  selectedWorkflowDescription,
  submitError,
  submitting,
}: {
  canSubmit: boolean;
  loading: boolean;
  onPrepareSample: () => void;
  onSubmit: () => void;
  pipelineReady: boolean;
  sampleLoading: boolean;
  sampleUploads: WorkflowUpload[];
  selectedWorkflowDescription?: string;
  submitError: string;
  submitting: boolean;
}) {
  const ready = sampleUploadsReady(sampleUploads);
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <UploadCloud strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            选择 Moving Pictures 16S 示例并准备数据
          </div>
          <div className="mt-1 text-xs leading-5 text-slate-500" data-testid="first-run-moving-pictures-pipeline-id">
            {FIRST_RUN_PIPELINE_ID}
          </div>
        </div>
        <span className={cn("rounded-full border px-2 py-1 text-[11px]", pipelineReady ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700")}>
          {pipelineReady ? "WorkflowReady" : "未就绪"}
        </span>
      </div>

      {selectedWorkflowDescription ? (
        <p className="mt-3 text-xs leading-5 text-slate-600">{selectedWorkflowDescription}</p>
      ) : null}

      <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
        <div className="grid gap-2">
          {EXPECTED_SAMPLE_ROLES.map((role) => {
            const upload = sampleUploads.find((item) => item.role === role);
            return (
              <div key={role} className="flex min-w-0 items-center justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
                <div className="min-w-0">
                  <div className="font-medium text-slate-800">{sampleRoleLabel(role)}</div>
                  <div className="mt-0.5 truncate font-mono text-[11px] text-slate-500">{upload?.filename || sampleRoleFilename(role)}</div>
                </div>
                {upload ? (
                  <span className="shrink-0 text-emerald-700">{formatBytes(upload.sizeBytes)}</span>
                ) : (
                  <span className="shrink-0 text-slate-400">待准备</span>
                )}
              </div>
            );
          })}
        </div>
        <div className="space-y-2">
          <Button
            className="h-10 w-full bg-slate-950 text-white hover:bg-slate-800"
            disabled={sampleLoading || loading || !pipelineReady}
            onClick={onPrepareSample}
            data-testid="first-run-prepare-sample-data"
          >
            {sampleLoading ? <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" /> : <UploadCloud strokeWidth={1.5} className="mr-2 h-4 w-4" />}
            准备示例数据
          </Button>
          <Button
            variant="outline"
            className="h-10 w-full bg-white text-slate-700"
            disabled={!canSubmit}
            onClick={onSubmit}
            data-testid="first-run-submit-run"
          >
            {submitting ? <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" /> : <Play strokeWidth={1.5} className="mr-2 h-4 w-4" />}
            提交运行
          </Button>
          <div className="text-[11px] leading-4 text-slate-400">
            {ready ? `${sampleUploads.length} 个输入已上传` : "使用官方三文件样例作为唯一输入来源"}
          </div>
        </div>
      </div>

      {submitError ? (
        <Alert variant="destructive" className="mt-4">
          <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
          <AlertDescription>{submitError}</AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}

function RunReportPanel({
  artifacts,
  detail,
  onRefreshRun,
  packageLoading,
  reportPreview,
  run,
  tablePreview,
}: {
  artifacts: WorkflowArtifact[];
  detail: WorkflowRunDetail | null;
  onRefreshRun: () => void;
  packageLoading: boolean;
  reportPreview?: WorkflowArtifactPreview;
  run: WorkflowRun | null;
  tablePreview?: WorkflowArtifactPreview;
}) {
  const rulesSummary = detail?.rules?.summary;
  const stdoutCount = detail?.logs.stdout?.lines?.length || 0;
  const stderrCount = detail?.logs.stderr?.lines?.length || 0;
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <FileCheck2 strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            看懂报告
          </div>
          <div className="mt-1 truncate font-mono text-[11px] text-slate-400">{run?.runId || "run not submitted"}</div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {run?.runId ? (
            <Button asChild variant="outline" size="sm" className="h-8 px-2.5 text-xs">
              <Link href={`/workflows/results/detail?run=${encodeURIComponent(run.runId)}`}>
                <ArrowRight strokeWidth={1.5} className="h-3.5 w-3.5" />
                完整结果
              </Link>
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" className="h-8 px-2 text-xs text-slate-500" disabled={!run?.runId || packageLoading} onClick={onRefreshRun}>
            <RefreshCw strokeWidth={1.5} className="h-3.5 w-3.5" />
            刷新
          </Button>
        </div>
      </div>

      {run ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="状态" value={runStatusLabel(run.status)} tone={run.status === "completed" ? "success" : run.status === "failed" || run.status === "error" ? "danger" : "info"} />
          <Metric label="阶段" value={run.stage || "-"} />
          <Metric label="规则" value={formatRuleSummary(rulesSummary)} />
          <Metric label="日志" value={`${stdoutCount} stdout / ${stderrCount} stderr`} />
        </div>
      ) : (
        <div className="mt-4 rounded-md border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-400">
          尚未提交运行
        </div>
      )}

      {tablePreview?.preview?.columns?.length ? <TablePreview preview={tablePreview} /> : null}
      {reportPreview?.artifact ? (
        <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          HTML 报告已生成：<span className="font-mono text-slate-800">{artifactName(reportPreview.artifact)}</span>
        </div>
      ) : null}
      {artifacts.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {artifacts.map((artifact) => (
            <span key={artifact.artifactId} className="inline-flex max-w-full items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600">
              <Package strokeWidth={1.5} className="h-3 w-3 shrink-0 text-slate-400" />
              <span className="truncate">{artifactName(artifact)}</span>
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function TablePreview({ preview }: { preview: WorkflowArtifactPreview }) {
  const columns = preview.preview?.columns || [];
  const rows = preview.preview?.rows || [];
  if (columns.length === 0 || rows.length === 0) return null;
  return (
    <div className="mt-4 overflow-hidden rounded-md border border-slate-200">
      <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-3 py-2">
        <span className="truncate text-xs font-medium text-slate-800">{preview.artifact ? artifactName(preview.artifact) : "summary.tsv"}</span>
        <span className="shrink-0 text-[11px] text-slate-400">{rows.length} 行预览</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-white text-slate-500">
            <tr>
              {columns.slice(0, 6).map((column) => (
                <th key={column} className="whitespace-nowrap px-3 py-2 font-medium">{column}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.slice(0, 5).map((row, index) => (
              <tr key={index}>
                {columns.slice(0, 6).map((column, columnIndex) => (
                  <td key={`${column}-${columnIndex}`} className="max-w-[180px] truncate px-3 py-2 text-slate-700">
                    {row[columnIndex] || ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
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

function Metric({ label, tone = "neutral", value }: { label: string; tone?: "neutral" | "success" | "danger" | "info"; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] font-medium text-slate-400">{label}</div>
      <div
        className={cn(
          "mt-1 truncate text-sm font-semibold",
          tone === "success" ? "text-emerald-700" : tone === "danger" ? "text-red-700" : tone === "info" ? "text-blue-700" : "text-slate-900"
        )}
      >
        {value}
      </div>
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
    ["connect", "连接远端", input.serverConnected, "SSH 连接可用"],
    ["readiness", "runner readiness", input.serverReady, "运行时、Snakemake、profile 与 pipeline registry 就绪"],
    ["select", "选择示例", input.selectedWorkflowReady, FIRST_RUN_PIPELINE_ID],
    ["sample", "准备示例数据", input.sampleReady, "metadata、barcodes、sequences 三个输入"],
    ["submit", "提交运行", input.runSubmitted, "固定 pipeline run 已进入队列"],
    ["report", "看懂报告", input.reportReady, "产物、预览、rule 状态可读"],
    ["package", "导出结果包", input.packageReady, "完整结果包包含 manifest、产物和证据"],
    ["card", "生成验证卡", input.validationReady, "客户可读的输入、版本、hash、下载摘要"],
  ] as const;
  const firstIncomplete = base.findIndex(([, , done]) => !done);
  return base.map(([id, label, done, detail], index) => ({
    id,
    label,
    detail,
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

function sampleUploadsReady(uploads: WorkflowUpload[]) {
  const roles = new Set(uploads.map((upload) => upload.role));
  return EXPECTED_SAMPLE_ROLES.every((role) => roles.has(role));
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

function preferredTablePreview(previews: WorkflowArtifactPreview[]) {
  const tables = previews.filter((preview) => preview.preview?.kind === "table");
  return (
    tables.find((preview) => preview.artifact && artifactName(preview.artifact) === "summary.tsv") ||
    tables.find((preview) => preview.artifact && artifactName(preview.artifact) === "qc-summary.tsv") ||
    tables[0]
  );
}

function preferredReportPreview(previews: WorkflowArtifactPreview[]) {
  return previews.find((preview) => preview.artifact && artifactName(preview.artifact) === "run-report.html");
}

function formatRuleSummary(summary: RulesSummary | undefined) {
  if (!summary) return "-";
  const count = summary.ruleCount ?? 0;
  const failed = summary.failedRuleCount ?? 0;
  return failed ? `${count} rules / ${failed} failed` : `${count} rules`;
}

function runStatusLabel(status?: string) {
  if (status === "completed") return "完成";
  if (status === "failed" || status === "error") return "失败";
  if (status === "running") return "运行中";
  return status || "-";
}

function sampleRoleLabel(role: string) {
  if (role === "metadata") return "sample metadata";
  if (role === "barcodes") return "barcode reads";
  if (role === "sequences") return "sequence reads";
  return role;
}

function sampleRoleFilename(role: string) {
  if (role === "metadata") return "sample-metadata.tsv";
  if (role === "barcodes") return "barcodes.fastq.gz";
  if (role === "sequences") return "sequences.fastq.gz";
  return role;
}
