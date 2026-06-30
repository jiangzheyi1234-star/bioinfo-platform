"use client";

import { useState } from "react";
import { ArrowRight, CheckCircle2, Loader2, Play, RefreshCw, Server, ShieldCheck, UploadCloud } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { workflowErrorMessage } from "@/app/components/workflows-page-model";
import type { FirstRunNextAction, FirstRunStatus } from "../_domain/first-run-types";

export type FirstRunContinueActionCode =
  | "CONNECT_REMOTE"
  | "ENSURE_RUNNER"
  | "REFRESH_WORKFLOW"
  | "PREPARE_SAMPLE_DATA"
  | "SUBMIT_RUN"
  | "REFRESH_RUN"
  | "INSPECT_FAILED_RUN"
  | "FINALIZE_FIRST_RUN"
  | "COMPLETE";

export type FirstRunContinueAction = {
  blockedCode?: string;
  code: FirstRunContinueActionCode;
  detail: string;
  disabled?: boolean;
  label: string;
  target: string;
  tone: "success" | "warning" | "danger" | "info";
};

export type FirstRunContinueActionInput = {
  canSubmit: boolean;
  firstRunStatus: FirstRunStatus | null;
  runSubmitted: boolean;
  sampleReady: boolean;
  selectedWorkflowReady: boolean;
  serverConnected: boolean;
  serverReady: boolean;
};

export function buildFirstRunContinueAction(input: FirstRunContinueActionInput): FirstRunContinueAction {
  const status = input.firstRunStatus;
  const evidence = status?.evidence;
  const statusRun = evidence?.run || status?.latestEligibleRun || null;
  const hasStatus = Boolean(status);
  const sampleReady = hasStatus ? evidence?.sampleCache?.status === "ready" : input.sampleReady;
  const runSubmitted = hasStatus ? Boolean(statusRun?.runId) : input.runSubmitted;
  if (status?.nextAction) {
    const action = continueActionFromStatus(status.nextAction);
    const statusAllowsSubmit =
      status.stage === "submit_run" &&
      status.evidence?.server?.ready === true &&
      status.evidence?.execution?.ready === true &&
      status.evidence?.workflow?.ready === true;
    if (action.code !== "SUBMIT_RUN" || input.canSubmit || statusAllowsSubmit) return action;
    return {
      ...action,
      detail: action.detail || "等待输入、runner 和 workflow readiness 全部通过后提交。",
      disabled: true,
      tone: "warning",
    };
  }
  if (!input.serverConnected) {
    return {
      code: "CONNECT_REMOTE",
      detail: "先建立 SSH 连接；首跑不会在未连接状态下猜测 runner。",
      label: "连接远端",
      target: "#runner-readiness",
      tone: "warning",
    };
  }
  if (!input.serverReady) {
    return {
      code: "ENSURE_RUNNER",
      detail: "执行 runner readiness，确认 Snakemake、profile、pipeline registry 和 execution diagnostics。",
      label: "准备 runner",
      target: "#runner-readiness",
      tone: "warning",
    };
  }
  if (!input.selectedWorkflowReady) {
    return {
      code: "REFRESH_WORKFLOW",
      detail: "workflow catalog 必须明确包含 Moving Pictures 16S，首跑不会退回其他流程。",
      label: "刷新首跑示例",
      target: "#sample-data",
      tone: "danger",
    };
  }
  if (!sampleReady) {
    return {
      code: "PREPARE_SAMPLE_DATA",
      detail: "下载或复用官方三文件样例，并记录 checksum 与 prep proof。",
      label: "准备示例数据",
      target: "#sample-data",
      tone: "info",
    };
  }
  if (!runSubmitted) {
    return {
      code: "SUBMIT_RUN",
      detail: input.canSubmit ? "提交 Moving Pictures 16S 首跑。" : "等待输入、runner 和 workflow readiness 全部通过后提交。",
      disabled: !input.canSubmit,
      label: "提交运行",
      target: "#sample-data",
      tone: input.canSubmit ? "info" : "warning",
    };
  }
  return {
    code: "REFRESH_RUN",
    detail: "等待服务端首跑状态聚合返回 run、报告、结果包和验证卡状态。",
    label: "刷新首跑状态",
    target: "#run-report",
    tone: "warning",
  };
}

export function useFirstRunConductor({
  busy,
  input,
  onConnect,
  onEnsureRunner,
  onFinalize,
  onPrepareSampleData,
  onRefreshRun,
  onRefreshWorkspace,
  onSubmitRun,
}: {
  busy: boolean;
  input: FirstRunContinueActionInput;
  onConnect: () => void;
  onEnsureRunner: () => Promise<void>;
  onFinalize: () => Promise<void>;
  onPrepareSampleData: () => Promise<void>;
  onRefreshRun: () => Promise<void>;
  onRefreshWorkspace: () => Promise<void>;
  onSubmitRun: () => Promise<void>;
}) {
  const [continuing, setContinuing] = useState(false);
  const [error, setError] = useState("");
  const action = buildFirstRunContinueAction(input);

  async function continueFirstRun() {
    if (continuing) return;
    setContinuing(true);
    setError("");
    try {
      if (action.code === "CONNECT_REMOTE") {
        onConnect();
      } else if (action.code === "ENSURE_RUNNER") {
        await onEnsureRunner();
      } else if (action.code === "REFRESH_WORKFLOW") {
        await onRefreshWorkspace();
      } else if (action.code === "PREPARE_SAMPLE_DATA") {
        await onPrepareSampleData();
      } else if (action.code === "SUBMIT_RUN") {
        await onSubmitRun();
      } else if (action.code === "REFRESH_RUN" || action.code === "INSPECT_FAILED_RUN") {
        await onRefreshRun();
        window.location.hash = action.target;
      } else if (action.code === "FINALIZE_FIRST_RUN") {
        await onFinalize();
      }
    } catch (err) {
      setError(workflowErrorMessage(err, "继续首跑失败"));
    } finally {
      setContinuing(false);
    }
  }

  return {
    action,
    busy: busy || continuing,
    continueFirstRun,
    error,
  };
}

