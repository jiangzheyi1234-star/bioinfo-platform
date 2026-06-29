import type {
  WorkflowExecutionDiagnostics,
  WorkflowResultPackageExport,
  WorkflowRun,
  WorkflowRunDetail,
  WorkflowServer,
} from "@/app/components/workflows-page-model";

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
    ["evidence-bundle", "下载/分享证据包", input.validationReady, "结果包、验证卡 JSON/Markdown、pilot handoff 四件套", "#evidence-bundle"],
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

export function mergePackageExport(
  item: WorkflowResultPackageExport,
  current: WorkflowResultPackageExport[]
): WorkflowResultPackageExport[] {
  const packageExportId = item.packageExportId || "";
  if (!packageExportId) return [item, ...current];
  return [item, ...current.filter((candidate) => candidate.packageExportId !== packageExportId)];
}
