import {
  Activity,
  Clock3,
  ListTree,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { cn } from "@/lib/utils";

import {
  AGENT_SESSION_OBSERVATION_ERRORS,
  deriveAgentSessionObservation,
  type AgentSessionObservationAttention,
  type AgentSessionObservationTimingStatus,
  type AgentSessionObservationV1,
} from "./agent-session-observation";
import {
  agentStatusLabel,
  type AgentSessionSnapshot,
  type AgentSessionStatus,
} from "./agent-workbench-model";

export type AgentSessionObservationPanelProps = {
  observedAtEpochMs: number;
  snapshot: AgentSessionSnapshot;
};

const ATTENTION_LABELS: Record<AgentSessionObservationAttention, string> = {
  plan_not_started: "需要开始规划",
  planning_recovery_available: "规划可恢复",
  human_approval_required: "需要人工审批",
  plan_failed: "方案失败，等待审查",
  typed_replan_required: "需要类型化重规划",
  run_authorization_pending: "等待独立运行授权",
  terminal: "终态，只读",
};

const KNOWN_OBSERVATION_ERRORS = new Set<string>(
  Object.values(AGENT_SESSION_OBSERVATION_ERRORS)
);
const UNKNOWN_OBSERVATION_ERROR = "AGENT_SESSION_OBSERVATION_DERIVATION_FAILED";

export function AgentSessionObservationPanel({
  observedAtEpochMs,
  snapshot,
}: AgentSessionObservationPanelProps) {
  let observation: AgentSessionObservationV1;
  try {
    observation = deriveAgentSessionObservation(snapshot, observedAtEpochMs);
  } catch (error) {
    return <ObservationError code={observationErrorCode(error)} />;
  }
  const maxReplans =
    observation.counters.replansUsed + observation.counters.replansRemaining;

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white"
      aria-labelledby="agent-session-observation-title"
      data-contract-version={observation.contractVersion}
      data-attention={observation.lifecycle.attention}
      data-status={observation.lifecycle.status}
      data-testid="agent-session-observation"
      data-timing-status={observation.lifecycle.timingStatus}
    >
      <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Activity
              strokeWidth={1.5}
              className="h-4 w-4 text-blue-600"
              aria-hidden="true"
            />
            <h2
              id="agent-session-observation-title"
              className="text-sm font-semibold text-slate-950"
            >
              当前观察
            </h2>
          </div>
          <p className="mt-0.5 text-[11px] text-slate-500">
            由本次原子会话快照在浏览器内只读派生
          </p>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium",
            statusTone(observation.lifecycle.status)
          )}
          data-status={observation.lifecycle.status}
          data-testid="agent-observation-status"
        >
          {agentStatusLabel(observation.lifecycle.status)}
        </span>
      </div>

      <div className="space-y-3 px-4 py-4">
        <div
          className="rounded-lg border border-blue-200 bg-blue-50/70 px-3 py-3"
          data-attention={observation.lifecycle.attention}
          data-testid="agent-observation-attention"
        >
          <div className="text-[10px] font-medium uppercase tracking-wide text-blue-600">
            当前关注
          </div>
          <div className="mt-1 text-sm font-semibold text-blue-950">
            {ATTENTION_LABELS[observation.lifecycle.attention]}
          </div>
          <code className="mt-1 block break-words text-[11px] text-blue-700">
            {observation.lifecycle.attention}
          </code>
          <p className="mt-2 text-[11px] leading-5 text-blue-800">
            这是只读提示，不授权或执行任何控制命令。
          </p>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <ObservationFact
            icon={Clock3}
            label="当前状态持续时间"
            testId="agent-observation-age"
            value={timingValue(
              observation.lifecycle.timingStatus,
              observation.lifecycle.stateAgeSeconds
            )}
            detail={timingDetail(observation.lifecycle.timingStatus)}
            dataValue={observation.lifecycle.timingStatus}
          />
          <ObservationFact
            icon={RotateCcw}
            label="重规划预算"
            testId="agent-observation-replans"
            value={`${observation.counters.replansUsed} / ${maxReplans}`}
            detail="已使用 / 上限；仅此预算有权威事件事实"
          />
          <ObservationFact
            className="col-span-2"
            icon={ListTree}
            label="持久事件"
            testId="agent-observation-events"
            value={`${observation.counters.events} 个 · head #${observation.source.headSequence}`}
            detail="原顺序的公开 sequence 与 prev-link 已验证"
          />
        </div>

        <div
          className="rounded-lg border border-emerald-200 bg-emerald-50/70 px-3 py-3"
          data-runner-full-chain={observation.integrity.runnerFullChain}
          data-testid="agent-observation-integrity"
        >
          <div className="flex items-start gap-2">
            <ShieldCheck
              strokeWidth={1.5}
              className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700"
              aria-hidden="true"
            />
            <div className="min-w-0">
              <code className="block break-words text-[11px] font-semibold text-emerald-900">
                Snapshot endpoint requires full-chain validation
              </code>
              <p className="mt-1 text-[11px] leading-5 text-emerald-800">
                正式 snapshot endpoint 的成功响应要求 runner 完整 hash-chain
                校验；浏览器仅验证 sequence 与 prevEventHash，不能重算已隐去 commandHash 的
                eventHash。
              </p>
              <p className="mt-1 text-[11px] leading-5 text-emerald-800">
                本摘要不展示事件内容、请求身份、操作者、路径或 URI、模型输出、命令哈希或凭据。
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ObservationError({ code }: { code: string }) {
  return (
    <section
      className="rounded-xl border border-red-200 bg-white px-4 py-4"
      aria-labelledby="agent-session-observation-error-title"
      data-error-code={code}
      data-testid="agent-session-observation-error"
    >
      <div className="flex items-start gap-2">
        <Activity
          strokeWidth={1.5}
          className="mt-0.5 h-4 w-4 shrink-0 text-red-600"
          aria-hidden="true"
        />
        <div className="min-w-0">
          <h2
            id="agent-session-observation-error-title"
            className="text-sm font-semibold text-red-900"
          >
            当前观察未通过快照校验
          </h2>
          <code className="mt-2 block break-all text-[11px] text-red-700">{code}</code>
        </div>
      </div>
    </section>
  );
}