export function WorkflowFirstRunConductorPanel({
  action,
  busy,
  error,
  onContinue,
}: {
  action: FirstRunContinueAction;
  busy: boolean;
  error: string;
  onContinue: () => void;
}) {
  const disabled = busy || action.disabled === true || action.code === "COMPLETE";
  return (
    <section
      className={cn("rounded-lg border p-4", conductorToneClass(action.tone))}
      data-testid="first-run-conductor"
      data-first-run-next-action={action.code}
      data-first-run-next-target={action.target}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold">
            {actionIcon(action.code, busy)}
            <span>{action.label}</span>
          </div>
          <div className="mt-1 text-xs leading-5">{action.detail}</div>
          {error ? <div className="mt-2 text-xs font-medium text-red-700">{error}</div> : null}
        </div>
        <Button
          type="button"
          className={cn("h-9 shrink-0 px-3 text-xs", action.tone === "success" ? "bg-emerald-700 hover:bg-emerald-800" : "bg-slate-950 hover:bg-slate-800")}
          disabled={disabled}
          onClick={onContinue}
          data-testid="first-run-continue"
        >
          {busy ? <Loader2 strokeWidth={1.5} className="mr-2 h-3.5 w-3.5 animate-spin" /> : <ArrowRight strokeWidth={1.5} className="mr-2 h-3.5 w-3.5" />}
          继续首跑
        </Button>
      </div>
    </section>
  );
}

function actionIcon(code: FirstRunContinueActionCode, busy: boolean) {
  if (busy) return <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" />;
  if (code === "CONNECT_REMOTE") return <Server strokeWidth={1.5} className="h-4 w-4" />;
  if (code === "ENSURE_RUNNER") return <ShieldCheck strokeWidth={1.5} className="h-4 w-4" />;
  if (code === "PREPARE_SAMPLE_DATA") return <UploadCloud strokeWidth={1.5} className="h-4 w-4" />;
  if (code === "SUBMIT_RUN") return <Play strokeWidth={1.5} className="h-4 w-4" />;
  if (code === "COMPLETE") return <CheckCircle2 strokeWidth={1.5} className="h-4 w-4" />;
  return <RefreshCw strokeWidth={1.5} className="h-4 w-4" />;
}

function continueActionFromStatus(action: FirstRunNextAction): FirstRunContinueAction {
  const code = firstRunContinueActionCode(action.code);
  return {
    blockedCode: action.blockedCode,
    code,
    detail: action.detail || defaultActionDetail(code),
    disabled: action.disabled === true || code === "COMPLETE",
    label: action.label || defaultActionLabel(code),
    target: action.target || defaultActionTarget(code),
    tone: actionTone(code),
  };
}

function firstRunContinueActionCode(code: string | undefined): FirstRunContinueActionCode {
  if (
    code === "CONNECT_REMOTE" ||
    code === "ENSURE_RUNNER" ||
    code === "REFRESH_WORKFLOW" ||
    code === "PREPARE_SAMPLE_DATA" ||
    code === "SUBMIT_RUN" ||
    code === "REFRESH_RUN" ||
    code === "INSPECT_FAILED_RUN" ||
    code === "FINALIZE_FIRST_RUN" ||
    code === "COMPLETE"
  ) {
    return code;
  }
  return "REFRESH_RUN";
}

function defaultActionDetail(code: FirstRunContinueActionCode) {
  if (code === "INSPECT_FAILED_RUN") return "首跑失败，先查看 rule-level 失败定位、stderr 和日志证据。";
  if (code === "FINALIZE_FIRST_RUN") return "生成或复用完整结果包，并生成验证卡与证据包清单。";
  if (code === "COMPLETE") return "结果包、验证卡和 pilot handoff 已准备好。";
  return "刷新服务端首跑状态。";
}

function defaultActionLabel(code: FirstRunContinueActionCode) {
  if (code === "INSPECT_FAILED_RUN") return "定位失败";
  if (code === "FINALIZE_FIRST_RUN") return "完成首跑";
  if (code === "COMPLETE") return "首跑已完成";
  return "刷新首跑状态";
}

function defaultActionTarget(code: FirstRunContinueActionCode) {
  if (code === "FINALIZE_FIRST_RUN") return "#result-package";
  if (code === "COMPLETE") return "#evidence-bundle";
  return "#run-report";
}

function actionTone(code: FirstRunContinueActionCode): FirstRunContinueAction["tone"] {
  if (code === "INSPECT_FAILED_RUN") return "danger";
  if (code === "FINALIZE_FIRST_RUN" || code === "COMPLETE") return "success";
  if (code === "CONNECT_REMOTE" || code === "ENSURE_RUNNER") return "warning";
  return "info";
}

function conductorToneClass(tone: FirstRunContinueAction["tone"]) {
  if (tone === "success") return "border-emerald-200 bg-emerald-50 text-emerald-900";
  if (tone === "danger") return "border-red-200 bg-red-50 text-red-900";
  if (tone === "warning") return "border-amber-200 bg-amber-50 text-amber-900";
  return "border-blue-200 bg-blue-50 text-blue-900";
}
