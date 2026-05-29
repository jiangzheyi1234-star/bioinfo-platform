"use client";

import { CheckCircle2, Loader2, RefreshCw, Trash2, Workflow } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AddedTool, RuleSpecTemplate } from "./tools-page-model";
import { PlatformBadge, RulePortPreview, SourceBadge, WrapperBadge } from "./tools-page-ui";
import { ToolRuleSpecEditor } from "./tools-page-rule-spec-editor";

export function ToolsLibrarySection({
  addedTools,
  editingRuleSpecToolId,
  ruleSpecEditError,
  ruleSpecSavingId,
  toolsError,
  toolsLoading,
  onCancelRuleSpecEdit,
  onEditRuleSpec,
  onRefresh,
  onRemove,
  onSaveRuleSpec,
}: {
  addedTools: AddedTool[];
  editingRuleSpecToolId: string;
  ruleSpecEditError: string;
  ruleSpecSavingId: string;
  toolsError: string;
  toolsLoading: boolean;
  onCancelRuleSpecEdit: () => void;
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
        <div className="grid grid-cols-1 gap-x-8 gap-y-3 xl:grid-cols-2">
          {addedTools.map((tool) => {
            const editing = editingRuleSpecToolId === tool.id;
            return (
              <RuleSpecNodeCard
                key={tool.id}
                editing={editing}
                ruleSpecEditError={ruleSpecEditError}
                ruleSpecSaving={ruleSpecSavingId === tool.id}
                tool={tool}
                onCancelRuleSpecEdit={onCancelRuleSpecEdit}
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
  editing,
  ruleSpecEditError,
  ruleSpecSaving,
  tool,
  onCancelRuleSpecEdit,
  onEditRuleSpec,
  onRemove,
  onSaveRuleSpec,
}: {
  editing: boolean;
  ruleSpecEditError: string;
  ruleSpecSaving: boolean;
  tool: AddedTool;
  onCancelRuleSpecEdit: () => void;
  onEditRuleSpec: () => void;
  onRemove: () => void;
  onSaveRuleSpec: (ruleTemplate: RuleSpecTemplate) => void;
}) {
  const state = ruleSpecNodeState(tool);
  return (
    <article
      data-node-state={state.kind}
      className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 transition-colors hover:border-blue-200 hover:bg-blue-50/30 sm:px-4"
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h3 className="min-w-0 truncate text-sm font-medium text-slate-900">{tool.name}</h3>
            <RuleSpecNodeReadinessBadge state={state} />
            <SourceBadge source={tool.source} label={tool.sourceLabel} />
            <PlatformBadge item={tool} />
            <WrapperBadge item={tool} />
          </div>
          <p className="mt-1 truncate font-mono text-xs text-slate-500">{tool.selectedPackageSpec}</p>
          <RuleSpecNodeStatusRow state={state} />
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-slate-400 hover:bg-white hover:text-blue-600"
            onClick={onEditRuleSpec}
            title="补全 RuleSpec"
          >
            <Workflow strokeWidth={1.5} className="h-3.5 w-3.5" />
            <span className="sr-only">补全 RuleSpec</span>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-slate-400 hover:bg-white hover:text-red-600"
            onClick={onRemove}
            title="移除"
          >
            <Trash2 strokeWidth={1.5} className="h-3.5 w-3.5" />
            <span className="sr-only">移除</span>
          </Button>
        </div>
      </div>

      <RulePortPreview item={tool} compact />

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

function RuleSpecNodeStatusRow({ state }: { state: RuleSpecNodeState }) {
  return (
    <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5">
      <RuleSpecNodeStatusChip label="Action" value={state.actionLabel} warning={!state.hasAction} />
      <RuleSpecNodeStatusChip label="Ports" value={`${state.inputs} in / ${state.outputs} out`} detail={`${state.params} params`} />
      <RuleSpecNodeStatusChip label="Env" value={state.envLabel} warning={!state.hasEnv} wide />
    </div>
  );
}

function RuleSpecNodeReadinessBadge({ state }: { state: RuleSpecNodeState }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded border px-1.5 text-[11px] leading-none",
        state.kind === "ready"
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-amber-200 bg-amber-50 text-amber-700"
      )}
    >
      {state.kind === "ready" ? <CheckCircle2 strokeWidth={1.5} className="mr-1 h-3 w-3" /> : null}
      {state.label}
    </span>
  );
}

function RuleSpecNodeStatusChip({
  detail,
  label,
  warning,
  value,
  wide,
}: {
  detail?: string;
  label: string;
  warning?: boolean;
  value: string;
  wide?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 max-w-full items-center gap-1 rounded border px-1.5 text-[11px] leading-none",
        warning ? "border-amber-200 bg-amber-50 text-amber-700" : "border-slate-200 bg-slate-50 text-slate-600",
        wide && "sm:max-w-[20rem]"
      )}
      title={detail ? `${label}: ${value} / ${detail}` : `${label}: ${value}`}
    >
      <span className={cn("shrink-0 font-medium", warning ? "text-amber-600" : "text-slate-400")}>{label}</span>
      <span className="min-w-0 truncate font-mono">{value}</span>
      {detail ? <span className="shrink-0 text-slate-400">· {detail}</span> : null}
    </span>
  );
}

type RuleSpecNodeState = {
  actionLabel: string;
  envLabel: string;
  hasAction: boolean;
  hasEnv: boolean;
  inputs: number;
  kind: "ready" | "missing-action" | "missing-env";
  label: "可运行" | "待补 action" | "待补 env";
  outputs: number;
  params: number;
};

function ruleSpecNodeState(tool: AddedTool): RuleSpecNodeState {
  const template = ruleTemplateForLibraryTool(tool);
  const actionLabel = ruleSpecActionLabel(template);
  const inputs = template.inputs?.length || 0;
  const outputs = template.outputs?.length || 0;
  const params = template.params ? Object.keys(template.params).length : 0;
  const dependencies = template.environment?.conda?.dependencies || [];
  const hasEnv = dependencies.length > 0 || Boolean(tool.selectedPackageSpec || tool.packageSpec);
  if (!actionLabel) {
    return {
      actionLabel: "待补 action",
      envLabel: environmentLabel(tool, dependencies),
      hasAction: false,
      hasEnv,
      inputs,
      kind: "missing-action",
      label: "待补 action",
      outputs,
      params,
    };
  }
  if (!hasEnv) {
    return {
      actionLabel,
      envLabel: "待补 env",
      hasAction: true,
      hasEnv: false,
      inputs,
      kind: "missing-env",
      label: "待补 env",
      outputs,
      params,
    };
  }
  return {
    actionLabel,
    envLabel: environmentLabel(tool, dependencies),
    hasAction: true,
    hasEnv: true,
    inputs,
    kind: "ready",
    label: "可运行",
    outputs,
    params,
  };
}

function ruleTemplateForLibraryTool(tool: AddedTool): RuleSpecTemplate {
  const manifest = tool.ruleTemplate || {};
  const draft = tool.ruleSpecDraft?.ruleTemplate || {};
  if (ruleSpecActionLabel(manifest)) return manifest;
  if (ruleSpecActionLabel(draft)) return draft;
  return Object.keys(manifest).length > 0 ? manifest : draft;
}

function ruleSpecActionLabel(template: RuleSpecTemplate) {
  if (template.wrapper) return "wrapper";
  if (template.commandTemplate) return "command";
  if (template.script) return "script";
  if (template.module) return "module";
  return "";
}

function environmentLabel(tool: AddedTool, dependencies: string[]) {
  if (dependencies.length > 1) return `${dependencies.length} deps`;
  if (dependencies.length === 1) return dependencies[0];
  return tool.selectedPackageSpec || tool.packageSpec || "待补 env";
}
