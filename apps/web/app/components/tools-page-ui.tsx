import { AlertCircle, ChevronLeft, ChevronRight, ExternalLink, Check, Loader2, PackagePlus, RefreshCw, Trash2, Workflow } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { AddedTool, RuleSpecDraft, ToolSearchItem } from "./tools-page-model";

export function SourceBadge({ source, label }: { source: string; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded border px-1.5 text-[11px] leading-none",
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
        "inline-flex h-5 shrink-0 items-center rounded border px-1.5 text-[11px] leading-none",
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

export function WrapperBadge({ item }: { item: ToolSearchItem }) {
  const count = item.snakemakeWrapperCount || item.snakemakeWrappers?.length || 0;
  if (count <= 0) return null;
  return (
    <span
      title={`${count} 个 Snakemake wrapper 可复用`}
      className="inline-flex h-5 shrink-0 items-center rounded border border-violet-200 bg-violet-50 px-1.5 text-[11px] leading-none text-violet-700"
    >
      <Workflow strokeWidth={1.5} className="mr-1 h-3 w-3" />
      {count} wrapper
    </span>
  );
}

export function RuleNodeSummary({ item }: { item: ToolSearchItem }) {
  const template = ruleTemplateForItem(item);
  const inputs = Array.isArray(template.inputs) ? template.inputs.length : 0;
  const outputs = Array.isArray(template.outputs) ? template.outputs.length : 0;
  const params = template.params && typeof template.params === "object" && !Array.isArray(template.params)
    ? Object.keys(template.params).length
    : 0;
  const hasRuleSpec = Boolean(template.commandTemplate || template.wrapper || template.script || inputs > 0 || outputs > 0 || params > 0);
  return (
    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
      <Workflow strokeWidth={1.5} className="h-3 w-3 text-slate-400" />
      <span>{hasRuleSpec ? "RuleSpec" : "RuleSpec 待补全"}</span>
      <span>{inputs} in</span>
      <span>/</span>
      <span>{outputs} out</span>
      <span>/</span>
      <span>{params} params</span>
    </div>
  );
}

function RulePortPreview({ item, compact = false }: { item: ToolSearchItem; compact?: boolean }) {
  const template = ruleTemplateForItem(item);
  const inputs = rulePortItems(template, "inputs");
  const outputs = rulePortItems(template, "outputs");
  if (compact && inputs.length === 0 && outputs.length === 0) return null;
  const body = (
    <div className="grid gap-2">
      <RulePortGroup label="输入端口" ports={inputs} />
      <RulePortGroup label="输出端口" ports={outputs} />
    </div>
  );
  if (compact) {
    return <div className="mt-2">{body}</div>;
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 text-[11px] uppercase text-slate-400">Rule ports</div>
      {body}
    </div>
  );
}

function RulePortGroup({ label, ports }: { label: string; ports: RulePortItem[] }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      {ports.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {ports.map((port) => (
            <span
              key={`${label}-${port.name}`}
              title={port.detail}
              className="max-w-full truncate rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-600"
            >
              {formatRulePortLabel(port)}
            </span>
          ))}
        </div>
      ) : (
        <div className="mt-1 text-[11px] text-slate-400">未声明</div>
      )}
    </div>
  );
}

function rulePortItems(template: Record<string, unknown>, key: "inputs" | "outputs") {
  const raw = template[key];
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item, index) => {
      const port = recordValue(item);
      const name = stringValue(port.name) || `${key.slice(0, -1)}_${index + 1}`;
      const semantics = key === "outputs" ? outputSemanticTags(port) : [];
      const detail = ["type", "kind", "mimeType", "format", "edamFormat"]
        .map((field) => stringValue(port[field]))
        .concat(semantics)
        .filter(Boolean)
        .join(" / ");
      const summary = ["kind", "format", "edamFormat", "mimeType", "type"]
        .map((field) => stringValue(port[field]))
        .find(Boolean) || "";
      return { name, detail: detail || "未声明类型", summary, semantics };
    })
    .filter((item) => item.name);
}

type RulePortItem = {
  name: string;
  detail: string;
  summary: string;
  semantics: string[];
};

function formatRulePortLabel(port: RulePortItem) {
  const summary = [port.summary, ...port.semantics].filter(Boolean).join(" · ");
  return summary ? `${port.name} · ${summary}` : port.name;
}

function outputSemanticTags(port: Record<string, unknown>) {
  return ["directory", "protected", "temp"].filter((field) => port[field] === true);
}

function ruleTemplateForItem(item: ToolSearchItem): Record<string, unknown> {
  const manifest = (item.ruleTemplate || {}) as Record<string, unknown>;
  const draft = (item.ruleSpecDraft?.ruleTemplate || {}) as Record<string, unknown>;
  if (hasRuleAction(manifest)) return manifest;
  if (hasRuleAction(draft)) return draft;
  return Object.keys(manifest).length > 0 ? manifest : draft;
}

function hasRuleAction(template: Record<string, unknown>) {
  return Boolean(stringValue(template.commandTemplate) || stringValue(template.wrapper) || stringValue(template.script));
}

