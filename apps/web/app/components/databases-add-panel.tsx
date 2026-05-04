"use client";

import { ChevronUp, Database, FolderOpen, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  browserFileAction,
  compositeFieldEntries,
  compositeFieldLabel,
} from "./database-path-utils";
import {
  pathLabel,
  runtimeHint,
  stableComplexityCopy,
  selectionCopy,
  templateCheckItemList,
} from "./database-page-model";
import {
  templateIcon,
} from "./database-page-ui";

import type { DatabasesPageState } from "./use-databases-page-state";

type DatabasesAddPanelProps = {
  state: DatabasesPageState;
};

export function DatabasesAddPanel({ state }: DatabasesAddPanelProps) {
  const {
    browserListRef,
    browserLoading,
    browserLoadingMore,
    browserParentPath,
    browserPath,
    browserItems,
    browserError,
    browserOpen,
    browserTruncated,
    browserTotal,
    templateGroups,
    templateLoading,
    templates,
    selectedTemplate,
    compositeFields,
    activeCompositeField,
    form,
    selectionMode,
    canSubmitDatabase,
    saving,
    handleBrowserScroll,
    loadRemotePath,
    selectTemplate,
    editManualPath,
    updateCompositeField,
    updateForm,
    addDatabase,
    selectBrowserPath,
    selectBrowserPathForCompositeField,
  } = state;

  return (
    <div className="grid grid-cols-1 gap-6 border-y border-slate-100 py-4 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <div className="space-y-3">
        <Label>数据库类型</Label>
        <div className="grid max-h-[calc(100vh-13rem)] grid-cols-1 gap-2 overflow-y-auto pr-2 sm:grid-cols-2 md:grid-cols-1">
          {templateLoading ? <div className="px-3 py-3 text-xs text-slate-400">正在读取数据库模板</div> : null}
          {!templateLoading && templates.length === 0 ? <div className="px-3 py-3 text-xs text-red-600">数据库模板不可用</div> : null}
          {templateGroups.map((group) => (
            <div key={group.label} className="space-y-1.5">
              <div className="px-1 text-[11px] font-medium text-slate-500">{group.label}</div>
              {group.templates.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  className={cn(
                    "flex min-h-16 w-full items-start rounded-md border bg-white px-3 py-2 text-left transition-colors hover:border-blue-300 hover:bg-blue-50/40",
                    form.templateId === template.id ? "border-blue-400 bg-blue-50" : "border-slate-200"
                  )}
                  onClick={() => selectTemplate(template.id)}
                >
                  <span className="mt-0.5 text-blue-600">{templateIcon(template)}</span>
                  <span className="ml-2 min-w-0">
                    <span className="block truncate text-sm font-medium text-slate-800">{template.name}</span>
                    <span className="mt-0.5 block truncate text-xs text-slate-500">{template.description}</span>
                  </span>
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-4 md:sticky md:top-16">
        {selectedTemplate ? (
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-4 text-sm text-slate-700 shadow-sm">
              <div className="flex items-center gap-2.5 text-xl font-medium text-slate-950">
              {templateIcon(selectedTemplate, "h-5 w-5 text-blue-600")}
              <span>{selectedTemplate.name}</span>
            </div>
            <div className="mt-4 space-y-4">
              <div>
                <div className="text-sm font-medium text-slate-500">
                  <span>选择目标</span>
                </div>
                <p className="mt-1 text-sm leading-6 text-slate-950">
                  {stableComplexityCopy(selectedTemplate)}。{selectionCopy(selectedTemplate)}。{runtimeHint(selectedTemplate)}
                </p>
              </div>
              <div>
                <div className="text-sm font-medium text-slate-500">
                  <span>自动校验</span>
                </div>
                <p className="mt-1 text-sm leading-6 text-slate-950">
                  工具验证：{selectedTemplate.toolProbe?.packageSpec || "自定义规则"}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {templateCheckItemList(selectedTemplate).map((item, index) => (
                    <span
                      key={`${item}-${index}`}
                      className="rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 font-mono text-xs leading-5 text-slate-950 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)]"
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-slate-500">
                  <span>路径示例</span>
                </div>
                <div className="mt-1.5 truncate rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 font-mono text-sm leading-5 text-slate-950 shadow-[inset_0_1px_1px_rgba(15,23,42,0.04)]">
                  {selectedTemplate.pathHint}
                </div>
              </div>
            </div>
          </div>
        ) : null}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-1.5 md:col-span-2">
            <Label htmlFor="database-name">数据库名称</Label>
            <Input
              id="database-name"
              placeholder={selectedTemplate ? `${selectedTemplate.name} Standard 2024` : "Kraken2 Standard 2024"}
              value={form.name}
              onChange={(event) => updateForm("name", event.target.value)}
            />
            <p className="text-[11px] text-slate-400">运行流程时会显示这个名称。留空则按数据库类型和路径自动命名。</p>
          </div>
          {selectedTemplate?.selectorKind === "composite" ? (
            <div className="space-y-3 md:col-span-2">
              <Label>{pathLabel(selectedTemplate)}</Label>
              {compositeFieldEntries(selectedTemplate).map(([key, field]) => (
                <div key={key} className="rounded-md border border-slate-200 bg-white px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <Label htmlFor={`database-field-${key}`} className="text-xs">
                      {compositeFieldLabel(key, field)}
                        {field.required === false ? "" : " *"}
                      </Label>
                      {field.pathHint ? <p className="mt-0.5 truncate font-mono text-[11px] text-slate-400">{field.pathHint}</p> : null}
                    </div>
                    <Button
                      type="button"
                      variant={activeCompositeField === key ? "default" : "outline"}
                      className="h-8 px-2 text-xs"
                      onClick={() => {
                        state.setSelectionMode("browser");
                        state.setActiveCompositeField(key);
                        loadRemotePath(compositeFields[key]?.trim() || field.pathHint || "~");
                      }}
                    >
                      <FolderOpen strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                      浏览
                    </Button>
                  </div>
                  <Input
                    id={`database-field-${key}`}
                    className="mt-2"
                    placeholder={field.pathHint || ""}
                    value={compositeFields[key] || ""}
                    onFocus={() => state.setActiveCompositeField(key)}
                    onChange={(event) => {
                      state.setSelectionMode(event.target.value.trim() ? "manual" : "none");
                      updateCompositeField(key, event.target.value);
                    }}
                  />
                  {compositeFields[key]?.trim() ? (
                    <p className="mt-1 truncate font-mono text-[11px] text-slate-400">
                      {selectionMode === "browser" && activeCompositeField === key ? "已选择：" : "手动输入："}
                      {compositeFields[key]}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-1.5 md:col-span-2">
              <Label htmlFor="database-path">{pathLabel(selectedTemplate)}</Label>
              <Input
                id="database-path"
                placeholder={selectedTemplate?.pathHint || ""}
                value={form.path}
                onChange={(event) => editManualPath(event.target.value)}
              />
              {form.path.trim() ? (
                <p className="truncate font-mono text-[11px] text-slate-400">
                  {selectionMode === "browser" ? "已选择：" : "手动输入："}
                  {form.path}
                </p>
              ) : null}
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="outline"
                  className="h-8 px-2 text-xs text-slate-600"
                  onClick={() => void loadRemotePath(form.path.trim() || "~")}
                >
                  <FolderOpen strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />
                  浏览远程路径
                </Button>
              </div>
            </div>
          )}
        </div>

        {browserOpen ? (
          <div className="rounded-md border border-slate-200 bg-white">
            <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate font-mono text-xs text-slate-700">{browserPath}</div>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs text-slate-600"
                disabled={browserLoading || !browserParentPath || browserParentPath === browserPath}
                onClick={() => void loadRemotePath(browserParentPath)}
              >
                <ChevronUp strokeWidth={1.5} className="mr-1 h-3.5 w-3.5" />
                上级
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs text-slate-600"
                disabled={browserLoading}
                onClick={() => void loadRemotePath(browserPath)}
              >
                <RefreshCw strokeWidth={1.5} className={cn("mr-1 h-3.5 w-3.5", browserLoading && "animate-spin")} />
                刷新
              </Button>
              {selectedTemplate?.selectorKind === "composite" && activeCompositeField ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => selectBrowserPathForCompositeField(activeCompositeField, browserPath)}
                >
                  选择当前目录
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={() => selectBrowserPath(browserPath)}
                >
                  选择当前目录
                </Button>
              )}
            </div>
            {browserError ? <div className="px-3 py-2 text-xs text-red-600">{browserError}</div> : null}
            {browserLoading ? (
              <div className="flex items-center px-3 py-3 text-xs text-slate-400">
                <RefreshCw strokeWidth={1.5} className="mr-2 h-3.5 w-3.5 animate-spin" />
                正在读取远程目录
              </div>
            ) : browserItems.length === 0 && !browserError ? (
              <div className="px-3 py-3 text-xs text-slate-400">当前目录没有可选路径</div>
            ) : (
              <div ref={browserListRef} className="max-h-80 overflow-y-auto p-1" onScroll={handleBrowserScroll}>
                {browserItems.map((item) => {
                  const fileAction = browserFileAction(selectedTemplate, item);
                  return (
                    <div key={item.path} className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-slate-50">
                      {item.isDirectory ? (
                        <FolderOpen strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-blue-600" />
                      ) : (
                        <Database strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-500" />
                      )}
                      <button
                        type="button"
                        className={cn("min-w-0 flex-1 truncate text-left font-mono", item.isDirectory ? "text-slate-700" : "cursor-default text-slate-500")}
                        onClick={() => (item.isDirectory ? void loadRemotePath(item.path) : undefined)}
                      >
                        {item.name}
                      </button>
                      {item.isDirectory ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[11px] text-slate-500"
                          onClick={() => void loadRemotePath(item.path)}
                        >
                          进入
                        </Button>
                      ) : fileAction ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[11px] text-slate-500 disabled:text-slate-400"
                          title={fileAction.hint}
                          disabled={fileAction.disabled}
                          onClick={() => selectBrowserPath(item.path)}
                        >
                          {fileAction.label}
                        </Button>
                      ) : selectedTemplate?.selectorKind === "composite" && activeCompositeField ? (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2 text-[11px] text-slate-500"
                          onClick={() => selectBrowserPathForCompositeField(activeCompositeField, item.path)}
                        >
                          选择此文件
                        </Button>
                      ) : null}
                    </div>
                  );
                })}
                {browserTruncated ? (
                  <div className="border-t border-slate-100 px-2 py-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      disabled={browserLoadingMore}
                      onClick={() => void loadRemotePath(browserPath, { append: true })}
                    >
                      {browserLoadingMore ? <RefreshCw strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : null}
                      加载更多
                    </Button>
                    <span className="ml-2 text-[11px] text-slate-400">
                      已显示 {browserItems.length}
                      {browserTotal !== null ? ` / ${browserTotal}` : ""}
                      项
                    </span>
                  </div>
                ) : null}
              </div>
            )}
            {browserTruncated ? (
              <div className="border-t border-slate-100 px-3 py-1.5 text-[11px] text-amber-700">
                当前目录内容较多，已分批加载。可以继续加载更多，或进入更具体的目录。
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="flex justify-end gap-2">
          <p className="mr-auto max-w-md text-xs leading-5 text-slate-500">
            加入前会解析入口路径并运行模板检查；验证失败不会保存为可用数据库。
          </p>
              <Button
            type="button"
            variant="ghost"
            className="h-9 px-3 text-slate-500"
            onClick={() => {
              state.cancelAdding();
              state.setCandidateDetail(null);
            }}
          >
            取消
          </Button>
          <Button type="button" className="h-9 px-3" onClick={addDatabase} disabled={saving || !canSubmitDatabase}>
            {saving ? "校验中" : "校验并保存"}
          </Button>
        </div>
      </div>
    </div>
  );
}
