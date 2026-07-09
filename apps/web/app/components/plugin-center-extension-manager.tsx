"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import {
  Boxes,
  CheckCircle2,
  Clock3,
  Database,
  Layers3,
  Package,
  Plug,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Wrench,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import {
  PLUGIN_CENTER_CATEGORIES,
  type PluginCenterExtensionItem,
  type PluginCenterSourceType,
  type PluginCenterTask,
  type PluginCenterViewMode,
} from "./plugin-center-model";

type PluginCenterExtensionManagerProps = {
  items: PluginCenterExtensionItem[];
  tasks: PluginCenterTask[];
  viewMode: PluginCenterViewMode;
  query: string;
  sourceFilter: string;
  remoteDetail?: ReactNode;
  onViewModeChange: (mode: PluginCenterViewMode) => void;
  onQueryChange: (query: string) => void;
  onSourceFilterChange: (sourceId: string) => void;
  onPrimaryAction: (item: PluginCenterExtensionItem) => void;
};

const ICONS: Record<string, LucideIcon> = {
  boxes: Boxes,
  database: Database,
  layers: Layers3,
  package: Package,
  server: Server,
  shield: ShieldCheck,
  sparkles: Sparkles,
  wrench: Wrench,
};

export function PluginCenterExtensionManager({
  items,
  onPrimaryAction,
  onQueryChange,
  onSourceFilterChange,
  onViewModeChange,
  query,
  remoteDetail,
  sourceFilter,
  tasks,
  viewMode,
}: PluginCenterExtensionManagerProps) {
  const modeItems = items.filter((item) => (viewMode === "skills" ? item.kind === "skill" : item.kind !== "skill"));
  const sourceOptions = sourceFilterOptions(modeItems);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredItems = modeItems.filter((item) => {
    const matchesSource = sourceFilter === "all" || item.sourceId === sourceFilter;
    const matchesQuery =
      !normalizedQuery ||
      [item.name, item.summary, item.publisher, item.sourceLabel, ...item.tags]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    return matchesSource && matchesQuery;
  });
  const installedItems = modeItems.filter((item) => item.installed || item.enabled);
  const activeTasks = tasks.filter((task) => task.active);

  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-4 py-6 text-slate-800 sm:px-6 sm:py-10 lg:px-8">
      <div className="mx-auto max-w-6xl space-y-8" data-testid="plugin-center-page">
        <header className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="inline-flex rounded-lg bg-slate-100 p-1" aria-label="插件视图">
              <TabButton active={viewMode === "plugins"} onClick={() => onViewModeChange("plugins")}>
                插件
              </TabButton>
              <TabButton active={viewMode === "skills"} onClick={() => onViewModeChange("skills")}>
                技能
              </TabButton>
            </div>
            <div className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
              <Plug strokeWidth={1.5} className="h-4 w-4" />
              本地
            </div>
          </div>

          <div className="mx-auto max-w-3xl space-y-4 text-center">
            <div>
              <h1 className="text-3xl font-semibold tracking-normal text-slate-950">插件</h1>
              <p className="mt-2 text-sm text-slate-500">统一管理 H2OMeta 执行器、工具目录、运行环境和技能入口。</p>
            </div>
            <div className="relative">
              <Search strokeWidth={1.5} className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                className="h-11 rounded-full pl-9"
                value={query}
                placeholder={viewMode === "skills" ? "搜索技能" : "搜索插件"}
                onChange={(event) => onQueryChange(event.target.value)}
                data-testid="plugin-center-search"
              />
            </div>
          </div>
        </header>

        <InstalledExtensionStrip items={installedItems} onSelect={(item) => onQueryChange(item.name)} />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2" data-testid="plugin-center-source-tabs">
            {sourceOptions.map((source) => (
              <button
                key={source.id}
                type="button"
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm transition-colors",
                  sourceFilter === source.id ? "bg-slate-100 text-slate-950" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"
                )}
                onClick={() => onSourceFilterChange(source.id)}
              >
                {source.label}
              </button>
            ))}
          </div>
          <Button type="button" variant="ghost" size="icon" title="筛选">
            <SlidersHorizontal strokeWidth={1.5} className="h-4 w-4" />
          </Button>
        </div>

        <main className="space-y-8">
          {PLUGIN_CENTER_CATEGORIES.map((category) => {
            const categoryItems = filteredItems.filter((item) => item.categoryIds.includes(category.id));
            if (categoryItems.length === 0) return null;
            return (
              <ExtensionCategorySection
                key={category.id}
                items={categoryItems}
                title={category.label}
                onPrimaryAction={onPrimaryAction}
              />
            );
          })}
          {filteredItems.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
              没有匹配的{viewMode === "skills" ? "技能" : "插件"}。
            </div>
          ) : null}
        </main>

        <ExtensionJobQueuePanel activeCount={activeTasks.length} tasks={tasks} />
        {remoteDetail ? <section id="remote-runner-detail">{remoteDetail}</section> : null}
      </div>
    </div>
  );
}

function TabButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={cn(
        "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
        active ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-800"
      )}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function InstalledExtensionStrip({
  items,
  onSelect,
}: {
  items: PluginCenterExtensionItem[];
  onSelect: (item: PluginCenterExtensionItem) => void;
}) {
  if (items.length === 0) return null;
  return (
    <section className="mx-auto max-w-3xl space-y-3" data-testid="plugin-center-installed-strip">
      <div className="flex items-center justify-between border-b border-slate-100 pb-2">
        <h2 className="text-sm font-semibold text-slate-950">已安装</h2>
        <Wrench strokeWidth={1.5} className="h-4 w-4 text-slate-400" />
      </div>
      <div className="flex flex-wrap gap-3">
        {items.map((item) => {
          const Icon = iconFor(item);
          return (
            <button
              key={item.id}
              type="button"
              title={`${item.name} · ${item.healthLabel}`}
              className="grid h-11 w-11 place-items-center rounded-lg border border-slate-200 bg-white text-slate-700 shadow-sm shadow-slate-900/5 transition-colors hover:border-slate-300 hover:bg-slate-50"
              onClick={() => onSelect(item)}
            >
              <Icon strokeWidth={1.6} className="h-5 w-5" />
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ExtensionCategorySection({
  items,
  onPrimaryAction,
  title,
}: {
  items: PluginCenterExtensionItem[];
  onPrimaryAction: (item: PluginCenterExtensionItem) => void;
  title: string;
}) {
  return (
    <section className="space-y-4" data-plugin-category={title}>
      <div className="border-b border-slate-100 pb-3">
        <h2 className="text-base font-semibold text-slate-950">{title}</h2>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {items.map((item) => (
          <ExtensionCard key={`${title}-${item.id}`} item={item} onPrimaryAction={onPrimaryAction} />
        ))}
      </div>
    </section>
  );
}

function ExtensionCard({
  item,
  onPrimaryAction,
}: {
  item: PluginCenterExtensionItem;
  onPrimaryAction: (item: PluginCenterExtensionItem) => void;
}) {
  const Icon = iconFor(item);
  const disabled = item.primaryAction === "try_in_chat" && !item.tryInChat?.enabled;
  return (
    <article className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 shadow-sm shadow-slate-900/5">
      <div className={cn("grid h-10 w-10 place-items-center rounded-lg border", iconTone(item))}>
        <Icon strokeWidth={1.6} className="h-5 w-5" />
      </div>
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-semibold text-slate-950">{item.name}</h3>
          <span className={cn("rounded-md px-1.5 py-0.5 text-[11px] font-medium", healthTone(item.health))}>
            {item.healthLabel}
          </span>
        </div>
        <p className="mt-1 truncate text-sm text-slate-500">{item.summary}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
          <span>{item.sourceLabel}</span>
          {item.installedVersion ? <span className="font-mono">v{item.installedVersion}</span> : null}
          {item.detailLabel ? <span>{item.detailLabel}</span> : null}
        </div>
      </div>
      {item.primaryAction === "manage" && item.manageHref ? (
        <Button asChild variant="outline" size="sm">
          <Link href={item.manageHref}>{item.primaryActionLabel}</Link>
        </Button>
      ) : (
        <Button type="button" variant={item.primaryAction === "install" ? "default" : "outline"} size="sm" disabled={disabled} onClick={() => onPrimaryAction(item)}>
          {item.primaryActionLabel}
        </Button>
      )}
    </article>
  );
}

function ExtensionJobQueuePanel({
  activeCount,
  tasks,
}: {
  activeCount: number;
  tasks: PluginCenterTask[];
}) {
  return (
    <section className="space-y-4" data-testid="plugin-center-installation-tasks-card">
      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
        <div>
          <h2 className="text-base font-semibold text-slate-950">安装任务</h2>
          <p className="mt-1 text-sm text-slate-500">远端执行器 provisioning 与工具准备任务。</p>
        </div>
        <span className="rounded-lg bg-slate-100 px-2.5 py-1 text-sm font-medium text-slate-700">活跃 {activeCount}</span>
      </div>
      {tasks.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-200 px-4 py-6 text-sm text-slate-500">
          暂无安装任务。
        </div>
      ) : (
        <div className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
          {tasks.slice(0, 8).map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}
        </div>
      )}
    </section>
  );
}

function TaskRow({ task }: { task: PluginCenterTask }) {
  const Icon = task.active ? Clock3 : task.status === "failed" ? XCircle : CheckCircle2;
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-3 py-3 text-sm">
      <Icon strokeWidth={1.5} className={cn("h-4 w-4", task.active ? "text-blue-600" : task.status === "failed" ? "text-red-600" : "text-emerald-600")} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-slate-950">{task.target}</span>
          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">{task.kind}</span>
        </div>
        <div className="mt-1 truncate text-xs text-slate-500">{task.message || task.stage}</div>
      </div>
      <div className="text-right">
        <div className="text-xs font-medium text-slate-800">{task.status}</div>
        <div className="mt-1 text-[11px] text-slate-500">{task.stage}</div>
      </div>
    </div>
  );
}

function sourceFilterOptions(items: PluginCenterExtensionItem[]): Array<{ id: string; label: string; type?: PluginCenterSourceType }> {
  const sources = new Map<string, { id: string; label: string; type?: PluginCenterSourceType }>();
  sources.set("all", { id: "all", label: "全部" });
  for (const item of items) {
    if (!sources.has(item.sourceId)) {
      sources.set(item.sourceId, { id: item.sourceId, label: item.sourceLabel, type: item.sourceType });
    }
  }
  return Array.from(sources.values());
}

function iconFor(item: PluginCenterExtensionItem): LucideIcon {
  return ICONS[item.icon] || Package;
}

function iconTone(item: PluginCenterExtensionItem): string {
  if (item.health === "ready") return "border-emerald-100 bg-emerald-50 text-emerald-700";
  if (item.health === "warning") return "border-amber-100 bg-amber-50 text-amber-700";
  if (item.health === "failed") return "border-red-100 bg-red-50 text-red-700";
  return "border-slate-100 bg-slate-50 text-slate-600";
}

function healthTone(health: PluginCenterExtensionItem["health"]): string {
  if (health === "ready") return "bg-emerald-50 text-emerald-700";
  if (health === "warning") return "bg-amber-50 text-amber-700";
  if (health === "failed") return "bg-red-50 text-red-700";
  return "bg-slate-100 text-slate-600";
}