function recordValue(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
}

function stringValue(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
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
        "group flex w-full items-center rounded-lg border px-3 py-3 text-left transition sm:px-4",
        selected
          ? "border-blue-200 bg-blue-50/60"
          : "border-transparent bg-white hover:border-slate-200 hover:bg-slate-50"
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <h3 className="min-w-0 truncate text-sm font-medium text-slate-900">{item.name}</h3>
          <SourceBadge source={item.source} label={item.sourceLabel} />
          <PlatformBadge item={item} />
          <WrapperBadge item={item} />
        </div>
        <p className="mt-1 truncate text-xs text-slate-500">{item.summary || "Conda package"}</p>
        <RuleNodeSummary item={item} />
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
        <div className="grid grid-cols-1 gap-x-12 gap-y-2 md:grid-cols-2">
          {addedTools.map((tool) => (
            <div
              key={tool.id}
              className="group flex items-center rounded-lg border border-transparent bg-white px-3 py-3 transition-colors hover:border-slate-200 hover:bg-slate-50"
            >
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
            没有找到匹配工具
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

function SnakemakeWrapperPreview({
  selected,
  onOpenSourceUrl,
}: {
  selected: ToolSearchItem;
  onOpenSourceUrl: (url: string) => void;
}) {
  const wrappers = selected.snakemakeWrappers || [];
  if (wrappers.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="text-[11px] uppercase text-slate-400">Snakemake wrapper</div>
        <div className="mt-1 text-xs leading-5 text-slate-500">未命中同名官方 wrapper；可作为 shell RuleSpec 节点使用。</div>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[11px] uppercase text-violet-500">Snakemake wrapper</div>
        <span className="text-[11px] text-violet-600">{wrappers.length} 个命中</span>
      </div>
      <div className="mt-2 space-y-1.5">
        {wrappers.slice(0, 4).map((wrapper) => (
          <button
            key={wrapper.wrapperPath}
            type="button"
            onClick={() => onOpenSourceUrl(wrapper.wrapperUrl)}
            className="flex w-full min-w-0 items-center justify-between gap-2 rounded-md bg-white/70 px-2 py-1.5 text-left text-xs text-violet-800 hover:bg-white"
          >
            <span className="truncate font-mono">{wrapper.wrapperPath}</span>
            <ExternalLink strokeWidth={1.5} className="h-3 w-3 flex-shrink-0" />
          </button>
        ))}
      </div>
      <p className="mt-2 text-[11px] leading-4 text-violet-600">
        当前 wrapper ref 已随 RuleSpec 草稿锁定。
      </p>
    </div>
  );
}

function ruleSpecDraftTitle(draft: RuleSpecDraft | undefined) {
  if (!draft) return "RuleSpec 草稿";
  if (draft.source === "snakemake-wrapper") return "生成 wrapper RuleSpec";
  return "生成自定义 RuleSpec";
}

function ruleSpecDraftLockText(draft: RuleSpecDraft | undefined) {
  const lock = draft?.lock || {};
  const wrapperIdentifier = String(lock.wrapperIdentifier || "");
  if (wrapperIdentifier) return wrapperIdentifier;
  const packageSpec = String(lock.packageSpec || "");
  if (packageSpec) return packageSpec;
  return "";
}

function ruleSpecDraftCommand(draft: RuleSpecDraft | undefined) {
  const template = draft?.ruleTemplate || {};
  if (typeof template.commandTemplate === "string") return template.commandTemplate;
  return typeof template.script === "string" ? `script: ${template.script}` : "";
}

function RuleSpecDraftPreview({ draft }: { draft: RuleSpecDraft | undefined }) {
  if (!draft) return null;
  const lockText = ruleSpecDraftLockText(draft);
  const command = ruleSpecDraftCommand(draft);
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] uppercase text-slate-400">RuleSpec 草稿</div>
        <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-500">
          {draft.requiresUserCompletion ? "待确认" : "可用"}
        </span>
      </div>
      <div className="mt-1 text-sm font-medium text-slate-900">{ruleSpecDraftTitle(draft)}</div>
      {lockText ? <div className="mt-2 truncate font-mono text-[11px] text-slate-500">{lockText}</div> : null}
      {command ? (
        <pre className="mt-2 overflow-hidden rounded-md bg-slate-950 px-2 py-1.5 text-[11px] leading-4 text-slate-100">
          {command}
        </pre>
      ) : null}
    </div>
  );
}

function RuleSpecContractPreview({ item }: { item: ToolSearchItem }) {
  const template = ruleTemplateForItem(item);
  const action = ruleSpecActionText(template);
  const params = ruleSpecParamItems(template);
  const resources = ruleSpecResourceItems(template);
  const environment = ruleSpecEnvironmentItems(template);
  const hasContract = Boolean(action || params.length > 0 || resources.length > 0 || environment.length > 0);
  if (!hasContract) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 text-[11px] uppercase text-slate-400">RuleSpec contract</div>
      <div className="grid gap-2">
        <RuleSpecContractRow label="Action" value={action || "待补全"} monospace={Boolean(action)} />
        <RuleSpecContractList label="运行环境" items={environment} empty="未声明 conda/container" />
        <RuleSpecContractList label="参数 schema" items={params} empty="未声明参数" />
        <RuleSpecContractList label="运行资源" items={resources} empty="未声明 threads/resources/log" />
      </div>
    </div>
  );
}

function RuleSpecContractRow({
  label,
  monospace = false,
  value,
}: {
  label: string;
  monospace?: boolean;
  value: string;
}) {
  return (
    <div className="grid gap-1 rounded-md bg-slate-50 px-2 py-1.5">
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      <div className={cn("truncate text-[11px] text-slate-700", monospace && "font-mono")}>{value}</div>
    </div>
  );
}

function RuleSpecContractList({ empty, items, label }: { empty: string; items: string[]; label: string }) {
  return (
    <div className="grid gap-1 rounded-md bg-slate-50 px-2 py-1.5">
      <div className="text-[11px] font-medium text-slate-500">{label}</div>
      {items.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <span key={`${label}-${item}`} className="max-w-full truncate rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
              {item}
            </span>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-slate-400">{empty}</div>
      )}
    </div>
  );
}

