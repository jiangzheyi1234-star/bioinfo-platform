"use client";

import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { AlertCircle, ArrowLeft, Check, ChevronLeft, ChevronRight, ExternalLink, Loader2, PackagePlus, Plus, RefreshCw, Search, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { cn } from "@/lib/utils";

import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";

type ToolSearchItem = {
  id: string;
  name: string;
  summary: string;
  source: "bioconda" | "conda-forge" | string;
  sourceLabel: string;
  packageSpec: string;
  version?: string;
  latestVersion?: string;
  versions?: string[];
  sourceUrl?: string;
  platforms?: string[];
  targetPlatform?: string;
  targetPlatformSupported?: boolean;
  testCommand?: string;
};

type ToolSearchResponse = {
  data: {
    items: ToolSearchItem[];
    query: string;
    online: boolean;
    cached?: boolean;
    total?: number;
    page?: number;
    pageSize?: number;
    hasMore?: boolean;
    complete?: boolean;
  };
};

type AddedTool = ToolSearchItem & {
  selectedVersion: string;
  selectedPackageSpec: string;
  status?: string;
  message?: string;
  createdAt?: string;
  updatedAt?: string;
  lastCheckedAt?: string | null;
};

type ToolsResponse = {
  data: {
    items: AddedTool[];
  };
};

const sourceFilters = [
  { id: "all", label: "全部" },
  { id: "bioconda", label: "Bioconda" },
  { id: "conda-forge", label: "conda-forge" },
];

const TOOL_SEARCH_PAGE_SIZE = 20;

function toolErrorMessage(err: unknown, fallback: string) {
  const message = err instanceof Error ? err.message : String(err || "");
  if (/timed out|timeout|超时/i.test(message)) {
    return "远程服务响应超时，请先确认 SSH 底部状态为已连接，并刷新远程服务后再试。";
  }
  if (/not ready|not prepared|not connected|unreachable|Remote end closed/i.test(message)) {
    return "远程服务暂不可用，请先连接 SSH 并启动远程服务。";
  }
  return message || fallback;
}

function searchErrorMessage(err: unknown) {
  const message = err instanceof Error ? err.message : String(err || "");
  if (/timed out|timeout|超时/i.test(message)) {
    return "在线搜索超时，请稍后重试。";
  }
  if (/name resolution|Temporary failure|NetworkError|Failed to fetch|unreachable/i.test(message)) {
    return "在线搜索暂不可用，请检查本机网络后重试。";
  }
  return message || "在线搜索失败";
}

function SourceBadge({ source, label }: { source: string; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded border px-1.5 text-[11px] leading-none",
        source === "bioconda" && "border-emerald-200 bg-emerald-50 text-emerald-700",
        source === "conda-forge" && "border-sky-200 bg-sky-50 text-sky-700",
        source !== "bioconda" && source !== "conda-forge" && "border-slate-200 bg-slate-50 text-slate-600"
      )}
    >
      {label}
    </span>
  );
}

function PlatformBadge({ item }: { item: ToolSearchItem }) {
  const target = item.targetPlatform || "linux-64";
  const supported = item.targetPlatformSupported === true;
  const unsupported = item.targetPlatformSupported === false;
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded border px-1.5 text-[11px] leading-none",
        supported && "border-blue-200 bg-blue-50 text-blue-700",
        unsupported && "border-amber-200 bg-amber-50 text-amber-700",
        !supported && !unsupported && "border-slate-200 bg-slate-50 text-slate-500"
      )}
    >
      {supported ? `${target} 可用` : unsupported ? `${target} 不支持` : "平台未知"}
    </span>
  );
}

function dependencyKey(packageSpec: string) {
  return String(packageSpec || "").trim().toLowerCase();
}

function uniqueDependencies(items: AddedTool[]) {
  const seen = new Set<string>();
  const unique: AddedTool[] = [];
  for (const item of items) {
    const key = dependencyKey(item.selectedPackageSpec || item.packageSpec);
    if (key && seen.has(key)) {
      continue;
    }
    if (key) {
      seen.add(key);
    }
    unique.push(item);
  }
  return unique;
}

