"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import {
  Boxes,
  Check,
  CheckCircle2,
  Clock3,
  Database,
  Layers3,
  MoreHorizontal,
  Package,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Wrench,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { PluginCenterTargetContext } from "./plugin-center-extension-details";
import {
  PLUGIN_CENTER_CATEGORIES,
  type PluginCenterExtensionItem,
  type PluginCenterManagedManifestAction,
  type PluginCenterRegistry,
  type PluginCenterTask,
  type PluginCenterViewMode,
} from "./plugin-center-model";

type PluginCenterStatusFilter = "all" | "installed" | "updates" | "attention";

type PluginCenterExtensionManagerProps = {
  actionError?: string;
  activeTarget: PluginCenterTargetContext;
  items: PluginCenterExtensionItem[];
  registries: PluginCenterRegistry[];
  tasks: PluginCenterTask[];
  viewMode: PluginCenterViewMode;
  query: string;
  sourceFilter: string;
  busyActionKey?: string;
  children?: ReactNode;
  loadError?: string;
  loading?: boolean;
  remoteDetail?: ReactNode;
  onViewModeChange: (mode: PluginCenterViewMode) => void;
  onQueryChange: (query: string) => void;
  onSourceFilterChange: (sourceId: string) => void;
  onPrimaryAction: (item: PluginCenterExtensionItem) => void;
  onExtensionAction: (item: PluginCenterExtensionItem, action: string) => void;
  onOpenDetails: (item: PluginCenterExtensionItem) => void;
  onRetry: () => void;
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

const STATUS_FILTERS: Array<{ id: PluginCenterStatusFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "installed", label: "已安装" },
  { id: "updates", label: "可更新" },
  { id: "attention", label: "需要处理" },
];

