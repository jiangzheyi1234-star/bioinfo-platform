"use client";

import { CheckCircle2, Loader2, PlayCircle, RefreshCw, Trash2, Workflow } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AddedTool, RuleSpecTemplate, ToolContractValidationItem } from "./tools-page-model";
import { ruleSpecReadinessForTool, type ToolRuleReadiness } from "./tool-rule-readiness";
import { PlatformBadge, SourceBadge, WrapperBadge } from "./tools-page-ui";
import { ToolRuleSpecEditor } from "./tools-page-rule-spec-editor";

export function ToolsLibrarySection({
  addedTools,
  checkingToolId,
  editingRuleSpecToolId,
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
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {addedTools.map((tool) => {
            const editing = editingRuleSpecToolId === tool.id;
            return (
              <RuleSpecNodeCard
                key={tool.id}
                editing={editing}
                ruleSpecEditError={ruleSpecEditError}
                ruleSpecSaving={ruleSpecSavingId === tool.id}
                checking={checkingToolId === tool.id}
                tool={tool}
                onCancelRuleSpecEdit={onCancelRuleSpecEdit}
                onCheck={() => onCheck(tool.id)}
                onEditRuleSpec={() => onEditRuleSpec(tool.id)}
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

function RuleSpecNodeCard({
  checking,
  editing,
  ruleSpecEditError,
  ruleSpecSaving,
  tool,
  onCancelRuleSpecEdit,
  onCheck,
  onEditRuleSpec,
  onRemove,
  onSaveRuleSpec,
}: {
  checking: boolean;
  editing: boolean;
  ruleSpecEditError: string;
  ruleSpecSaving: boolean;
  tool: AddedTool;
  onCancelRuleSpecEdit: () => void;
  onCheck: () => void;
  onEditRuleSpec: () => void;
  onRemove: () => void;
  onSaveRuleSpec: (ruleTemplate: RuleSpecTemplate) => void;
}) {
  const state = ruleSpecReadinessForTool(tool);
  const canCheck = state.kind === "validation-pending" || state.kind === "workflow-ready";
  return (
    <article
      data-node-state={state.kind}
      className={cn(
        "group rounded-md border border-slate-200 bg-white p-3 transition-colors hover:border-slate-300 hover:bg-slate-50/70",
        editing && "col-span-full"
      )}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <h3 className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900">{tool.name}</h3>
            <RuleSpecNodeReadinessBadge state={state} />
          </div>
          <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-1">
            <SourceBadge source={tool.source} label={tool.sourceLabel} />
            <PlatformBadge item={tool} />
            <WrapperBadge item={tool} />
          </div>
          <p className="mt-2 truncate font-mono text-[11px] text-slate-500">{tool.selectedPackageSpec}</p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5 opacity-80 transition-opacity group-hover:opacity-100">
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

      <RuleSpecNodeStatusRow state={state} />
      <ToolContractStatusRow tool={tool} />

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
  return (
    <div className="mt-3 flex items-center gap-1.5">
      <ToolContractStatusChip label="Dry-run" shortLabel="D" item={validation.dryRun} />
      <ToolContractStatusChip label="Smoke" shortLabel="S" item={validation.smokeRun} />
      <ToolContractStatusChip label="Output" shortLabel="O" item={validation.outputValidation} />
      <ToolContractStatusChip label="Production" shortLabel="P" item={validation.production} />
    </div>
  );
}

function ToolContractStatusChip({
  item,
  label,
  shortLabel,
}: {
  item?: ToolContractValidationItem;
  label: string;
  shortLabel: string;
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
        "inline-flex h-5 min-w-5 items-center justify-center rounded border px-1 text-[10px] font-medium leading-none",
        status === "passed"
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : status === "failed"
            ? "border-red-200 bg-red-50 text-red-700"
            : "border-slate-200 bg-slate-50 text-slate-500"
      )}
      title={title}
    >
      {shortLabel}
      {item?.artifactCount ? <span className="shrink-0 font-mono text-[10px]">({item.artifactCount})</span> : null}
    </span>
  );
}

function RuleSpecNodeStatusRow({ state }: { state: RuleSpecNodeState }) {
  return (
    <div className="mt-3 grid grid-cols-3 gap-1 text-[11px]">
      <RuleSpecNodeStatusChip label="I/O" value={`${state.inputs}/${state.outputs}`} warning={!state.outputsReady} />
      <RuleSpecNodeStatusChip label="Env" value={state.hasEnv ? "ok" : "todo"} warning={!state.hasEnv} />
      <RuleSpecNodeStatusChip label="Smoke" value={state.hasSmoke ? "ok" : "todo"} warning={!state.hasSmoke} />
    </div>
  );
}

function RuleSpecNodeReadinessBadge({ state }: { state: RuleSpecNodeState }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded border px-1.5 text-[10px] leading-none",
        state.kind === "workflow-ready"
            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
            : state.kind === "dependency-only"
              ? "border-slate-200 bg-slate-50 text-slate-600"
              : "border-amber-200 bg-amber-50 text-amber-700"
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
        "inline-flex h-6 min-w-0 items-center justify-between gap-1 rounded border px-1.5 leading-none",
        warning ? "border-amber-200 bg-amber-50 text-amber-700" : "border-slate-200 bg-slate-50 text-slate-600"
      )}
      title={`${label}: ${value}`}
    >
      <span className={cn("shrink-0 font-medium", warning ? "text-amber-600" : "text-slate-400")}>{label}</span>
      <span className="min-w-0 truncate font-mono">{value}</span>
    </span>
  );
}

type RuleSpecNodeState = ToolRuleReadiness;
