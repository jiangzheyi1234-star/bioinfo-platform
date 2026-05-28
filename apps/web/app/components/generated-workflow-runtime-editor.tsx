import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import type { AddedTool } from "./tools-page-model";
import type { GeneratedWorkflowStepRuntime } from "./generated-workflow-model";

type RuntimeScalar = string | number;

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