export function PluginCenterExtensionManager({
  actionError = "",
  activeTarget,
  busyActionKey = "",
  children,
  items,
  loadError = "",
  loading = false,
  onExtensionAction,
  onOpenDetails,
  onPrimaryAction,
  onQueryChange,
  onRetry,
  onSourceFilterChange,
  onViewModeChange,
  query,
  registries,
  remoteDetail,
  sourceFilter,
  tasks,
  viewMode,
}: PluginCenterExtensionManagerProps) {
  const [statusFilter, setStatusFilter] = useState<PluginCenterStatusFilter>("all");
  const modeItems = items.filter((item) => (viewMode === "skills" ? item.kind === "skill" : item.kind !== "skill"));
  const registryById = new Map(registries.map((registry) => [registry.id, registry]));
  const sourceOptions = sourceFilterOptions(modeItems, registries);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredItems = modeItems.filter((item) => {
    const registry = registryById.get(item.registryId);
    const matchesSource = sourceFilter === "all" || item.registryId === sourceFilter;
    const matchesQuery =
      !normalizedQuery ||
      [item.name, item.summary, item.publisher, registry?.label || item.registryId, ...item.tags]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    return matchesSource && matchesQuery && matchesStatus(item, statusFilter);
  });
  const installedItems = modeItems.filter((item) => item.installed || item.enabled);
  const activeTasks = tasks.filter((task) => task.active);
  const selectedStatusLabel = STATUS_FILTERS.find((filter) => filter.id === statusFilter)?.label || "全部";
  const initialLoading = loading && items.length === 0;
  const showEmpty = !initialLoading && !(loadError && items.length === 0) && filteredItems.length === 0;

  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-4 py-6 text-slate-800 sm:px-6 sm:py-8 lg:px-8">
      <div className="mx-auto max-w-6xl space-y-7" data-testid="plugin-center-page">
        <header className="space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="inline-flex rounded-lg bg-slate-100 p-1" role="tablist" aria-label="插件中心视图">
              <TabButton
                active={viewMode === "plugins"}
                controls="plugin-center-results"
                onClick={() => onViewModeChange("plugins")}
              >
                插件
              </TabButton>
              <TabButton
                active={viewMode === "skills"}
                controls="plugin-center-results"
                onClick={() => onViewModeChange("skills")}
              >
                技能
              </TabButton>
            </div>
            <TargetStatus target={activeTarget} />
          </div>

          <div className="mx-auto max-w-3xl space-y-4 text-center">
            <div>
              <h1 className="text-3xl font-semibold tracking-normal text-slate-950">
                {viewMode === "skills" ? "技能" : "插件"}
              </h1>
              <p className="mt-2 text-sm text-slate-500">统一管理 H2OMeta 执行器、工具目录、运行环境和技能入口。</p>
            </div>
            <div className="relative">
              <Search strokeWidth={1.5} className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                className="h-11 rounded-full pl-9"
                value={query}
                type="search"
                placeholder={viewMode === "skills" ? "搜索技能" : "搜索插件"}
                aria-label={viewMode === "skills" ? "搜索技能" : "搜索插件"}
                aria-controls="plugin-center-results"
                aria-describedby="plugin-center-result-status"
                onChange={(event) => onQueryChange(event.target.value)}
                data-testid="plugin-center-search"
              />
            </div>
            <p id="plugin-center-result-status" className="sr-only" aria-live="polite">
              {initialLoading ? "正在加载插件 registry" : `当前显示 ${filteredItems.length} 个结果`}
            </p>
          </div>
        </header>

        <div aria-live="assertive" aria-atomic="true">
          {actionError ? (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              操作失败：{actionError}
            </div>
          ) : null}
        </div>

        <InstalledExtensionStrip items={installedItems} onSelect={onOpenDetails} />

        {loadError ? (
          <div role="alert" className="flex flex-col gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 sm:flex-row sm:items-center sm:justify-between">
            <span>
              插件 registry 加载失败：{loadError}
              {items.length ? "。当前保留并显示上次成功加载的数据。" : "。尚未获得可显示的数据。"}
            </span>
            <Button type="button" variant="outline" size="sm" disabled={loading} onClick={onRetry}>
              <RefreshCw className={cn("mr-2 h-4 w-4", loading && "animate-spin")} />
              重试
            </Button>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div
            className="flex max-w-full flex-wrap gap-1"
            role="group"
            aria-label="Registry 来源筛选"
            data-testid="plugin-center-source-tabs"
          >
            {sourceOptions.map((source) => (
              <button
                key={source.id}
                type="button"
                aria-pressed={sourceFilter === source.id}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm transition-colors",
                  sourceFilter === source.id
                    ? "bg-slate-100 text-slate-950"
                    : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"
                )}
                onClick={() => onSourceFilterChange(source.id)}
              >
                {source.label}
              </button>
            ))}
          </div>
          <StatusFilterMenu value={statusFilter} label={selectedStatusLabel} onChange={setStatusFilter} />
        </div>

        <main id="plugin-center-results" className="space-y-8" aria-busy={initialLoading}>
          {initialLoading ? <PluginCenterLoadingState /> : null}
          {!initialLoading
            ? PLUGIN_CENTER_CATEGORIES.map((category) => {
                const categoryItems = filteredItems.filter((item) => item.categoryIds.includes(category.id));
                if (categoryItems.length === 0) return null;
                return (
                  <ExtensionCategorySection
                    key={category.id}
                    items={categoryItems}
                    registries={registryById}
                    title={category.label}
                    busyActionKey={busyActionKey}
                    onExtensionAction={onExtensionAction}
                    onOpenDetails={onOpenDetails}
                    onPrimaryAction={onPrimaryAction}
                  />
                );
              })
            : null}
          {showEmpty ? (
            <div className="rounded-lg border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
              没有匹配当前搜索与筛选条件的{viewMode === "skills" ? "技能" : "插件"}。
            </div>
          ) : null}
        </main>

        <ExtensionJobQueuePanel activeCount={activeTasks.length} tasks={tasks} />
        {remoteDetail ? <section id="remote-runner-detail">{remoteDetail}</section> : null}
        {children}
      </div>
    </div>
  );
}

