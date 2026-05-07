import { AlertCircle, ChevronLeft, ChevronRight, ExternalLink, Check, Loader2, PackagePlus, RefreshCw, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AddedTool, ToolSearchItem } from "./tools-page-model";

export function SourceBadge({ source, label }: { source: string; label: string }) {
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

export function formatPlatformBadgeText(item: ToolSearchItem) {
  const target = (item.targetPlatform || "").trim();
  const supported = item.targetPlatformSupported === true;
  const unsupported = item.targetPlatformSupported === false;
  const platforms = (item.platforms || []).map((platform) => platform.trim()).filter(Boolean);
  if (target) {
    return supported ? `${target} 可用` : unsupported ? `${target} 不支持` : `${target} 平台状态未知`;
  }
  if (platforms.length === 1) {
    return `支持 ${platforms[0]}`;
  }
  if (platforms.length > 1) {
    return `支持 ${platforms.length} 个平台`;
  }
  return "平台未知";
}

export function PlatformBadge({ item }: { item: ToolSearchItem }) {
  const supported = item.targetPlatformSupported === true;
  const unsupported = item.targetPlatformSupported === false;
  const hasPlatformInfo = Boolean((item.targetPlatform || "").trim()) || Boolean(item.platforms && item.platforms.length > 0);
  const platforms = (item.platforms || []).map((platform) => platform.trim()).filter(Boolean);
  return (
    <span
      title={platforms.length > 0 ? `支持平台：${platforms.join(", ")}` : undefined}
      className={cn(
        "inline-flex h-5 items-center rounded border px-1.5 text-[11px] leading-none",
        supported && "border-blue-200 bg-blue-50 text-blue-700",
        unsupported && "border-amber-200 bg-amber-50 text-amber-700",
        !supported && !unsupported && hasPlatformInfo && "border-blue-200 bg-blue-50 text-blue-700",
        !supported && !unsupported && !hasPlatformInfo && "border-slate-200 bg-slate-50 text-slate-500"
      )}
    >
      {formatPlatformBadgeText(item)}
    </span>
  );
}

export function PlatformChips({ platforms }: { platforms: string[] | undefined }) {
  const items = (platforms || []).map((platform) => platform.trim()).filter(Boolean);
  if (items.length === 0) {
    return <div className="mt-2 text-[11px] text-slate-400">平台信息未声明</div>;
  }
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {items.map((platform) => (
        <span
          key={platform}
          className="inline-flex h-6 items-center rounded-md border border-blue-200 bg-blue-50 px-2 font-mono text-[11px] leading-none text-blue-700"
        >
          {platform}
        </span>
      ))}
    </div>
  );
}

export function ResultRow({
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

export function ToolsLibrarySection({
  addedTools,
  toolsError,
  toolsLoading,
  onRefresh,
  onRemove,
}: {
  addedTools: AddedTool[];
  toolsError: string;
  toolsLoading: boolean;
  onRefresh: () => void;
  onRemove: (id: string) => void;
}) {
  return (
    <section className="min-w-0">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-900">项目依赖</h2>
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
                onClick={() => onRemove(tool.id)}
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
  );
}

export function ToolSearchResults({
  error,
  filtered,
  loading,
  query,
  searchComplete,
  searchHasMore,
  searchPage,
  searchTotal,
  selectedId,
  onPageChange,
  onSelect,
}: {
  error: string;
  filtered: ToolSearchItem[];
  loading: boolean;
  query: string;
  searchComplete: boolean;
  searchHasMore: boolean;
  searchPage: number;
  searchTotal: number;
  selectedId: string;
  onPageChange: (page: number | ((current: number) => number)) => void;
  onSelect: (id: string) => void;
}) {
  const selected = filtered.find((item) => item.id === selectedId) ?? filtered[0];

  return (
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
          <div className="px-1 py-3 text-sm text-slate-400">输入至少 2 个字符开始搜索</div>
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
                onSelect={() => onSelect(item.id)}
              />
            ))}
            <div className="flex items-center justify-between pt-2">
              <Button
                type="button"
                variant="outline"
                className="h-8 bg-white px-2.5 text-xs text-slate-600"
                disabled={searchPage <= 1 || loading}
                onClick={() => onPageChange((current) => Math.max(1, current - 1))}
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
                onClick={() => onPageChange((current) => current + 1)}
              >
                下一页
                <ChevronRight strokeWidth={1.5} className="ml-1 h-3.5 w-3.5" />
              </Button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

export function ToolPreviewPanel({
  canAddSelected,
  onAdd,
  onOpenSourceUrl,
  onVersionChange,
  selected,
  selectedAlreadyAdded,
  selectedPackageSpec,
  selectedVersion,
}: {
  canAddSelected: boolean;
  onAdd: () => void;
  onOpenSourceUrl: (url: string) => void;
  onVersionChange: (id: string, version: string) => void;
  selected: ToolSearchItem | undefined;
  selectedAlreadyAdded: boolean;
  selectedPackageSpec: string;
  selectedVersion: string;
}) {
  return (
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
              {(selected.targetPlatform || "").trim()
                ? `${(selected.targetPlatform || "").trim()}${
                    selected.targetPlatformSupported === true
                      ? " 可加入"
                      : selected.targetPlatformSupported === false
                        ? " 当前不可用"
                        : " 状态未知"
                  }`
                : "平台信息未声明"}
            </div>
            <div className="mt-3 text-[11px] uppercase text-slate-400">支持平台</div>
            <PlatformChips platforms={selected.platforms} />
          </div>

          <div className="space-y-1.5">
            <label className="text-[11px] uppercase text-slate-400" htmlFor="tool-version">
              版本
            </label>
            <select
              id="tool-version"
              value={selectedVersion}
              onChange={(event) => onVersionChange(selected.id, event.target.value)}
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
            <p className="text-[11px] leading-4 text-slate-400">选择版本会锁定依赖，选择不锁版本则只记录包名。</p>
          </div>

          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="text-[11px] uppercase text-slate-400">包声明</div>
            <div className="mt-1 font-mono text-xs text-slate-800">{selectedPackageSpec}</div>
            {selected.sourceUrl ? (
              <button
                type="button"
                onClick={() => onOpenSourceUrl(selected.sourceUrl || "")}
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
            onClick={onAdd}
          >
            {selectedAlreadyAdded ? "已加入" : "加入依赖"}
          </Button>
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-400">选择一个搜索结果</p>
      )}
    </aside>
  );
}
