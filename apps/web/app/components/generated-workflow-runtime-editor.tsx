import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import type { AddedTool } from "./tools-page-model";
import type { GeneratedWorkflowStepRuntime } from "./generated-workflow-model";

type RuntimeScalar = string | number;
type RuntimeLogEntry = {
  key: string;
  label: string;
  mode: "single" | "named";
  value: string;
  defaultValue: string;
};

export function GeneratedWorkflowRuntimeEditor({
  runtime,
  tool,
  onChange,
}: {
  runtime: GeneratedWorkflowStepRuntime;
  tool: AddedTool | undefined;
  onChange: (runtime: GeneratedWorkflowStepRuntime) => void;
}) {
  const template = (tool?.ruleTemplate || {}) as Record<string, unknown>;
  const defaultThreads = defaultRuntimeValue(template.threads);
  const defaultResources = schedulerResourceDefaults(template.schedulerResources || template.runtimeResources);
  const runtimeResources = runtime.resources || runtime.schedulerResources || {};
  const resourceKeys = uniqueKeys([...Object.keys(defaultResources), ...Object.keys(runtimeResources)]);
  const defaultLogs = logDefaults(template.log);
  const logEntries = namedLogEntries(runtime.log, defaultLogs);

  return (
    <div className="rounded-md bg-white px-3 py-2">
      <div className="mb-2 text-[11px] font-semibold uppercase text-slate-400">运行资源</div>
      <div className="grid gap-2">
        <div>
          <Label className="text-[11px] text-slate-500" htmlFor="generated-runtime-threads">
            线程
          </Label>
          <Input
            id="generated-runtime-threads"
            inputMode="numeric"
            min={1}
            placeholder={defaultThreads === undefined ? "默认" : `默认 ${defaultThreads}`}
            value={runtime.threads ?? ""}
            onChange={(event) => onChange(updateThreads(runtime, event.target.value))}
            className="mt-1 h-8 font-mono text-xs"
          />
        </div>
        <div className="grid gap-1.5">
          <div className="text-[11px] font-semibold uppercase text-slate-400">调度资源</div>
          {resourceKeys.length === 0 ? (
            <div className="rounded border border-dashed border-slate-200 px-2 py-1.5 text-[11px] text-slate-400">
              未声明 scheduler resources
            </div>
          ) : resourceKeys.map((key) => (
            <div key={key} className="grid grid-cols-[80px_minmax(0,1fr)] items-center gap-2">
              <Label className="truncate font-mono text-[11px] text-slate-500" htmlFor={`generated-runtime-${key}`}>
                {key}
              </Label>
              <Input
                id={`generated-runtime-${key}`}
                placeholder={defaultResources[key] === undefined ? "默认" : `默认 ${defaultResources[key]}`}
                value={runtimeResources[key] ?? ""}
                onChange={(event) => onChange(updateResource(runtime, key, event.target.value))}
                className="h-8 font-mono text-xs"
              />
            </div>
          ))}
        </div>
        <div className="grid gap-1.5">
          <div className="text-[11px] font-semibold uppercase text-slate-400">日志</div>
          {logEntries.length === 0 ? (
            <div className="rounded border border-dashed border-slate-200 px-2 py-1.5 text-[11px] text-slate-400">
              未声明 log
            </div>
          ) : logEntries.map((entry) => (
            <div key={entry.key} className="grid grid-cols-[80px_minmax(0,1fr)] items-center gap-2">
              <Label
                className="truncate font-mono text-[11px] text-slate-500"
                htmlFor={`generated-runtime-log-${entry.key}`}
              >
                {entry.label}
              </Label>
              <Input
                id={`generated-runtime-log-${entry.key}`}
                placeholder={entry.defaultValue ? `默认 ${entry.defaultValue}` : "默认"}
                value={entry.value}
                onChange={(event) =>
                  onChange(
                    entry.mode === "single"
                      ? updateLog(runtime, event.target.value)
                      : updateLogPath(runtime, entry.key, event.target.value, entry.mode)
                  )
                }
                className="h-8 font-mono text-xs"
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function updateThreads(runtime: GeneratedWorkflowStepRuntime, raw: string): GeneratedWorkflowStepRuntime {
  const value = raw.trim();
  const next = { ...runtime };
  if (!value) {
    delete next.threads;
    return next;
  }
  const parsed = Number(value);
  if (Number.isInteger(parsed) && parsed > 0) {
    next.threads = parsed;
  }
  return next;
}

function updateResource(runtime: GeneratedWorkflowStepRuntime, key: string, raw: string): GeneratedWorkflowStepRuntime {
  const value = raw.trim();
  const resources = { ...(runtime.resources || runtime.schedulerResources || {}) };
  if (!value) {
    delete resources[key];
  } else {
    resources[key] = parseRuntimeScalar(value);
  }
  const next: GeneratedWorkflowStepRuntime = { ...runtime, resources };
  delete next.schedulerResources;
  if (Object.keys(resources).length === 0) delete next.resources;
  return next;
}

function updateLog(runtime: GeneratedWorkflowStepRuntime, raw: string): GeneratedWorkflowStepRuntime {
  return updateLogPath(runtime, "log", raw, "single");
}

function updateLogPath(
  runtime: GeneratedWorkflowStepRuntime,
  key: string,
  raw: string,
  mode: RuntimeLogEntry["mode"]
): GeneratedWorkflowStepRuntime {
  const value = raw.trim();
  const next = { ...runtime };
  if (mode === "single") {
    if (value) {
      next.log = value;
    } else {
      delete next.log;
    }
    return next;
  }
  const logs = runtime.log && typeof runtime.log === "object" && !Array.isArray(runtime.log) ? { ...runtime.log } : {};
  if (value) {
    logs[key] = value;
  } else {
    delete logs[key];
  }
  if (Object.keys(logs).length > 0) {
    next.log = logs;
  } else {
    delete next.log;
  }
  return next;
}

function namedLogEntries(
  runtimeLog: GeneratedWorkflowStepRuntime["log"],
  defaults: ReturnType<typeof logDefaults>
): RuntimeLogEntry[] {
  if (defaults.mode === "single" || typeof runtimeLog === "string") {
    return [
      {
        key: "log",
        label: "log",
        mode: "single",
        value: typeof runtimeLog === "string" ? runtimeLog : "",
        defaultValue: defaults.entries.log || "",
      },
    ];
  }
  const runtimeLogs = runtimeLog && typeof runtimeLog === "object" && !Array.isArray(runtimeLog) ? runtimeLog : {};
  return uniqueKeys([...Object.keys(defaults.entries), ...Object.keys(runtimeLogs)]).map((key) => ({
    key,
    label: key,
    mode: "named",
    value: runtimeLogs[key] || "",
    defaultValue: defaults.entries[key] || "",
  }));
}

function logDefaults(raw: unknown): { mode: "none" | "single" | "named"; entries: Record<string, string> } {
  if (typeof raw === "string") {
    const value = raw.trim();
    return value ? { mode: "single", entries: { log: value } } : { mode: "none", entries: {} };
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { mode: "none", entries: {} };
  }
  const entries = Object.fromEntries(
    Object.entries(raw as Record<string, unknown>)
      .map(([key, value]) => [key.trim(), typeof value === "string" ? value.trim() : ""] as const)
      .filter(([key, value]) => Boolean(key && value))
  );
  return Object.keys(entries).length > 0 ? { mode: "named", entries } : { mode: "none", entries: {} };
}

function parseRuntimeScalar(value: string): RuntimeScalar {
  const numeric = Number(value);
  return Number.isFinite(numeric) && String(numeric) === value ? numeric : value;
}

function schedulerResourceDefaults(raw: unknown): Record<string, RuntimeScalar> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>)
      .map(([key, value]) => [key, defaultRuntimeValue(value)] as const)
      .filter((entry): entry is [string, RuntimeScalar] => entry[1] !== undefined)
  );
}

function defaultRuntimeValue(raw: unknown): RuntimeScalar | undefined {
  if (typeof raw === "string" || typeof raw === "number") return raw;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const value = (raw as Record<string, unknown>).default ?? (raw as Record<string, unknown>).value;
  return typeof value === "string" || typeof value === "number" ? value : undefined;
}

function uniqueKeys(keys: string[]) {
  return [...new Set(keys.map((key) => key.trim()).filter(Boolean))];
}