function ObservationFact({
  className,
  dataValue,
  detail,
  icon: Icon,
  label,
  testId,
  value,
}: {
  className?: string;
  dataValue?: string;
  detail: string;
  icon: typeof Clock3;
  label: string;
  testId: string;
  value: string;
}) {
  return (
    <div
      className={cn("min-w-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3", className)}
      data-value={dataValue}
      data-testid={testId}
    >
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
        <Icon strokeWidth={1.5} className="h-3.5 w-3.5" aria-hidden="true" />
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-slate-900">{value}</div>
      <p className="mt-1 text-[11px] leading-4 text-slate-500">{detail}</p>
    </div>
  );
}

function timingValue(
  status: AgentSessionObservationTimingStatus,
  stateAgeSeconds: number | null
): string {
  if (status !== "client_estimate" || stateAgeSeconds === null) return "无法估算";
  return formatDuration(stateAgeSeconds);
}

function timingDetail(status: AgentSessionObservationTimingStatus): string {
  if (status === "invalid_timestamp") {
    return "时间异常：持久事件时间戳无法解析。";
  }
  if (status === "clock_regression") {
    return "时间异常：客户端时钟早于状态进入或 head 事件。";
  }
  return "刷新时的客户端估算；不能据此判断 stalled、SLA 或 timeout。";
}

function formatDuration(totalSeconds: number): string {
  if (totalSeconds < 60) return `${totalSeconds} 秒`;
  if (totalSeconds < 3_600) {
    return `${Math.floor(totalSeconds / 60)} 分 ${totalSeconds % 60} 秒`;
  }
  if (totalSeconds < 86_400) {
    return `${Math.floor(totalSeconds / 3_600)} 小时 ${Math.floor(
      (totalSeconds % 3_600) / 60
    )} 分`;
  }
  return `${Math.floor(totalSeconds / 86_400)} 天 ${Math.floor(
    (totalSeconds % 86_400) / 3_600
  )} 小时`;
}

function statusTone(status: AgentSessionStatus): string {
  if (status === "ready_to_run") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (status === "awaiting_approval") {
    return "border-blue-200 bg-blue-50 text-blue-700";
  }
  if (status === "planning") {
    return "border-cyan-200 bg-cyan-50 text-cyan-700";
  }
  if (status === "plan_failed") {
    return "border-red-200 bg-red-50 text-red-700";
  }
  if (status === "changes_requested") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function observationErrorCode(error: unknown): string {
  if (error instanceof Error && KNOWN_OBSERVATION_ERRORS.has(error.message)) {
    return error.message;
  }
  return UNKNOWN_OBSERVATION_ERROR;
}