function TabButton({
  active,
  children,
  controls,
  onClick,
}: {
  active: boolean;
  children: ReactNode;
  controls: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      aria-controls={controls}
      tabIndex={active ? 0 : -1}
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

function TargetStatus({ target }: { target: PluginCenterTargetContext }) {
  const statusLabel = target.loading ? "连接状态待确认" : target.connected ? "已连接" : "未连接";
  const trustLabel = target.loading ? "信任状态待确认" : target.trusted ? "Host key 已信任" : "Host key 待确认";
  return (
    <div
      className="flex min-w-0 max-w-full items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700"
      role="status"
      aria-label={`当前目标 ${target.label}，${statusLabel}，${trustLabel}`}
    >
      <Server strokeWidth={1.5} className="h-4 w-4 shrink-0 text-slate-500" />
      <span className="max-w-[min(18rem,55vw)] truncate font-medium">{target.label}</span>
      <span className={cn("h-2 w-2 shrink-0 rounded-full", target.loading ? "bg-slate-400" : target.connected ? "bg-emerald-500" : "bg-amber-500")} />
      <span className="shrink-0 text-xs text-slate-500">{statusLabel}</span>
      <span className="hidden shrink-0 text-xs text-slate-500 sm:inline">{trustLabel}</span>
    </div>
  );
}

function StatusFilterMenu({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: PluginCenterStatusFilter) => void;
  value: PluginCenterStatusFilter;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title={`状态筛选：${label}`}
          aria-label={`状态筛选：${label}`}
          aria-pressed={value !== "all"}
        >
          <SlidersHorizontal strokeWidth={1.5} className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" aria-label="状态筛选选项">
        {STATUS_FILTERS.map((filter) => (
          <DropdownMenuItem
            key={filter.id}
            className="justify-between gap-4"
            aria-current={value === filter.id ? "true" : undefined}
            onSelect={() => onChange(filter.id)}
          >
            {filter.label}
            {value === filter.id ? <Check className="h-4 w-4" /> : <span className="h-4 w-4" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
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
              aria-label={`打开 ${item.name} 详情，状态 ${item.healthLabel}`}
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
  busyActionKey,
  items,
  onExtensionAction,
  onOpenDetails,
  onPrimaryAction,
  registries,
  title,
}: {
  busyActionKey: string;
  items: PluginCenterExtensionItem[];
  onExtensionAction: (item: PluginCenterExtensionItem, action: string) => void;
  onOpenDetails: (item: PluginCenterExtensionItem) => void;
  onPrimaryAction: (item: PluginCenterExtensionItem) => void;
  registries: Map<string, PluginCenterRegistry>;
  title: string;
}) {
  return (
    <section className="space-y-4" data-plugin-category={title}>
      <div className="border-b border-slate-100 pb-3">
        <h2 className="text-base font-semibold text-slate-950">{title}</h2>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        {items.map((item) => (
          <ExtensionCard
            key={`${title}-${item.id}`}
            busyActionKey={busyActionKey}
            item={item}
            registry={registries.get(item.registryId)}
            onExtensionAction={onExtensionAction}
            onOpenDetails={onOpenDetails}
            onPrimaryAction={onPrimaryAction}
          />
        ))}
      </div>
    </section>
  );
}

function ExtensionCard({
  busyActionKey,
  item,
  onExtensionAction,
  onOpenDetails,
  onPrimaryAction,
  registry,
}: {
  busyActionKey: string;
  item: PluginCenterExtensionItem;
  onExtensionAction: (item: PluginCenterExtensionItem, action: string) => void;
  onOpenDetails: (item: PluginCenterExtensionItem) => void;
  onPrimaryAction: (item: PluginCenterExtensionItem) => void;
  registry?: PluginCenterRegistry;
}) {
  const Icon = iconFor(item);
  const declaredActions = extensionActionOptions(item);
  const secondaryActions = declaredActions.filter((action) => action.id !== item.primaryAction);
  const primaryManagedAction = declaredActions.find((action) => action.id === item.primaryAction);
  const primaryIsManaged = ["install", "repair", "update", "uninstall"].includes(item.primaryAction);
  const showPrimary =
    (!primaryIsManaged || Boolean(primaryManagedAction)) &&
    (item.primaryAction !== "update" || item.updateAvailable === true);
  const mutationActive = item.installState === "installing" || item.installState === "updating";
  const itemBusy = busyActionKey.startsWith(`${item.id}:`);
  const primaryBusy = busyActionKey === `${item.id}:${item.primaryAction}:run`;
  const primaryDisabled = mutationActive || itemBusy;

  return (
    <article className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3 rounded-lg border border-slate-200 bg-white p-3 shadow-sm shadow-slate-900/5 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-center">
      <div className={cn("grid h-10 w-10 place-items-center rounded-lg border", iconTone(item))}>
        <Icon strokeWidth={1.6} className="h-5 w-5" />
      </div>
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <button
            type="button"
            className="min-w-0 truncate text-left text-sm font-semibold text-slate-950 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
            onClick={() => onOpenDetails(item)}
          >
            {item.name}
          </button>
          <span className={cn("rounded-md px-1.5 py-0.5 text-[11px] font-medium", healthTone(item.health))}>
            {item.healthLabel}
          </span>
          {item.updateAvailable ? <span className="rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-700">可更新</span> : null}
        </div>
        <p className="mt-1 line-clamp-2 text-sm text-slate-500">{item.summary}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
          <span>{registry?.label || item.registryId}</span>
          {item.installedVersion ? <span className="font-mono">v{item.installedVersion}</span> : null}
          {item.detailLabel ? <span>{item.detailLabel}</span> : null}
        </div>
      </div>
      <div className="col-span-2 flex min-h-8 items-center justify-end gap-1 sm:col-span-1">
        {showPrimary ? (
          item.primaryAction === "manage" && item.manageHref ? (
            <Button asChild variant="outline" size="sm">
              <Link href={item.manageHref}>{item.primaryActionLabel}</Link>
            </Button>
          ) : (
            <Button
              type="button"
              variant={item.primaryAction === "install" || item.primaryAction === "repair" ? "default" : "outline"}
              size="sm"
              disabled={primaryDisabled}
              onClick={() => onPrimaryAction(item)}
            >
              {primaryBusy || mutationActive ? "执行中" : item.primaryActionLabel}
            </Button>
          )
        ) : null}
        {secondaryActions.length ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                title="更多操作"
                aria-label={`${item.name} 更多操作`}
                className="h-8 w-8"
                disabled={mutationActive || itemBusy}
              >
                <MoreHorizontal strokeWidth={1.6} className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {secondaryActions.map((action) => {
                const busy = busyActionKey.startsWith(`${item.id}:${action.id}:`);
                return (
                  <DropdownMenuItem
                    key={action.id}
                    destructive={action.id === "uninstall"}
                    disabled={busy || mutationActive}
                    onSelect={() => onExtensionAction(item, action.id)}
                  >
                    {action.id === "uninstall" ? <Trash2 className="mr-2 h-4 w-4" /> : <RefreshCw className="mr-2 h-4 w-4" />}
                    {busy ? "执行中" : action.label}
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
    </article>
  );
}

function extensionActionOptions(item: PluginCenterExtensionItem): PluginCenterManagedManifestAction[] {
  return item.manifest.actions
    .filter((action): action is PluginCenterManagedManifestAction => action.type === "managed-extension-action")
    .filter((action) => item.actions.includes(action.id as PluginCenterExtensionItem["actions"][number]))
    .filter((action) => action.id !== "update" || item.updateAvailable === true);
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
    <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3 px-3 py-3 text-sm sm:grid-cols-[auto_minmax(0,1fr)_auto]">
      <Icon strokeWidth={1.5} className={cn("h-4 w-4", task.active ? "text-blue-600" : task.status === "failed" ? "text-red-600" : "text-emerald-600")} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-slate-950">{task.target}</span>
          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">{task.kind}</span>
        </div>
        <div className="mt-1 truncate text-xs text-slate-500">{task.message || task.stage}</div>
      </div>
      <div className="col-span-2 text-right sm:col-span-1">
        <div className="text-xs font-medium text-slate-800">{task.status}</div>
        <div className="mt-1 text-[11px] text-slate-500">{task.stage}</div>
      </div>
    </div>
  );
}

function PluginCenterLoadingState() {
  return (
    <div className="space-y-3" role="status" aria-label="正在加载插件 registry">
      <div className="h-5 w-32 animate-pulse rounded bg-slate-100" />
      {[0, 1, 2].map((index) => (
        <div key={index} className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-3 rounded-lg border border-slate-200 p-3">
          <div className="h-10 w-10 animate-pulse rounded-lg bg-slate-100" />
          <div className="space-y-2 py-1">
            <div className="h-3 w-40 max-w-full animate-pulse rounded bg-slate-100" />
            <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
          </div>
        </div>
      ))}
      <span className="sr-only">正在加载</span>
    </div>
  );
}

function sourceFilterOptions(
  items: PluginCenterExtensionItem[],
  registries: PluginCenterRegistry[]
): Array<{ id: string; label: string }> {
  const availableIds = new Set(items.map((item) => item.registryId));
  const sources = registries
    .filter((registry) => availableIds.has(registry.id))
    .sort((left, right) => right.priority - left.priority || left.label.localeCompare(right.label))
    .map((registry) => ({ id: registry.id, label: registry.label }));
  return [{ id: "all", label: "全部来源" }, ...sources];
}

function matchesStatus(item: PluginCenterExtensionItem, filter: PluginCenterStatusFilter): boolean {
  if (filter === "installed") return item.installed || item.enabled;
  if (filter === "updates") return item.updateAvailable === true;
  if (filter === "attention") {
    return item.installState === "failed" || item.health === "failed" || ((item.installed || item.enabled) && item.health === "warning");
  }
  return true;
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