function ruleSpecActionText(template: Record<string, unknown>) {
  const wrapper = stringValue(template.wrapper);
  if (wrapper) return `wrapper: ${wrapper}`;
  const script = stringValue(template.script);
  if (script) return `script: ${script}`;
  const command = stringValue(template.commandTemplate);
  if (command) return command;
  return "";
}

function ruleSpecEnvironmentItems(template: Record<string, unknown>) {
  const environment = recordValue(template.environment);
  const conda = recordValue(environment.conda);
  const channels = stringArray(conda.channels);
  const dependencies = stringArray(conda.dependencies);
  const container = typeof environment.container === "string"
    ? environment.container.trim()
    : stringValue(recordValue(environment.container).url) || stringValue(recordValue(environment.container).image);
  return [
    channels.length > 0 ? `channels:${channels.join(",")}` : "",
    ...dependencies.slice(0, 5),
    dependencies.length > 5 ? `+${dependencies.length - 5} deps` : "",
    container ? `container:${container}` : "",
  ].filter(Boolean);
}

function ruleSpecParamItems(template: Record<string, unknown>) {
  const params = recordValue(template.params);
  return Object.entries(params).map(([name, raw]) => {
    const spec = recordValue(raw);
    const type = stringValue(spec.type) || scalarType(raw);
    const defaultValue = spec.default !== undefined ? spec.default : scalarValue(raw);
    const defaultText = defaultValue !== undefined ? `=${String(defaultValue)}` : "";
    return `${name}${type ? `:${type}` : ""}${defaultText}`;
  });
}

function ruleSpecResourceItems(template: Record<string, unknown>) {
  const resources = recordValue(template.resources);
  const resourceItems = Object.entries(resources).map(([name, raw]) => {
    const spec = recordValue(raw);
    const defaultValue = spec.default !== undefined ? spec.default : raw;
    const defaultText = defaultValue !== undefined && typeof defaultValue !== "object" ? `=${String(defaultValue)}` : "";
    return `${name}${defaultText}`;
  });
  const log = template.log;
  return [
    ...resourceItems,
    typeof log === "string" && log.trim() ? `log:${log.trim()}` : "",
    log && typeof log === "object" && !Array.isArray(log) ? `log:${Object.keys(log).join(",")}` : "",
  ].filter(Boolean);
}

function stringArray(raw: unknown) {
  return Array.isArray(raw) ? raw.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function scalarType(raw: unknown) {
  return typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean" ? typeof raw : "";
}

function scalarValue(raw: unknown) {
  return typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean" ? raw : undefined;
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
    <aside className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm shadow-slate-200/40 min-[820px]:sticky min-[820px]:top-4 min-[820px]:self-start">
      <h2 className="text-sm font-medium text-slate-900">工具预览</h2>
      {selected ? (
        <div className="mt-4 space-y-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="truncate text-base font-semibold text-slate-950">{selected.name}</h3>
              <SourceBadge source={selected.source} label={selected.sourceLabel} />
              <PlatformBadge item={selected} />
              <WrapperBadge item={selected} />
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">{selected.summary || "Conda package"}</p>
            <RuleNodeSummary item={selected} />
          </div>

          <RulePortPreview item={selected} />
          <RuleSpecContractPreview item={selected} />
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

          <SnakemakeWrapperPreview selected={selected} onOpenSourceUrl={onOpenSourceUrl} />
          <RuleSpecDraftPreview draft={selected.ruleSpecDraft} />

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
            <p className="text-[11px] leading-4 text-slate-400">选择版本会锁定节点运行环境，选择不锁版本则只记录包名。</p>
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
            {selectedAlreadyAdded ? "已加入" : "加入工具"}
          </Button>
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-400">选择一个搜索结果</p>
      )}
    </aside>
  );
}
