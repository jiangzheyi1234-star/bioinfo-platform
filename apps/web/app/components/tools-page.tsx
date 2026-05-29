"use client";

import { ArrowLeft, Plus, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { sourceFilters } from "./tools-page-model";
import { ToolsLibrarySection } from "./tools-page-library-section";
import { ToolPreviewPanel, ToolSearchResults } from "./tools-page-ui";
import { useToolsPageState } from "./use-tools-page-state";
import { WorkflowPageHeader } from "./workflow-page-header";
import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";

export function ToolsPage() {
  const state = useToolsPageState();

  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-4 py-6 text-slate-800 sm:px-6 sm:py-10 lg:px-8">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-5xl space-y-6">
        <WorkflowPageHeader
          title="工具"
          actions={
            state.view === "library" ? (
              <Button variant="outline" className="h-9 bg-white px-3 text-slate-600" onClick={() => state.setView("search")}>
                <Plus strokeWidth={1.5} className="mr-2 h-4 w-4" />
                添加工具
              </Button>
            ) : (
              <Button variant="outline" className="h-9 bg-white px-3 text-slate-600" onClick={() => state.setView("library")}>
                <ArrowLeft strokeWidth={1.5} className="mr-2 h-4 w-4" />
                返回工具库
              </Button>
            )
          }
        />

        {state.view === "library" ? (
          <ToolsLibrarySection
            addedTools={state.addedTools}
            editingRuleSpecToolId={state.editingRuleSpecToolId}
            ruleSpecEditError={state.ruleSpecEditError}
            ruleSpecSavingId={state.ruleSpecSavingId}
            toolsError={state.toolsError}
            toolsLoading={state.toolsLoading}
            onCancelRuleSpecEdit={() => state.setEditingRuleSpecToolId("")}
            onEditRuleSpec={state.editToolRuleTemplate}
            onRefresh={() => void state.loadAddedTools()}
            onRemove={state.removeAddedTool}
            onSaveRuleSpec={state.saveToolRuleTemplate}
          />
        ) : (
          <>
            <div>
              <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
                <div className="relative">
                  <Search
                    strokeWidth={1.5}
                    className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                  />
                  <Input
                    type="text"
                    value={state.query}
                    onChange={(event) => state.updateQuery(event.target.value)}
                    placeholder="在线搜索 Bioconda / conda-forge 工具"
                    className="h-10 w-full rounded-md border-slate-200 bg-white pl-9"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {sourceFilters.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => state.setSource(item.id)}
                      className={cn(
                        "h-8 rounded-md px-3 text-xs transition",
                        state.source === item.id
                          ? "bg-slate-900 text-white"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-x-8 gap-y-6 min-[820px]:grid-cols-[minmax(0,1fr)_340px]">
              <ToolSearchResults
                error={state.error}
                filtered={state.filtered}
                loading={state.loading}
                query={state.query}
                searchComplete={state.searchComplete}
                searchHasMore={state.searchHasMore}
                searchPage={state.searchPage}
                searchTotal={state.searchTotal}
                selectedId={state.selectedId}
                onPageChange={state.setSearchPage}
                onSelect={state.setSelectedId}
              />

              <ToolPreviewPanel
                canAddSelected={state.canAddSelected}
                selected={state.selected}
                selectedAlreadyAdded={state.selectedAlreadyAdded}
                selectedPackageSpec={state.selectedPackageSpec}
                selectedVersion={state.selectedVersion}
                onAdd={state.addSelectedTool}
                onOpenSourceUrl={(url) => void state.openToolSourceUrl(url)}
                onVersionChange={state.updateSelectedVersion}
              />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
