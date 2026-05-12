"use client";

import Link from "next/link";
import { AlertCircle, CheckCircle2, Database, Loader2, Play, UploadCloud, Wrench } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import { WorkflowCurrentRunPanel } from "./workflow-current-run-panel";
import { WorkflowParamsForm } from "./workflow-params-form";
import {
  fetchRunsList,
  fetchWorkflowDatabases,
  fetchWorkflowServer,
  fetchWorkflowTools,
} from "./workflows-page-api";
import {
  outputArtifactNames,
  type JsonSchema,
  type WorkflowCatalogItem,
  type WorkflowRun,
  type WorkflowRunDetail,
  type WorkflowServer,
  type WorkflowUpload,
} from "./workflows-page-model";

export { WorkflowCatalogTable };

function prefetchWorkflowDetailData() {
  void fetchWorkflowTools();
  void fetchWorkflowDatabases();
  void fetchWorkflowServer();
  void fetchRunsList();
}

function WorkflowCatalogTable({
  items,
  selectedWorkflowId,
  onSelect,
}: {
  items: WorkflowCatalogItem[];
  selectedWorkflowId?: string;
  onSelect?: (id: string) => void;
}) {
  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-900">流程目录</h2>
        <span className="text-xs text-slate-400">{items.length}</span>
      </div>
      <div className="overflow-hidden rounded-lg border border-slate-200">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="w-[28%] px-3 py-2 font-medium">名称</th>
              <th className="w-[14%] px-3 py-2 font-medium">来源</th>
              <th className="w-[14%] px-3 py-2 font-medium">状态</th>
              <th className="w-[28%] px-3 py-2 font-medium">输出</th>
              <th className="w-[16%] px-3 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.map((item) => (
              <tr key={`${item.kind}-${item.id}`} className={selectedWorkflowId === item.id ? "bg-blue-50/60" : "bg-white"}>
                <td className="px-3 py-3">
                  <div className="truncate font-medium text-slate-800">{item.name}</div>
                  <div className="truncate text-xs text-slate-500">{item.description}</div>
                </td>
                <td className="px-3 py-3 text-xs text-slate-600">{item.source}</td>
                <td className="px-3 py-3">
                  <span className={cn("inline-flex h-5 items-center rounded border px-1.5 text-[11px]", item.runnable ? "border-emerald-200 text-emerald-700" : "border-slate-200 text-slate-500")}>
                    {item.runnable ? "runnable" : item.status}
                  </span>
                </td>
                <td className="truncate px-3 py-3 font-mono text-xs text-slate-500">{outputArtifactNames(item) || `${item.outputCount || 0} outputs`}</td>
                <td className="px-3 py-3">
                  {onSelect ? (
                    <Button
                      variant={selectedWorkflowId === item.id ? "default" : "outline"}
                      className="h-8 px-2.5 text-xs"
                      disabled={!item.runnable}
                      onClick={() => onSelect(item.id)}
                    >
                      {selectedWorkflowId === item.id ? "已选择" : "查看"}
                    </Button>
                  ) : (
                    <Button asChild variant="outline" className="h-8 px-2.5 text-xs">
                      <Link
                        href={`/workflows/detail?workflow=${encodeURIComponent(item.id)}`}
                        onFocus={prefetchWorkflowDetailData}
                        onPointerEnter={prefetchWorkflowDetailData}
                      >
                        查看
                      </Link>
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function WorkflowRunBuilder({
  availableDatabases,
  canSubmit,
  files,
  sampleLoading,
  sampleUploads,
  onFilesChange,
  onLoadSampleData,
  onSubmit,
  runnableTools,
  isGeneratedToolRun,
  selectedDatabaseIds,
  selectedToolIds,
  server,
  submitError,
  submittedRun,
  submitting,
  runDetail,
  runDetailError,
  toggleDatabase,
  toggleTool,
  selectedWorkflow,
  params,
  onParamsChange,
  dagPreview,
}: {
  availableDatabases: DatabaseItem[];
  canSubmit: boolean;
  files: File[];
  sampleLoading: boolean;
  sampleUploads: WorkflowUpload[];
  onFilesChange: (files: File[]) => void;
  onLoadSampleData: () => void;
  onSubmit: () => void;
  runnableTools: AddedTool[];
  isGeneratedToolRun: boolean;
  selectedDatabaseIds: string[];
  selectedToolIds: string[];
  server: WorkflowServer | null;
  submitError: string;
  submittedRun: WorkflowRun | null;
  submitting: boolean;
  runDetail: WorkflowRunDetail | null;
  runDetailError: string;
  toggleDatabase: (id: string) => void;
  toggleTool: (id: string) => void;
  selectedWorkflow: WorkflowCatalogItem | null;
  params: Record<string, unknown>;
  onParamsChange: (values: Record<string, unknown>) => void;
  dagPreview?: React.ReactNode;
}) {
  const currentRun = runDetail?.run || submittedRun || null;
  const ready = Boolean(server?.ready);
  const inputCount = files.length + sampleUploads.length;

  return (
    <section className="space-y-5">
      {dagPreview}

      <div className="rounded-xl border border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-950">运行配置</h2>
          <span className={cn("inline-flex h-5 items-center rounded-full border px-2 text-[11px]", selectedWorkflow?.runnable ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-500")}>
            {selectedWorkflow?.runnable ? "可运行" : selectedWorkflow?.status || "未知"}
          </span>
        </div>

        <div className="grid gap-0 sm:grid-cols-[minmax(0,1fr)_260px]">
          <div className="divide-y divide-slate-100">
            <WorkflowFilePicker
              files={files}
              sampleLoading={sampleLoading}
              sampleUploads={sampleUploads}
              selectedWorkflow={selectedWorkflow}
              onFilesChange={onFilesChange}
              onLoadSampleData={onLoadSampleData}
            />
            <WorkflowParamsForm
              schema={selectedWorkflow?.paramsSchema as JsonSchema | undefined}
              values={params}
              onChange={onParamsChange}
            />
          </div>

          <div className="border-t border-slate-100 p-5 sm:border-l sm:border-t-0">
            <div className="space-y-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">远程服务器</div>
                <div className="mt-1 truncate text-sm font-medium text-slate-800">
                  {server?.label || server?.serverId || "未连接"}
                </div>
                <div className="mt-0.5 text-xs text-slate-500">
                  {ready ? (
                    <span className="inline-flex items-center gap-1 text-emerald-600">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                      ready
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-slate-400">
                      <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
                      not ready
                    </span>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 border-t border-slate-100 pt-4">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">输入</div>
                  <div className="mt-1 text-sm font-medium text-slate-800">{inputCount} 个</div>
                </div>
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">参数</div>
                  <div className="mt-1 text-sm font-medium text-slate-800">{Object.keys(params).length} 项</div>
                </div>
              </div>

              {submitError ? (
                <Alert variant="destructive" className="py-2 text-xs">
                  <AlertCircle strokeWidth={1.5} className="h-3.5 w-3.5" />
                  <AlertDescription>{submitError}</AlertDescription>
                </Alert>
              ) : null}

              {submittedRun ? (
                <Alert className="border-emerald-200 bg-emerald-50 py-2 text-xs text-emerald-800">
                  <CheckCircle2 strokeWidth={1.5} className="h-3.5 w-3.5" />
                  <AlertDescription>已提交 {submittedRun.runId}</AlertDescription>
                </Alert>
              ) : null}

              <Button
                className="h-10 w-full bg-slate-950 text-white hover:bg-slate-800"
                disabled={!canSubmit}
                onClick={onSubmit}
              >
                {submitting ? (
                  <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play strokeWidth={1.5} className="mr-2 h-4 w-4" />
                )}
                提交流程
              </Button>
            </div>
          </div>
        </div>

          {isGeneratedToolRun ? (
            <div className="space-y-5 border-t border-slate-100 px-5 py-5">
              <SelectionGroup
                emptyText="还没有可运行工具"
                icon={<Wrench strokeWidth={1.5} className="h-4 w-4" />}
                items={runnableTools.map((tool) => ({
                  id: tool.id,
                  title: tool.name,
                  detail: tool.packageSpec,
                  checked: selectedToolIds.includes(tool.id),
                }))}
                title="工具步骤"
                onToggle={toggleTool}
              />
              <SelectionGroup
                emptyText="还没有可用数据库"
                icon={<Database strokeWidth={1.5} className="h-4 w-4" />}
                items={availableDatabases.map((database) => ({
                  id: database.id,
                  title: database.name,
                  detail: database.metadata?.templateLabel || database.type,
                  checked: selectedDatabaseIds.includes(database.id),
                }))}
                title="数据库绑定"
                onToggle={toggleDatabase}
              />
            </div>
          ) : null}
      </div>

      {currentRun && <WorkflowCurrentRunPanel run={currentRun} detail={runDetail} />}
    </section>
  );
}

function WorkflowFilePicker({
  files,
  sampleLoading,
  sampleUploads,
  selectedWorkflow,
  onFilesChange,
  onLoadSampleData,
}: {
  files: File[];
  sampleLoading: boolean;
  sampleUploads: WorkflowUpload[];
  selectedWorkflow: WorkflowCatalogItem | null;
  onFilesChange: (files: File[]) => void;
  onLoadSampleData: () => void;
}) {
  const exampleDataset = (
    selectedWorkflow?.uiSchema?.inputs as { exampleDataset?: { label?: string; description?: string } } | undefined
  )?.exampleDataset;
  return (
    <div className="grid gap-4 px-5 py-5 md:grid-cols-[160px_minmax(0,1fr)]">
      <div>
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-950 text-xs text-white">1</span>
          输入数据
        </div>
      </div>
      <div className="space-y-3">
        {exampleDataset ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-100 bg-blue-50/60 px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-xs font-medium text-blue-800">{exampleDataset.label || "使用官方示例数据"}</div>
              <div className="truncate text-[11px] text-blue-600">{exampleDataset.description || "下载并上传示例输入"}</div>
            </div>
            <Button
              type="button"
              variant="outline"
              className="h-8 border-blue-200 bg-white px-2.5 text-xs text-blue-700 hover:bg-blue-50"
              disabled={sampleLoading}
              onClick={onLoadSampleData}
            >
              {sampleLoading ? (
                <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <UploadCloud strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
              )}
              准备数据
            </Button>
          </div>
        ) : null}
        <Label htmlFor="workflow-files" className="sr-only">输入文件</Label>
        <Input
          id="workflow-files"
          type="file"
          multiple
          onChange={(event) => onFilesChange(Array.from(event.target.files || []))}
          className="cursor-pointer text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-slate-700 hover:file:bg-slate-200"
        />
        {files.length > 0 ? (
          <div className="grid gap-1.5">
            {files.map((file) => (
              <div key={`${file.name}-${file.size}`} className="truncate rounded-md bg-slate-50 px-3 py-2 font-mono text-xs text-slate-600">
                {file.name}
              </div>
            ))}
          </div>
        ) : null}
        {sampleUploads.length > 0 ? (
          <div className="grid gap-1.5">
            {sampleUploads.map((upload) => (
              <div key={upload.uploadId || `${upload.filename}-${upload.sizeBytes}`} className="flex items-center justify-between gap-3 rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                <span className="min-w-0 truncate font-mono">{upload.filename}</span>
                <span className="shrink-0 text-[11px] text-emerald-600">{upload.role || "input"}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function SelectionGroup({
  emptyText,
  icon,
  items,
  onToggle,
  title,
}: {
  emptyText: string;
  icon: React.ReactNode;
  items: Array<{ id: string; title: string; detail: string; checked: boolean }>;
  onToggle: (id: string) => void;
  title: string;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-900">
        {icon}
        {title}
      </div>
      {items.length === 0 ? (
        <div className="rounded-md border border-dashed border-slate-200 py-3 text-center text-sm text-slate-400">
          {emptyText}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-x-12 gap-y-2 md:grid-cols-2">
          {items.map((item) => (
            <label
              key={item.id}
              className="flex cursor-pointer items-center rounded-lg border border-transparent bg-white px-3 py-3 hover:border-slate-200 hover:bg-slate-50"
            >
              <Checkbox checked={item.checked} onCheckedChange={() => onToggle(item.id)} />
              <span className="ml-3 min-w-0">
                <span className="block truncate text-sm font-medium text-slate-800">{item.title}</span>
                <span className="block truncate font-mono text-xs text-slate-500">{item.detail}</span>
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
