"use client";

import { ArrowLeft, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { DatabaseValidationDetailsDialog } from "./database-validation-details-dialog";
import { DatabasesAddPanel } from "./databases-add-panel";
import { DatabaseItemList } from "./databases-item-list";
import { useDatabasesPageState } from "./use-databases-page-state";
import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";
import { templateText } from "./database-page-model";
import { databaseToolPath } from "./database-path-utils";

export function DatabasesPage() {
  const state = useDatabasesPageState();

  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex h-9 items-center justify-end">
          {state.adding ? (
            <Button type="button" variant="outline" className="h-9 bg-white px-3 text-slate-600" onClick={state.cancelAdding}>
              <ArrowLeft strokeWidth={1.5} className="mr-2 h-4 w-4" />
              返回数据库
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              className="h-9 bg-white px-3 text-slate-600"
              disabled={state.templateLoading || state.templates.length === 0}
              onClick={state.startAdding}
            >
              <Plus strokeWidth={1.5} className="mr-2 h-4 w-4" />
              添加数据库
            </Button>
          )}
        </div>

        <div className="text-center">
          <h1 className="text-2xl font-semibold">数据库</h1>
        </div>

        {state.error ? <div className="py-1 text-sm text-red-600">{state.error}</div> : null}
        {state.templateError ? <div className="py-1 text-sm text-red-600">{state.templateError}</div> : null}

        {state.adding ? <DatabasesAddPanel state={state} /> : null}

        <Dialog open={Boolean(state.editingItem)} onOpenChange={(open) => (!open ? state.closeEditDialog() : null)}>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>编辑数据库</DialogTitle>
              <DialogDescription>修改用于识别和查找的展示信息。数据库路径和模板保持不变。</DialogDescription>
            </DialogHeader>
            <div className="mt-5 flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="database-edit-name">名称</Label>
                <Input
                  id="database-edit-name"
                  value={state.editValues.name}
                  onChange={(event) => state.updateEditValue("name", event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="database-edit-version">版本</Label>
                <Input
                  id="database-edit-version"
                  value={state.editValues.version}
                  onChange={(event) => state.updateEditValue("version", event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="database-edit-description">描述</Label>
                <Input
                  id="database-edit-description"
                  value={state.editValues.description}
                  onChange={(event) => state.updateEditValue("description", event.target.value)}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" className="h-9 px-3 text-slate-500" onClick={state.closeEditDialog}>
                  取消
                </Button>
                <Button
                  type="button"
                  className="h-9 px-3"
                  onClick={state.updateDatabase}
                  disabled={Boolean(state.updatingId) || !state.editValues.name.trim()}
                >
                  {state.updatingId ? "保存中" : "保存"}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
        <DatabaseValidationDetailsDialog
          open={Boolean(state.detailsItem)}
          item={state.detailsItem}
          toolPath={state.detailsItem ? databaseToolPath(state.detailsItem) : ""}
          onOpenChange={(open) => (!open ? state.setDetailsItem(null) : null)}
        />
        <Dialog open={Boolean(state.candidateDetail)} onOpenChange={(open) => (!open ? state.setCandidateDetail(null) : null)}>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>请选择数据库入口</DialogTitle>
              <DialogDescription>
                {state.candidateDetail?.message || "检测到多个可用数据库入口，请选择一个后继续校验。"}
              </DialogDescription>
            </DialogHeader>
            <div className="max-h-96 space-y-2 overflow-y-auto">
              {(state.candidateDetail?.candidates || []).map((candidate) => (
                <button
                  key={candidate.entryPath}
                  type="button"
                  className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-left hover:border-blue-300 hover:bg-blue-50/40"
                  onClick={() => void state.submitDatabase(candidate.entryPath)}
                >
                  <div className="text-sm font-medium text-slate-800">{candidate.label}</div>
                  <div className="mt-1 truncate font-mono text-xs text-slate-600">{candidate.entryPath}</div>
                  {candidate.evidence && candidate.evidence.length > 0 ? (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {candidate.evidence.slice(0, 8).map((item, index) => (
                        <span key={`${item}-${index}`} className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-500">
                          {item}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </button>
              ))}
            </div>
          </DialogContent>
        </Dialog>

        <DatabaseItemList
          items={state.items}
          checkingId={state.checkingId}
          getDatabaseToolPath={databaseToolPath}
          templateText={(item) => templateText(item, state.templateById)}
          openEditDatabase={state.openEditDatabase}
          copyDatabasePath={state.copyDatabasePath}
          setDetailsItem={state.setDetailsItem}
          onCheck={state.checkDatabase}
          onRemove={state.removeDatabase}
        />

        {!state.loading && state.items.length === 0 ? <div className="py-8 text-center text-sm text-slate-500">暂无数据库</div> : null}
      </div>
    </div>
  );
}
