import type {
  WorkflowExecutionDiagnostics,
  WorkflowResultPackageExport,
  WorkflowRun,
  WorkflowRunDetail,
  WorkflowServer,
} from "@/app/components/workflows-page-model";
import type { FirstRunStatus } from "./first-run-types";

export const FIRST_RUN_PIPELINE_ID = "moving-pictures-16s-rulegraph-v1";
export const FIRST_RUN_PIPELINE_NAME = "Moving Pictures 16S";

export type FirstRunStepState = "done" | "current" | "waiting" | "blocked";
export type FirstRunStep = {
  id: string;
  label: string;
  detail: string;
  state: FirstRunStepState;
  target: string;
};

export function buildFirstRunSteps(input: {
  firstRunStatus?: FirstRunStatus | null;
  runSubmitted: boolean;
  sampleReady: boolean;
  selectedWorkflowReady: boolean;
  serverConnected: boolean;
  serverReady: boolean;
}): FirstRunStep[] {
  const status = input.firstRunStatus;
  const evidence = status?.evidence;
  const statusRun = evidence?.run || status?.latestEligibleRun || null;
  const hasStatus = Boolean(status);
  const base = [
    stepDefinition("connect", "连接远端", input.serverConnected, "SSH 连接可用", "#runner-readiness"),
    stepDefinition("readiness", "runner readiness", input.serverReady, "运行时、Snakemake、profile 与 pipeline registry 就绪", "#runner-readiness"),
    stepDefinition("select", "选择示例", input.selectedWorkflowReady, FIRST_RUN_PIPELINE_ID, "#sample-data"),
    stepDefinition(
      "sample",
      "准备示例数据",
      hasStatus ? evidence?.sampleCache?.status === "ready" : input.sampleReady,
      "metadata、barcodes、sequences 三个输入",
      "#sample-data"
    ),
    stepDefinition(
      "submit",
      "提交运行",
      hasStatus ? Boolean(statusRun?.runId) : input.runSubmitted,
      "固定 pipeline run 已进入队列",
      "#sample-data"
    ),
    stepDefinition(
      "report",
      "看懂报告",
      evidence?.report?.ready === true,
      "summary、QC、feature table 和 HTML report 已通过服务端验证",
      "#run-report"
    ),
    stepDefinition(
      "package",
      "导出结果包",
      evidence?.resultPackage?.ready === true,
      "完整结果包包含 manifest、产物和证据",
      "#result-package"
    ),
    stepDefinition(
      "evidence-bundle",
      "下载/分享证据包",
      evidence?.validation?.ready === true || status?.status === "ready",
      "结果包、验证卡 JSON/Markdown、pilot handoff 四件套",
      "#evidence-bundle"
    ),
  ] as const;
  const firstIncomplete = base.findIndex(([, , done]) => !done);
  const currentStepId = firstRunStepIdForStage(status?.stage) || base[firstIncomplete]?.[0] || "evidence-bundle";
  const blockedStepId = status?.status === "blocked" ? currentStepId : "";
  return base.map(([id, label, done, detail, target], index) => ({
    id,
    label,
    detail,
    target,
    state: firstRunStepState({ blockedStepId, currentStepId, done, firstIncomplete, id, index }),
  }));
}

function stepDefinition(id: string, label: string, done: boolean, detail: string, target: string) {
  return [id, label, done, detail, target] as const;
}

function firstRunStepIdForStage(stage: string | undefined): string {
  if (stage === "connect_remote") return "connect";
  if (stage === "runner_readiness") return "readiness";
  if (stage === "select_example") return "select";
  if (stage === "prepare_sample_data") return "sample";
  if (stage === "submit_run") return "submit";
  if (stage === "run_in_progress" || stage === "inspect_failed_run" || stage === "report_ready") return "report";
  if (stage === "export_result_package") return "package";
  if (stage === "validation_ready") return "evidence-bundle";
  return "";
}

function firstRunStepState({
  blockedStepId,
  currentStepId,
  done,
  firstIncomplete,
  id,
  index,
}: {
  blockedStepId: string;
  currentStepId: string;
  done: boolean;
  firstIncomplete: number;
  id: string;
  index: number;
}): FirstRunStepState {
  if (done) return "done";
  if (blockedStepId === id) return "blocked";
  if (currentStepId === id || index === firstIncomplete) return "current";
  return "waiting";
}

export function runnerChecks(server: WorkflowServer | null | undefined) {
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

export function executionDiagnosticsDetail(diagnostics: WorkflowExecutionDiagnostics | null, loading: boolean) {
  if (loading) return "checking execution readiness";
  const readiness = diagnostics?.readiness;
  if (!readiness) return "未检查 execution diagnostics";
  if (readiness.ok) return readiness.status || "ok";
  return readiness.reasonCode || readiness.blockingReasons?.[0]?.code || readiness.status || "not ready";
}

export function resultPackageDisabledReason({
  firstRunStatus,
  resultId,
  run,
  workflowRevisionId,
}: {
  firstRunStatus?: FirstRunStatus | null;
  resultId: string;
  run: WorkflowRun | null;
  workflowRevisionId: string;
}) {
  if (firstRunStatus) {
    if (firstRunStatus.evidence?.resultPackage?.ready === true) return "";
    const action = firstRunStatus.nextAction;
    if (action?.code === "FINALIZE_FIRST_RUN") return "";
    if (firstRunStatus.stage === "export_result_package") return "";
    return action?.detail || firstRunStatus.evidence?.resultPackage?.blockedCode || "等待首跑达到结果包导出阶段";
  }
  if (!resultId) return "等待运行产出 resultId";
  if (!run || !isTerminalRun(run)) return "仅 completed/failed 运行可导出";
  if (!workflowRevisionId) return "缺少 WorkflowRevision，当前 runner 需要升级到首跑 revision 绑定版本";
  return "";
}

export function workflowRevisionIdFor(
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

export function isTerminalRun(run: WorkflowRun | null | undefined) {
  return run?.status === "completed" || run?.status === "failed" || run?.status === "error";
}
