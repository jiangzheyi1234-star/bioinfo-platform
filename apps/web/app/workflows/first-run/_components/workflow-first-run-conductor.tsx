"use client";

import { useState } from "react";
import { ArrowRight, CheckCircle2, Loader2, Play, RefreshCw, Server, ShieldCheck, UploadCloud } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { workflowErrorMessage } from "@/app/components/workflows-page-model";

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
  code: FirstRunContinueActionCode;
  detail: string;
  disabled?: boolean;
  label: string;
  target: string;
  tone: "success" | "warning" | "danger" | "info";
};

export type FirstRunContinueActionInput = {
  canSubmit: boolean;
  packageReady: boolean;
  reportReady: boolean;
  runCompleted: boolean;
  runFailed: boolean;
  runSubmitted: boolean;
  runTerminal: boolean;
  sampleReady: boolean;
  selectedWorkflowReady: boolean;
  serverConnected: boolean;
  serverReady: boolean;
  validationEligible: boolean;
  validationReady: boolean;
  workflowRevisionId: string;
};

export function buildFirstRunContinueAction(input: FirstRunContinueActionInput): FirstRunContinueAction {
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
  if (!input.sampleReady) {
    return {
      code: "PREPARE_SAMPLE_DATA",
      detail: "下载或复用官方三文件样例，并记录 checksum 与 prep proof。",
      label: "准备示例数据",
      target: "#sample-data",
      tone: "info",
    };
  }
  if (!input.runSubmitted) {
    return {
      code: "SUBMIT_RUN",
      detail: input.canSubmit ? "提交 Moving Pictures 16S 首跑。" : "等待输入、runner 和 workflow readiness 全部通过后提交。",
      disabled: !input.canSubmit,
      label: "提交运行",
      target: "#sample-data",
      tone: input.canSubmit ? "info" : "warning",
    };
  }
  if (input.runFailed) {
    return {
      code: "INSPECT_FAILED_RUN",
      detail: "首跑失败，先查看 rule-level 失败定位、stderr 和日志证据。",
      label: "定位失败",
      target: "#run-report",
      tone: "danger",
    };
  }
  if (!input.runTerminal) {
    return {
      code: "REFRESH_RUN",
      detail: "运行已提交，继续刷新状态、rule 事件和日志证据。",
      label: "刷新运行状态",
      target: "#run-report",
      tone: "info",
    };
  }
  if (!input.reportReady) {
    return {
      code: "REFRESH_RUN",
      detail: "等待 summary、QC、feature table 和 HTML report 进入结果视图。",
      label: "读取报告",
      target: "#run-report",
      tone: "warning",
    };
  }
  if (!input.validationReady) {
    const blocked = !input.runCompleted || !input.workflowRevisionId;
    return {
      code: "FINALIZE_FIRST_RUN",
      detail: blocked
        ? "必须是 completed 运行且带 WorkflowRevision，才能生成完整结果包和验证卡。"
        : input.packageReady || input.validationEligible
          ? "生成或复用完整结果包，并生成验证卡与证据包清单。"
          : "等待完整结果包、WorkflowRevision 和服务端验证卡条件。",
      disabled: blocked,
      label: "完成首跑",
      target: "#result-package",
      tone: blocked ? "warning" : "success",
    };
  }
  return {
    code: "COMPLETE",
    detail: "结果包、验证卡和 pilot handoff 已准备好。",
    disabled: true,
    label: "首跑已完成",
    target: "#evidence-bundle",
    tone: "success",
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

function conductorToneClass(tone: FirstRunContinueAction["tone"]) {
  if (tone === "success") return "border-emerald-200 bg-emerald-50 text-emerald-900";
  if (tone === "danger") return "border-red-200 bg-red-50 text-red-900";
  if (tone === "warning") return "border-amber-200 bg-amber-50 text-amber-900";
  return "border-blue-200 bg-blue-50 text-blue-900";
}
