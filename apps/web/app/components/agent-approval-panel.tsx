"use client";

import { useState } from "react";
import {
  AlertCircle,
  Ban,
  CheckCircle2,
  FileClock,
  Loader2,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import {
  agentStatusLabel,
  formatAgentBytes,
  type AgentPlanRevision,
  type AgentSession,
} from "./agent-workbench-model";

export type AgentApprovalAction = "approve" | "request_changes" | "cancel" | "refresh" | "busy" | "";

export type AgentApprovalPanelProps = {
  busyAction?: AgentApprovalAction;
  error?: string;
  onApprove?: (reason: string) => void | Promise<void>;
  onCancel?: () => void | Promise<void>;
  onRefresh?: () => void | Promise<void>;
  onRequestChanges?: (reason: string) => void | Promise<void>;
  onStartNew?: () => void;
  plan?: AgentPlanRevision | null;
  session: AgentSession;
};

export function AgentApprovalPanel({
  busyAction = "",
  error = "",
  onApprove,
  onCancel,
  onRefresh,
  onRequestChanges,
  onStartNew,
  plan = null,
  session,
}: AgentApprovalPanelProps) {
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [changesOpen, setChangesOpen] = useState(false);
  const [approvalConfirmed, setApprovalConfirmed] = useState(false);
  const [approvalReason, setApprovalReason] = useState("");
  const [changeReason, setChangeReason] = useState("");
  const busy = Boolean(busyAction);

  function closeApproval(nextOpen: boolean) {
    setApprovalOpen(nextOpen);
    if (!nextOpen) {
      setApprovalConfirmed(false);
      setApprovalReason("");
    }
  }

  function closeChanges(nextOpen: boolean) {
    setChangesOpen(nextOpen);
    if (!nextOpen) setChangeReason("");
  }

  function approve() {
    if (!plan || !approvalConfirmed || !onApprove || busy) return;
    void onApprove(approvalReason.trim());
    closeApproval(false);
  }

  function requestChanges() {
    const reason = changeReason.trim();
    if (!plan || !reason || !onRequestChanges || busy) return;
    void onRequestChanges(reason);
    closeChanges(false);
  }

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white"
      aria-labelledby="agent-approval-panel-title"
      data-session-status={session.status}
      data-testid="agent-approval-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <h2 id="agent-approval-panel-title" className="text-sm font-semibold text-slate-950">人工控制点</h2>
          <p className="mt-1 text-xs text-slate-500">有后果的动作必须以类型化命令持久记录。</p>
        </div>
        <span className={cn("rounded-full border px-2.5 py-1 text-xs font-medium", statusTone(session.status))}>
          {agentStatusLabel(session.status)}
        </span>
      </div>

      <div className="space-y-4 px-5 py-5">
        {error ? (
          <Alert variant="destructive" data-testid="agent-approval-error">
            <AlertCircle strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
            <AlertTitle>控制命令未完成</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {session.status === "awaiting_approval" ? (
          plan ? (
            <>
              <ApprovalPreview plan={plan} />
              <div className="flex flex-wrap justify-end gap-2">
                {onCancel ? <CancelButton busyAction={busyAction} disabled={busy} onCancel={onCancel} sessionId={session.sessionId} /> : null}
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy || !onRequestChanges}
                  onClick={() => setChangesOpen(true)}
                  data-testid="agent-request-changes-open"
                >
                  <RotateCcw strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
                  记录修改意见
                </Button>
                <Button
                  type="button"
                  disabled={busy || !onApprove || !plan.validation.valid}
                  onClick={() => setApprovalOpen(true)}
                  data-testid="agent-approve-open"
                >
                  {busyAction === "approve" ? (
                    <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <ShieldCheck strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
                  )}
                  批准并编译
                </Button>
              </div>
            </>
          ) : (
            <Alert variant="destructive">
              <AlertTitle>PlanRevision 尚未加载</AlertTitle>
              <AlertDescription>审批按钮保持关闭；刷新后必须重新核对精确 planHash。</AlertDescription>
            </Alert>
          )
        ) : null}

        {session.status === "ready_to_run" ? (
          <>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-4" data-testid="agent-ready-to-run">
              <div className="flex items-start gap-3">
                <CheckCircle2 strokeWidth={1.5} className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" aria-hidden="true" />
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-emerald-900">不可变 WorkflowRevision 已编译</div>
                  <div className="mt-2 break-all rounded-md border border-emerald-200 bg-white/80 px-3 py-2 font-mono text-xs text-emerald-800" data-testid="agent-workflow-revision-id">
                    {session.workflowRevisionId || "workflowRevisionId pending"}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-emerald-800">
                    本次审批没有提交 Run，也没有创建 run command、attempt 或 run event。运行授权属于后续独立控制点。
                  </p>
                </div>
              </div>
            </div>
            <UnsupportedReplan
              busyAction={busyAction}
              onCancel={onCancel}
              onRefresh={onRefresh}
              onStartNew={onStartNew}
              sessionId={session.sessionId}
              status="ready_to_run"
            />
          </>
        ) : null}

        {session.status === "plan_failed" || session.status === "changes_requested" ? (
          <UnsupportedReplan
            busyAction={busyAction}
            errorCode={session.lastErrorCode}
            onCancel={onCancel}
            onRefresh={onRefresh}
            onStartNew={onStartNew}
            sessionId={session.sessionId}
            status={session.status}
          />
        ) : null}

        {session.status === "created" || session.status === "planning" ? (
          <div className="rounded-lg border border-cyan-200 bg-cyan-50 px-4 py-3 text-xs text-cyan-900">
            <div className="flex items-start gap-2">
              <FileClock strokeWidth={1.5} className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <div>
                <div className="font-medium">{session.status === "planning" ? "规划命令可以安全重放" : "目标已持久化"}</div>
                <p className="mt-1 leading-5 text-cyan-800">
                  {session.status === "planning"
                    ? "刷新或恢复必须复用 durable agent.plan_requested 的 requestId 与 idempotencyKey。"
                    : "生成方案后才会出现 hash-bound 编译审批。"}
                </p>
              </div>
            </div>
            <div className="mt-3 flex justify-end gap-2">
              {onCancel ? <CancelButton busyAction={busyAction} disabled={busy} onCancel={onCancel} sessionId={session.sessionId} /> : null}
              {onRefresh ? <RefreshButton busyAction={busyAction} onRefresh={onRefresh} /> : null}
            </div>
          </div>
        ) : null}

        {session.status === "cancelled" ? (
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-700">
            <div className="flex items-center gap-2 font-medium">
              <Ban strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
              会话已取消，历史记录保持只读
            </div>
            <div className="mt-3 flex justify-end gap-2">
              {onRefresh ? <RefreshButton busyAction={busyAction} onRefresh={onRefresh} /> : null}
              {onStartNew ? <Button type="button" variant="outline" onClick={onStartNew}>新建会话</Button> : null}
            </div>
          </div>
        ) : null}
      </div>

      {plan ? (
        <ApprovalDialog
          busy={busy}
          confirmed={approvalConfirmed}
          open={approvalOpen}
          plan={plan}
          reason={approvalReason}
          onApprove={approve}
          onConfirmedChange={setApprovalConfirmed}
          onOpenChange={closeApproval}
          onReasonChange={setApprovalReason}
        />
      ) : null}

      {plan ? (
        <RequestChangesDialog
          busy={busy}
          open={changesOpen}
          plan={plan}
          reason={changeReason}
          onOpenChange={closeChanges}
          onReasonChange={setChangeReason}
          onSubmit={requestChanges}
        />
      ) : null}
    </section>
  );
}

function ApprovalPreview({ plan }: { plan: AgentPlanRevision }) {
  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/60 px-4 py-4" data-testid="agent-approval-preview">
      <div className="flex items-start gap-3">
        <ShieldCheck strokeWidth={1.5} className="mt-0.5 h-5 w-5 shrink-0 text-blue-700" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-blue-950">等待批准：compile_workflow_revision</div>
          <p className="mt-1 text-xs leading-5 text-blue-800">只编译当前 hash 绑定的 draft；不会提交或执行 Run。</p>
          <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-[112px_minmax(0,1fr)]">
            <Fact label="target" value={`${plan.draftId}@${plan.draftRevision}`} />
            <Fact label="plan" value={plan.planRevisionId} />
            <Fact label="planHash" value={plan.planHash} breakAll />
            <Fact label="tools" value={plan.validation.orderedSteps.map((step) => step.toolRevisionId).join(", ")} breakAll />
          </dl>
        </div>
      </div>
    </div>
  );
}

