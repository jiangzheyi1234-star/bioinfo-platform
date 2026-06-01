"use client";

import { useState } from "react";
import { CheckCircle2, Loader2, PlayCircle, RefreshCw, Trash2, Workflow } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AddedTool, RuleSpecTemplate, ToolContractValidationItem } from "./tools-page-model";
import { ruleSpecReadinessForTool, type ToolRuleReadiness } from "./tool-rule-readiness";
import { PlatformBadge, WrapperBadge } from "./tools-page-ui";
import { ToolRuleSpecEditor } from "./tools-page-rule-spec-editor";

export function ToolsLibrarySection({
  addedTools,
  checkingToolId,
  editingRuleSpecToolId,
  preparingToolIds,
  ruleSpecEditError,
  ruleSpecSavingId,
  toolsError,
  toolsLoading,
  onCancelRuleSpecEdit,
  onCheck,
  onEditRuleSpec,
  onRefresh,
  onRemove,
  onSaveRuleSpec,
}: {
  addedTools: AddedTool[];
  checkingToolId: string;
  editingRuleSpecToolId: string;
  preparingToolIds: string[];
  ruleSpecEditError: string;
  ruleSpecSavingId: string;
  toolsError: string;
  toolsLoading: boolean;
  onCancelRuleSpecEdit: () => void;
  onCheck: (id: string) => void;
  onEditRuleSpec: (id: string) => void;
  onRefresh: () => void;
  onRemove: (id: string) => void;
  onSaveRuleSpec: (id: string, ruleTemplate: RuleSpecTemplate) => void;
}) {
  const [expandedToolId, setExpandedToolId] = useState("");

  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-900">工具</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRefresh}
            className="inline-flex h-7 items-center rounded-md px-2 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            <RefreshCw strokeWidth={1.5} className={cn("mr-1 h-3.5 w-3.5", toolsLoading && "animate-spin")} />
            刷新
          </button>
          <span className="text-xs text-slate-400">{addedTools.length}</span>
        </div>
      </div>

      {toolsError ? (
        <div className="py-3 text-sm text-red-600">{toolsError}</div>
      ) : toolsLoading ? (
        <div className="flex items-center py-3 text-sm text-slate-400">
          <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
          正在读取工具列表
        </div>
      ) : addedTools.length === 0 ? (
        <div className="py-3 text-sm text-slate-400">还没有加入工具</div>
      ) : (
        <div className="overflow-hidden rounded-md border border-slate-200/80 bg-white">
          {addedTools.map((tool) => {
            const editing = editingRuleSpecToolId === tool.id;
            return (
              <ToolContractRow
                key={tool.id}
                expanded={expandedToolId === tool.id || editing}
                editing={editing}
                ruleSpecEditError={ruleSpecEditError}
                ruleSpecSaving={ruleSpecSavingId === tool.id}
                checking={checkingToolId === tool.id || preparingToolIds.includes(tool.id)}
                tool={tool}
                onCancelRuleSpecEdit={onCancelRuleSpecEdit}
                onCheck={() => onCheck(tool.id)}
                onEditRuleSpec={() => onEditRuleSpec(tool.id)}
                onExpand={() => setExpandedToolId((current) => (current === tool.id ? "" : tool.id))}
                onRemove={() => onRemove(tool.id)}
                onSaveRuleSpec={(ruleTemplate) => onSaveRuleSpec(tool.id, ruleTemplate)}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}

function ToolContractRow({
  checking,
  editing,
  expanded,
  ruleSpecEditError,
  ruleSpecSaving,
  tool,
  onCancelRuleSpecEdit,
  onCheck,
  onEditRuleSpec,
  onExpand,
  onRemove,
  onSaveRuleSpec,
}: {
  checking: boolean;
  editing: boolean;
  expanded: boolean;
  ruleSpecEditError: string;
  ruleSpecSaving: boolean;
  tool: AddedTool;
  onCancelRuleSpecEdit: () => void;
  onCheck: () => void;
  onEditRuleSpec: () => void;
  onExpand: () => void;
  onRemove: () => void;
  onSaveRuleSpec: (ruleTemplate: RuleSpecTemplate) => void;
}) {
  const state = ruleSpecReadinessForTool(tool);
  const canCheck = state.kind === "validation-pending" || state.kind === "workflow-ready";
  return (
    <article
      data-node-state={state.kind}
      className="group border-b border-slate-100 last:border-b-0"
    >
      <div className="grid min-h-13 grid-cols-[minmax(0,1fr)_8rem_5.5rem_auto] items-center gap-4 px-3 py-2 transition-colors hover:bg-slate-50/70">
        <button type="button" className="min-w-0 text-left" onClick={onExpand}>
          <div className="flex min-w-0 items-center gap-2">
            <span className={cn("h-2 w-2 shrink-0 rounded-full", state.workflowReady ? "bg-emerald-500" : state.kind === "platform-unsupported" ? "bg-red-500" : "bg-amber-500")} />
            <h3 className="min-w-0 truncate text-sm font-medium text-slate-900">{tool.name}</h3>
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-2 text-[11px] text-slate-400">
            <span className="shrink-0">{tool.sourceLabel}</span>
            <span className="min-w-0 truncate font-mono">{tool.selectedPackageSpec}</span>
          </div>
        </button>

        <button type="button" className="min-w-0 text-left" onClick={onExpand}>
          <RuleSpecNodeReadinessBadge state={state} />
        </button>

        <ToolContractStatusRow tool={tool} />

        <div className="flex shrink-0 items-center justify-end gap-0.5 opacity-80 transition-opacity group-hover:opacity-100">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-slate-400 hover:bg-white hover:text-emerald-600"
            disabled={checking || !canCheck}
            onClick={onCheck}
            title={canCheck ? "验证工具" : "先补全 RuleSpec 和 env"}
          >
            {checking ? (
              <Loader2 strokeWidth={1.5} className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <PlayCircle strokeWidth={1.5} className="h-3.5 w-3.5" />
            )}
            <span className="sr-only">验证工具</span>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-slate-400 hover:bg-white hover:text-blue-600"
            onClick={onEditRuleSpec}
            title="补全 RuleSpec"
          >
            <Workflow strokeWidth={1.5} className="h-3.5 w-3.5" />
            <span className="sr-only">补全 RuleSpec</span>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-slate-400 hover:bg-white hover:text-red-600"
            onClick={onRemove}
            title="移除"
          >
            <Trash2 strokeWidth={1.5} className="h-3.5 w-3.5" />
            <span className="sr-only">移除</span>
          </Button>
        </div>
      </div>

      {expanded ? (
        <div className="border-t border-slate-100 bg-slate-50/30 px-3 py-3">
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
            <ContractStageRail state={state} tool={tool} />
            <div className="flex min-w-0 flex-wrap items-center gap-1.5 lg:justify-end">
              <PlatformBadge item={tool} />
              <WrapperBadge item={tool} />
            </div>
          </div>
          <div className="mt-3 grid gap-2 text-[11px] sm:grid-cols-3">
            <RuleSpecNodeStatusChip label="Action" value={state.actionLabel} warning={!state.hasAction} />
            <RuleSpecNodeStatusChip label="Runtime" value={state.runtimeLabel} warning={!state.hasRuntime} />
            <RuleSpecNodeStatusChip label="Env" value={state.envLabel} warning={!state.hasEnv} />
          </div>
        </div>
      ) : null}

      {editing ? (
        <ToolRuleSpecEditor
          error={ruleSpecEditError}
          saving={ruleSpecSaving}
          tool={tool}
          onCancel={onCancelRuleSpecEdit}
          onSave={onSaveRuleSpec}
        />
      ) : null}
    </article>
  );
}

function ToolContractStatusRow({ tool }: { tool: AddedTool }) {
  const validation = tool.toolContract?.validation || tool.contractStatus;
  if (!validation) return null;
  const items = [validation.dryRun, validation.smokeRun, validation.outputValidation, validation.production];
  const passedCount = items.filter((item) => item?.status === "passed").length;
  return (
    <div className="flex items-center gap-2 text-[11px] text-slate-400" title={`验证进度 ${passedCount}/${items.length}`}>
      <span className="font-mono text-slate-500">{passedCount}/{items.length}</span>
      <div className="flex items-center gap-1">
        <ToolContractStatusDot label="Dry-run" item={validation.dryRun} />
        <ToolContractStatusDot label="Smoke" item={validation.smokeRun} />
        <ToolContractStatusDot label="Output" item={validation.outputValidation} />
        <ToolContractStatusDot label="Production" item={validation.production} />
      </div>
    </div>
  );
}

function ContractStageRail({ state, tool }: { state: RuleSpecNodeState; tool: AddedTool }) {
  const validation = tool.toolContract?.validation || tool.contractStatus;
  const stages = [
    { label: "Package", done: Boolean(tool.selectedPackageSpec) },
    { label: "RuleSpec", done: state.hasAction && state.outputsReady && state.paramsReady },
    { label: "Env", done: state.hasEnv },
    { label: "Dry-run", done: validation?.dryRun?.status === "passed" },
    { label: "Smoke", done: validation?.smokeRun?.status === "passed" },
    { label: "Output", done: validation?.outputValidation?.status === "passed" },
    { label: "Production", done: validation?.production?.status === "passed" },
  ];
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 text-[11px]">
      {stages.map((stage, index) => (
        <span key={stage.label} className={cn("inline-flex items-center gap-1.5", stage.done ? "text-slate-700" : "text-slate-400")}>
          {index > 0 ? <span className="h-px w-2 bg-slate-200" /> : null}
          <span className={cn("h-1.5 w-1.5 rounded-full", stage.done ? "bg-emerald-500" : "bg-slate-300")} />
          {stage.label}
        </span>
      ))}
    </div>
  );
}

function ToolContractStatusDot({
  item,
  label,
}: {
  item?: ToolContractValidationItem;
  label: string;
}) {
  const status = item?.status || "not_run";
  const title =
    [
      item?.code,
      item?.message,
      item?.logPath ? `log=${item.logPath}` : "",
      item?.runId ? `run=${item.runId}` : "",
      item?.artifactCount ? `artifacts=${item.artifactCount}` : "",
      item?.artifactNames ? `artifactNames=${item.artifactNames}` : "",
      item?.evidenceType ? `evidence=${item.evidenceType}` : "",
      item?.databaseId ? `database=${item.databaseId}` : "",
      item?.templateId ? `template=${item.templateId}` : "",
      item?.role ? `role=${item.role}` : "",
      item?.artifactName ? `artifact=${item.artifactName}` : "",
    ]
      .filter(Boolean)
      .join("; ") || `${label}: ${status}`;
  return (
    <span
      className={cn(
        "h-1.5 w-1.5 rounded-full",
        status === "passed"
          ? "bg-emerald-500"
          : status === "failed"
            ? "bg-red-500"
            : "bg-slate-300"
      )}
      title={title}
    />
  );
}

function RuleSpecNodeReadinessBadge({ state }: { state: RuleSpecNodeState }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center text-xs leading-none",
        state.kind === "workflow-ready"
            ? "text-emerald-700"
            : state.kind === "dependency-only"
              ? "text-slate-500"
              : "text-amber-700"
      )}
    >
      {state.kind === "workflow-ready" ? <CheckCircle2 strokeWidth={1.5} className="mr-1 h-3 w-3" /> : null}
      {state.label}
    </span>
  );
}

function RuleSpecNodeStatusChip({
  label,
  warning,
  value,
}: {
  label: string;
  warning?: boolean;
  value: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 min-w-0 items-center justify-between gap-1 rounded border border-slate-200 bg-white px-1.5 leading-none",
        warning ? "text-amber-700" : "text-slate-600"
      )}
      title={`${label}: ${value}`}
    >
      <span className={cn("shrink-0 font-medium", warning ? "text-amber-600" : "text-slate-400")}>{label}</span>
      <span className="min-w-0 truncate font-mono">{value}</span>
    </span>
  );
}

type RuleSpecNodeState = ToolRuleReadiness;
