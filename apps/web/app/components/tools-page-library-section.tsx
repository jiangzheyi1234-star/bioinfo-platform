"use client";

import { Loader2, RefreshCw, Trash2, Workflow } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AddedTool, RuleSpecTemplate } from "./tools-page-model";
import { PlatformBadge, RuleNodeSummary, RulePortPreview, SourceBadge, WrapperBadge } from "./tools-page-ui";
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
        <h2 className="text-sm font-medium text-slate-900">工具库</h2>
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
              <div
                key={tool.id}
                className="rounded-lg border border-transparent bg-white px-3 py-3 transition-colors hover:border-slate-200 hover:bg-slate-50"
              >
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <h3 className="min-w-0 truncate text-sm font-medium text-slate-800">{tool.name}</h3>
                      <SourceBadge source={tool.source} label={tool.sourceLabel} />
                      <PlatformBadge item={tool} />
                      <WrapperBadge item={tool} />
                    </div>
                    <p className="mt-1 truncate font-mono text-xs text-slate-500">{tool.selectedPackageSpec}</p>
                    <RuleNodeSummary item={tool} />
                    <RulePortPreview item={tool} compact />
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-slate-400 hover:bg-white hover:text-blue-600"
                      onClick={() => onEditRuleSpec(tool.id)}
                      title="补全 RuleSpec"
                    >
                      <Workflow strokeWidth={1.5} className="h-3.5 w-3.5" />
                      <span className="sr-only">补全 RuleSpec</span>
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-slate-400 hover:bg-white hover:text-red-600"
                      onClick={() => onRemove(tool.id)}
                      title="移除"
                    >
                      <Trash2 strokeWidth={1.5} className="h-3.5 w-3.5" />
                      <span className="sr-only">移除</span>
                    </Button>
                  </div>
                </div>
                {editing ? (
                  <ToolRuleSpecEditor
                    error={ruleSpecEditError}
                    saving={ruleSpecSavingId === tool.id}
                    tool={tool}
                    onCancel={onCancelRuleSpecEdit}
                    onSave={(ruleTemplate) => onSaveRuleSpec(tool.id, ruleTemplate)}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