async function openSourceUrl(url: string) {
  try {
    await invoke("open_external_url", { url });
  } catch {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

function ResultRow({
  item,
  selected,
  onSelect,
}: {
  item: ToolSearchItem;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group flex w-full items-center rounded-lg border px-4 py-3 text-left transition",
        selected
          ? "border-blue-200 bg-blue-50/60"
          : "border-transparent bg-white hover:border-slate-200 hover:bg-slate-50"
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="truncate text-sm font-medium text-slate-900">{item.name}</h3>
          <SourceBadge source={item.source} label={item.sourceLabel} />
          <PlatformBadge item={item} />
        </div>
        <p className="mt-1 truncate text-xs text-slate-500">{item.summary || "Conda package"}</p>
      </div>
      <div className="ml-4 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 group-hover:text-slate-700">
        {selected ? (
          <Check strokeWidth={1.5} className="h-4 w-4 text-blue-600" />
        ) : (
          <PackagePlus strokeWidth={1.5} className="h-4 w-4" />
        )}
      </div>
    </button>
  );
}

export function ToolsPage() {
  const [view, setView] = useState<"library" | "search">("library");
  const [addedTools, setAddedTools] = useState<AddedTool[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState("");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [items, setItems] = useState<ToolSearchItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [versionOverrides, setVersionOverrides] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searchPage, setSearchPage] = useState(1);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchHasMore, setSearchHasMore] = useState(false);
  const [searchComplete, setSearchComplete] = useState(true);

  async function loadAddedTools() {
    setToolsLoading(true);
    setToolsError("");
    try {
      const response = await requestLocalApiJson<ToolsResponse>("GET", "/api/v1/tools", { cache: "no-store" });
      const nextItems = uniqueDependencies(
        (response.data.items || []).map((item) => ({
          ...item,
          selectedVersion: item.version || "",
          selectedPackageSpec: item.packageSpec,
        }))
      );
      setAddedTools(nextItems);
    } catch (err) {
      setAddedTools([]);
      setToolsError(toolErrorMessage(err, "读取工具列表失败"));
    } finally {
      setToolsLoading(false);
    }
  }

  useEffect(() => {
    void loadAddedTools();
  }, []);

  useEffect(() => {
    const normalized = query.trim();
    if (normalized.length < 2) {
      setItems([]);
      setSelectedId("");
      setError("");
      setLoading(false);
      setSearchTotal(0);
      setSearchHasMore(false);
      setSearchComplete(true);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const response = await requestLocalApiJson<ToolSearchResponse>(
          "GET",
          `/api/v1/tool-capabilities/search?q=${encodeURIComponent(normalized)}&page=${searchPage}&pageSize=${TOOL_SEARCH_PAGE_SIZE}`,
          { cache: "no-store", signal: controller.signal }
        );
        const nextItems = response.data.items || [];
        setItems(nextItems);
        setSearchTotal(response.data.total ?? nextItems.length);
        setSearchHasMore(Boolean(response.data.hasMore));
        setSearchComplete(response.data.complete !== false);
        setSelectedId((current) => (nextItems.some((item) => item.id === current) ? current : nextItems[0]?.id || ""));
      } catch (err) {
        if (controller.signal.aborted) {
          return;
        }
        setItems([]);
        setSelectedId("");
        setSearchTotal(0);
        setSearchHasMore(false);
        setSearchComplete(true);
        setError(searchErrorMessage(err));
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }, 350);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, searchPage]);

  const filtered = useMemo(() => {
    if (source === "all") {
      return items;
    }
    return items.filter((item) => item.source === source);
  }, [items, source]);

  const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0];
  const selectedVersion = selected ? (versionOverrides[selected.id] ?? selected.latestVersion ?? "") : "";
  const selectedPackageSpec = selected
    ? selectedVersion.trim()
      ? `${selected.source}::${selected.name}=${selectedVersion.trim()}`
      : `${selected.source}::${selected.name}`
    : "";
  const selectedAlreadyAdded = Boolean(
    selectedPackageSpec && addedTools.some((tool) => dependencyKey(tool.selectedPackageSpec || tool.packageSpec) === dependencyKey(selectedPackageSpec))
  );
  const canAddSelected = selected?.targetPlatformSupported === true && !selectedAlreadyAdded;

  function addSelectedTool() {
    if (!selected || !canAddSelected) {
      if (selectedAlreadyAdded) {
        setToolsError("该依赖版本已经加入项目。");
        setView("library");
      }
      return;
    }
    const nextTool: AddedTool = {
      ...selected,
      selectedVersion,
      selectedPackageSpec,
      packageSpec: selectedPackageSpec,
    };
    void (async () => {
      setToolsError("");
      try {
        await requestLocalApiJson("POST", "/api/v1/tools", {
          body: {
            id: nextTool.id,
            name: nextTool.name,
            source: nextTool.source,
            sourceLabel: nextTool.sourceLabel,
            version: nextTool.selectedVersion,
            packageSpec: nextTool.selectedPackageSpec,
            summary: nextTool.summary,
            targetPlatform: nextTool.targetPlatform,
            targetPlatformSupported: nextTool.targetPlatformSupported,
            platforms: nextTool.platforms || [],
            sourceUrl: nextTool.sourceUrl,
            testCommand: nextTool.testCommand || "",
          },
        });
        await loadAddedTools();
        setView("library");
      } catch (err) {
        setToolsError(toolErrorMessage(err, "加入依赖失败"));
      }
    })();
  }

  function removeAddedTool(id: string) {
    void (async () => {
      setToolsError("");
      try {
        await requestLocalApiJson("DELETE", `/api/v1/tools/${encodeURIComponent(id)}`);
        await loadAddedTools();
      } catch (err) {
        setToolsError(toolErrorMessage(err, "移除工具失败"));
      }
    })();
  }

  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex h-9 items-center justify-end">
          {view === "library" ? (
            <Button variant="outline" className="h-9 bg-white px-3 text-slate-600" onClick={() => setView("search")}>
              <Plus strokeWidth={1.5} className="mr-2 h-4 w-4" />
              添加依赖
            </Button>
          ) : (
            <Button variant="outline" className="h-9 bg-white px-3 text-slate-600" onClick={() => setView("library")}>
              <ArrowLeft strokeWidth={1.5} className="mr-2 h-4 w-4" />
              返回依赖
            </Button>
          )}
        </div>

        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-normal text-slate-950">工具依赖</h1>
        </div>

        {view === "library" ? (
          <section className="min-w-0">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-medium text-slate-900">项目依赖</h2>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void loadAddedTools()}
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
              <div className="py-3 text-sm text-slate-400">还没有加入依赖</div>
            ) : (
              <div className="grid grid-cols-1 gap-x-12 gap-y-2 md:grid-cols-2">
                {addedTools.map((tool) => (
                    <div
                      key={tool.id}
                      className="group flex items-center rounded-lg border border-transparent bg-white px-3 py-3 transition-colors hover:border-slate-200 hover:bg-slate-50"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-2">
                          <h3 className="truncate text-sm font-medium text-slate-800">{tool.name}</h3>
                          <SourceBadge source={tool.source} label={tool.sourceLabel} />
                          <PlatformBadge item={tool} />
                        </div>
                        <p className="mt-1 truncate font-mono text-xs text-slate-500">{tool.selectedPackageSpec}</p>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="ml-3 h-8 w-8 flex-shrink-0 text-slate-400 hover:bg-white hover:text-red-600"
                        onClick={() => removeAddedTool(tool.id)}
                        title="移除"
                      >
                        <Trash2 strokeWidth={1.5} className="h-3.5 w-3.5" />
                        <span className="sr-only">移除</span>
                      </Button>
                    </div>
                ))}
              </div>
            )}
          </section>
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
                    value={query}
                    onChange={(event) => {
                      setQuery(event.target.value);
                      setSearchPage(1);
                    }}
                    placeholder="在线搜索 Bioconda / conda-forge 依赖"
                    className="h-10 w-full rounded-md border-slate-200 bg-white pl-9"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {sourceFilters.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setSource(item.id)}
                      className={cn(
                        "h-8 rounded-md px-3 text-xs transition",
                        source === item.id
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

            <div className="grid grid-cols-1 gap-x-12 gap-y-6 lg:grid-cols-[minmax(0,1fr)_340px]">
              <section className="min-w-0">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-medium text-slate-900">搜索结果</h2>
                  <span className="text-xs text-slate-400">
                    {searchTotal > 0 ? `${searchComplete ? "" : "已加载 "}${searchTotal} 条` : filtered.length}
                  </span>
                </div>

                <div className="min-h-[320px] space-y-2">
                  {loading ? (
                    <div className="flex h-48 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm text-slate-500">
                      <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
                      正在在线搜索
                    </div>
                  ) : error ? (
                    <div className="flex h-48 items-center justify-center rounded-lg border border-red-100 bg-red-50 px-4 text-sm text-red-700">
                      <AlertCircle strokeWidth={1.5} className="mr-2 h-4 w-4" />
                      {error}
                    </div>
                  ) : query.trim().length < 2 ? (
                    <div className="px-1 py-3 text-sm text-slate-400">
                      输入至少 2 个字符开始搜索
                    </div>
                  ) : filtered.length === 0 ? (
                    <div className="flex h-48 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-sm text-slate-500">
                      没有找到匹配依赖
                    </div>
                  ) : (
                    <>
                      {filtered.map((item) => (
                        <ResultRow
                          key={item.id}
                          item={item}
                          selected={selected?.id === item.id}
                          onSelect={() => setSelectedId(item.id)}
                        />
                      ))}
                      <div className="flex items-center justify-between pt-2">
                        <Button
                          type="button"
                          variant="outline"
                          className="h-8 bg-white px-2.5 text-xs text-slate-600"
                          disabled={searchPage <= 1 || loading}
                          onClick={() => setSearchPage((current) => Math.max(1, current - 1))}
                        >
                          <ChevronLeft strokeWidth={1.5} className="mr-1 h-3.5 w-3.5" />
                          上一页
                        </Button>
                        <span className="text-xs text-slate-400">第 {searchPage} 页</span>
                        <Button
                          type="button"
                          variant="outline"
                          className="h-8 bg-white px-2.5 text-xs text-slate-600"
                          disabled={!searchHasMore || loading}
                          onClick={() => setSearchPage((current) => current + 1)}
                        >
                          下一页
                          <ChevronRight strokeWidth={1.5} className="ml-1 h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              </section>

              <aside className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/40">
                <h2 className="text-sm font-medium text-slate-900">依赖预览</h2>
                {selected ? (
                  <div className="mt-4 space-y-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="truncate text-base font-semibold text-slate-950">{selected.name}</h3>
                        <SourceBadge source={selected.source} label={selected.sourceLabel} />
                        <PlatformBadge item={selected} />
                      </div>
                      <p className="mt-2 text-xs leading-5 text-slate-500">{selected.summary || "Conda package"}</p>
                    </div>

                    <div className="rounded-lg border border-slate-200 bg-white p-3">
                      <div className="text-[11px] uppercase text-slate-400">目标平台</div>
                      <div className="mt-1 text-xs text-slate-700">
                        {selected.targetPlatform || "linux-64"}
                        {selected.targetPlatformSupported === true
                          ? " 可加入"
                          : selected.targetPlatformSupported === false
                            ? " 当前不可用"
                            : " 平台未知"}
                      </div>
                      {selected.platforms && selected.platforms.length > 0 ? (
                        <div className="mt-2 line-clamp-2 text-[11px] leading-4 text-slate-400">
                          支持平台：{selected.platforms.join(", ")}
                        </div>
                      ) : (
                        <div className="mt-2 text-[11px] text-slate-400">平台信息未声明</div>
                      )}
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[11px] uppercase text-slate-400" htmlFor="tool-version">
                        版本
                      </label>
                      <select
                        id="tool-version"
                        value={selectedVersion}
                        onChange={(event) =>
                          setVersionOverrides((current) => ({
                            ...current,
                            [selected.id]: event.target.value,
                          }))
                        }
                        className="h-9 w-full rounded-md border border-slate-200 bg-white px-3 font-mono text-xs text-slate-800 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
                      >
                        <option value="">不锁版本</option>
                        {selected.latestVersion ? (
                          <option value={selected.latestVersion}>latest {selected.latestVersion}</option>
                        ) : null}
                        {(selected.versions || [])
                          .filter((version) => version !== selected.latestVersion)
                          .slice()
                          .reverse()
                          .map((version) => (
                            <option key={version} value={version}>
                              {version}
                            </option>
                          ))}
                      </select>
                      <p className="text-[11px] leading-4 text-slate-400">
                        选择版本会锁定依赖，选择不锁版本则只记录包名。
                      </p>
                    </div>

                    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                      <div className="text-[11px] uppercase text-slate-400">包声明</div>
                      <div className="mt-1 font-mono text-xs text-slate-800">{selectedPackageSpec}</div>
                      {selected.sourceUrl ? (
                        <button
                          type="button"
                          onClick={() => void openSourceUrl(selected.sourceUrl || "")}
                          className="mt-2 inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
                        >
                          查看来源
                          <ExternalLink strokeWidth={1.5} className="h-3 w-3" />
                        </button>
                      ) : null}
                    </div>

                    <pre className="overflow-hidden rounded-md bg-slate-950 px-3 py-2 text-xs leading-5 text-slate-100">
{`channels:
  - ${selected.source}
  - ${selected.source === "bioconda" ? "conda-forge" : "bioconda"}
dependencies:
  - ${selectedPackageSpec}`}
                    </pre>

                    <Button
                      className="h-10 w-full bg-slate-950 text-white hover:bg-slate-800 disabled:bg-slate-200 disabled:text-slate-500"
                      disabled={!canAddSelected}
                      onClick={addSelectedTool}
                    >
                      {selectedAlreadyAdded ? "已加入" : "加入依赖"}
                    </Button>
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-slate-400">选择一个搜索结果</p>
                )}
              </aside>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