function ApprovalDialog({
  busy,
  confirmed,
  onApprove,
  onConfirmedChange,
  onOpenChange,
  onReasonChange,
  open,
  plan,
  reason,
}: {
  busy: boolean;
  confirmed: boolean;
  onApprove: () => void;
  onConfirmedChange: (checked: boolean) => void;
  onOpenChange: (open: boolean) => void;
  onReasonChange: (reason: string) => void;
  open: boolean;
  plan: AgentPlanRevision;
  reason: string;
}) {
  const input = plan.proposal.draft.inputs[0];
  const digestValue = input?.metadata.sha256;
  const sizeValue = input?.metadata.sizeBytes;
  const inputDigest = typeof digestValue === "string" && digestValue ? digestValue : "—";
  const inputSize = typeof sizeValue === "number" && Number.isFinite(sizeValue) ? sizeValue : 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl" data-testid="agent-approve-dialog">
        <DialogHeader>
          <DialogTitle>批准并编译不可变 WorkflowRevision</DialogTitle>
          <DialogDescription>
            本审批精确绑定到当前 PlanRevision、draft revision 和 planHash；状态变化后旧审批会被拒绝。
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 grid gap-3 text-xs md:grid-cols-2">
          <ApprovalFact title="Action" value="compile_workflow_revision" />
          <ApprovalFact title="Affected revision" value={`${plan.draftId}@${plan.draftRevision}`} />
          <ApprovalFact title="Target plan" value={`${plan.planRevisionId} / generation ${plan.planGeneration}`} />
          <ApprovalFact title="Input" value={`${input?.filename || "input"} / ${formatAgentBytes(inputSize)} / sha256 ${inputDigest}`} />
          <ApprovalFact title="Arguments" value={plan.validation.orderedSteps.map((step) => `${step.id}:${step.toolRevisionId}`).join(" · ")} />
          <ApprovalFact title="Outputs" value={plan.proposal.draft.outputs.map((output) => output.as).join(", ")} />
          <ApprovalFact title="Risk" value="创建一个不可变 WorkflowRevision；不运行、不发布、不删除数据。" />
          <ApprovalFact
            title="Budget impact"
            value={`不消耗 run submission；ceiling turns=${plan.budget.maxModelTurns}, tools=${plan.budget.maxToolCalls}, replans=${plan.budget.maxReplans}.`}
          />
        </div>

        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-950 px-3 py-3 text-slate-100">
          <div className="text-[10px] font-medium uppercase tracking-wide text-slate-400">planHash</div>
          <code className="mt-1 block break-all text-xs leading-5">{plan.planHash}</code>
        </div>

        <div className="mt-4 space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="agent-approval-reason">审批备注（可选）</Label>
            <Input
              id="agent-approval-reason"
              value={reason}
              onChange={(event) => onReasonChange(event.target.value)}
              placeholder="已核对输入摘要、工具修订、资源和输出。"
              disabled={busy}
            />
          </div>
          <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-3">
            <Checkbox
              id="agent-approval-review-confirmation"
              checked={confirmed}
              onCheckedChange={(value) => onConfirmedChange(value === true)}
              disabled={busy}
              data-testid="agent-approval-review-confirmation"
            />
            <Label htmlFor="agent-approval-review-confirmation" className="cursor-pointer text-xs leading-5 text-blue-900">
              我已核对 input digest、精确 toolRevisionId、资源、exposed outputs、风险与预算影响。
            </Label>
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <DialogClose asChild>
            <Button type="button" variant="ghost" disabled={busy}>返回审查</Button>
          </DialogClose>
          <Button type="button" disabled={!confirmed || busy} onClick={onApprove} data-testid="agent-approve-confirm">
            {busy ? <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" /> : <ShieldCheck strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />}
            确认批准并编译
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RequestChangesDialog({
  busy,
  onOpenChange,
  onReasonChange,
  onSubmit,
  open,
  plan,
  reason,
}: {
  busy: boolean;
  onOpenChange: (open: boolean) => void;
  onReasonChange: (reason: string) => void;
  onSubmit: () => void;
  open: boolean;
  plan: AgentPlanRevision;
  reason: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="agent-request-changes-dialog">
        <DialogHeader>
          <DialogTitle>记录修改意见</DialogTitle>
          <DialogDescription>
            意见会作为不可变审批事实绑定到 {plan.planRevisionId}，不会静默修改当前 draft。
          </DialogDescription>
        </DialogHeader>
        <Alert className="mt-4 border-amber-200 bg-amber-50 text-amber-900">
          <AlertCircle strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>当前 FASTQ adapter 不支持 typed adjustment</AlertTitle>
          <AlertDescription>
            记录意见后，同一会话不能按自由文本自动 replan。恢复动作是基于修改后的目标或输入新建会话，旧 lineage 保留。
          </AlertDescription>
        </Alert>
        <div className="mt-4 space-y-1.5">
          <Label htmlFor="agent-change-reason">修改原因</Label>
          <textarea
            id="agent-change-reason"
            value={reason}
            onChange={(event) => onReasonChange(event.target.value)}
            disabled={busy}
            rows={5}
            className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-slate-300 focus:ring-2 focus:ring-slate-200 disabled:opacity-50"
            placeholder="说明需要改变的科学目标、输入或证据要求。"
            data-testid="agent-change-reason"
          />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <DialogClose asChild>
            <Button type="button" variant="ghost" disabled={busy}>返回审查</Button>
          </DialogClose>
          <Button type="button" variant="outline" disabled={!reason.trim() || busy} onClick={onSubmit} data-testid="agent-request-changes-confirm">
            记录修改意见
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function UnsupportedReplan({
  busyAction,
  errorCode = "WORKFLOW_FASTQ_QC_REPLAN_ADJUSTMENT_UNSUPPORTED",
  onCancel,
  onRefresh,
  onStartNew,
  sessionId,
  status,
}: {
  busyAction: AgentApprovalAction;
  errorCode?: string;
  onCancel?: () => void | Promise<void>;
  onRefresh?: () => void | Promise<void>;
  onStartNew?: () => void;
  sessionId: string;
  status: "plan_failed" | "changes_requested" | "ready_to_run";
}) {
  const busy = Boolean(busyAction);
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-4" data-testid="agent-replan-unsupported">
      <div className="flex items-start gap-3">
        <Ban strokeWidth={1.5} className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-amber-950">当前适配器不支持自由文本重规划</div>
          <p className="mt-1 text-xs leading-5 text-amber-800">
            状态 {status} 的 lineage 已持久化。只有 adapter 声明并实际应用 typed adjustment 后，replan 才会启用。
          </p>
          <div className="mt-2 break-all rounded-md border border-amber-200 bg-white/70 px-2.5 py-2 font-mono text-[11px] text-amber-800">
            {errorCode || "WORKFLOW_FASTQ_QC_REPLAN_ADJUSTMENT_UNSUPPORTED"}
          </div>
          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <Button type="button" variant="outline" disabled title="当前 FASTQ adapter 没有 typed adjustment schema">
              重规划（当前不支持）
            </Button>
            {onRefresh ? <RefreshButton busyAction={busyAction} onRefresh={onRefresh} /> : null}
            {onCancel ? <CancelButton busyAction={busyAction} disabled={busy} onCancel={onCancel} sessionId={sessionId} /> : null}
            {onStartNew ? <Button type="button" onClick={onStartNew} disabled={busy}>按新目标创建会话</Button> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function CancelButton({
  busyAction,
  disabled,
  onCancel,
  sessionId,
}: {
  busyAction: AgentApprovalAction;
  disabled: boolean;
  onCancel: () => void | Promise<void>;
  sessionId: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        className="text-red-700 hover:bg-red-50"
        disabled={disabled}
        onClick={() => setOpen(true)}
        data-testid="agent-cancel-session"
      >
        {busyAction === "cancel" ? <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Ban strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />}
        取消会话
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg" data-testid="agent-cancel-dialog">
          <DialogHeader>
            <DialogTitle>确认取消 Agent 会话</DialogTitle>
            <DialogDescription>
              取消会进入不可逆终态；目标、PlanRevision、审批与事件历史会保留为只读审计事实。
            </DialogDescription>
          </DialogHeader>
          <div className="break-all rounded-md border border-red-200 bg-red-50 px-3 py-2 font-mono text-xs text-red-800">
            {sessionId}
          </div>
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="outline">返回审查</Button>
            </DialogClose>
            <Button
              type="button"
              variant="destructive"
              disabled={disabled}
              onClick={() => {
                setOpen(false);
                void onCancel();
              }}
              data-testid="agent-cancel-confirm"
            >
              确认取消并保留历史
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function RefreshButton({ busyAction, onRefresh }: { busyAction: AgentApprovalAction; onRefresh: () => void | Promise<void> }) {
  return (
    <Button type="button" variant="outline" disabled={Boolean(busyAction)} onClick={() => void onRefresh()}>
      {busyAction === "refresh" ? <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />}
      刷新状态
    </Button>
  );
}

function ApprovalFact({ title, value }: { title: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{title}</div>
      <div className="mt-1 break-all font-mono text-[11px] leading-5 text-slate-700">{value || "—"}</div>
    </div>
  );
}

function Fact({ breakAll = false, label, value }: { breakAll?: boolean; label: string; value: string }) {
  return (
    <>
      <dt className="text-blue-600">{label}</dt>
      <dd className={cn("min-w-0 font-mono text-blue-950", breakAll ? "break-all" : "truncate")}>{value || "—"}</dd>
    </>
  );
}

function statusTone(status: AgentSession["status"]) {
  if (status === "ready_to_run") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "awaiting_approval") return "border-blue-200 bg-blue-50 text-blue-700";
  if (status === "planning") return "border-cyan-200 bg-cyan-50 text-cyan-700";
  if (status === "plan_failed") return "border-red-200 bg-red-50 text-red-700";
  if (status === "changes_requested") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}
