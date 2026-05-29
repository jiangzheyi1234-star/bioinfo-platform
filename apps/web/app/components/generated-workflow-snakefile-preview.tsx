import type { AddedTool } from "./tools-page-model";
import {
  readRuleInputs,
  readRuleOutputs,
  readRuleParams,
  readToolRuleTemplate,
  type GeneratedWorkflowGraphNode,
  type GeneratedWorkflowStepRuntime,
  type RuleOutputSpec,
} from "./generated-workflow-model";

type RuntimeScalar = string | number;

export function GeneratedWorkflowSnakefilePreview({
  node,
  tool,
}: {
  node: GeneratedWorkflowGraphNode;
  tool: AddedTool | undefined;
}) {
  const lines = rulePreviewLines({ node, tool });
  return (
    <div className="rounded-md bg-white px-3 py-2">
      <div className="mb-2 text-[11px] font-semibold uppercase text-slate-400">Snakefile preview</div>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded border border-slate-100 bg-slate-950 px-3 py-2 font-mono text-[11px] leading-5 text-slate-100">
        {lines.join("\n")}
      </pre>
    </div>
  );
}

function rulePreviewLines({ node, tool }: { node: GeneratedWorkflowGraphNode; tool: AddedTool | undefined }): string[] {
  const template = readToolRuleTemplate(tool);
  const inputs = readRuleInputs(tool);
  const outputs = readRuleOutputs(tool);
  const params = readRuleParams(tool);
  const commandTemplate = stringValue(template.commandTemplate);
  const wrapper = stringValue(template.wrapper);
  const lines = [`rule ${safeSnakemakeName(node.id)}:`];
  lines.push("    input:");
  lines.push(
    ...inputs.map((input, index) => `        ${safeSnakemakeName(input.name)}=${quotePreviewPath(input.name, "input", index)},`)
  );
  lines.push("    output:");
  lines.push(
    ...outputs.map((output, index) => `        ${safeSnakemakeName(output.name)}=${renderOutputValue(output, index)},`)
  );
  const paramLines = params.map(
    (param) => `        ${safeSnakemakeName(param.name)}=${JSON.stringify(node.params[param.name] ?? param.default ?? "")},`
  );
  if (paramLines.length > 0) {
    lines.push("    params:");
    lines.push(...paramLines);
  }
  const runtime = runtimePreviewItems(template, node.runtime);
  if (runtime.threads !== undefined) {
    lines.push(`    threads: ${runtime.threads}`);
  }
  if (Object.keys(runtime.resources).length > 0) {
    lines.push("    resources:");
    lines.push(
      ...Object.entries(runtime.resources).map(([name, value]) => `        ${safeSnakemakeName(name)}=${JSON.stringify(value)},`)
    );
  }
  if (Object.keys(runtime.log).length > 0) {
    lines.push("    log:");
    lines.push(
      ...Object.entries(runtime.log).map(([name, value]) => `        ${safeSnakemakeName(name)}=${JSON.stringify(value)},`)
    );
  }
  if (wrapper) {
    lines.push("    wrapper:");
    lines.push(`        ${JSON.stringify(wrapper)}`);
    return lines;
  }
  if (hasCondaEnvironment(template)) {
    lines.push("    conda:");
    lines.push(`        ${JSON.stringify(`envs/${safeSnakemakeName(node.id)}.yaml`)}`);
  }
  lines.push("    shell:");
  lines.push("        r\"\"\"");
  lines.push(`        ${commandTemplate || "# commandTemplate required"}`);
  lines.push("        \"\"\"");
  return lines;
}

function renderOutputValue(output: RuleOutputSpec, index: number) {
  let rendered = quotePreviewPath(output.path || `${output.name || `output_${index + 1}`}.dat`, "output", index);
  if (output.directory === true) rendered = `directory(${rendered})`;
  if (output.protected === true) rendered = `protected(${rendered})`;
  if (output.temp === true) rendered = `temp(${rendered})`;
  return rendered;
}

function runtimePreviewItems(template: Record<string, unknown>, runtime: GeneratedWorkflowStepRuntime) {
  const resources = {
    ...defaultResourceItems(template.resources),
    ...defaultResourceItems(template.schedulerResources || template.runtimeResources),
    ...(runtime.resources || runtime.schedulerResources || {}),
  };
  const threads =
    runtime.threads ?? defaultRuntimeValue(template.threads) ?? defaultRuntimeValue(objectValue(template.resources).threads);
  delete resources.threads;
  return {
    threads,
    resources,
    log: normalizeLogPreview(runtime.log || template.log),
  };
}

function defaultResourceItems(raw: unknown): Record<string, RuntimeScalar> {
  return Object.fromEntries(
    Object.entries(objectValue(raw))
      .filter(([, value]) => !hasWorkflowResourceMarkers(value))
      .map(([name, value]) => [name, defaultRuntimeValue(value)] as const)
      .filter((entry): entry is [string, RuntimeScalar] => entry[1] !== undefined)
  );
}

function normalizeLogPreview(raw: unknown): Record<string, string> {
  if (typeof raw === "string") {
    const value = raw.trim();
    return value ? { log: value } : {};
  }
  return Object.fromEntries(
    Object.entries(objectValue(raw))
      .map(([name, value]) => [name.trim(), stringValue(value)] as const)
      .filter(([name, value]) => Boolean(name && value))
  );
}

function quotePreviewPath(value: string, direction: "input" | "output", index: number) {
  const fallback = direction === "input" ? `inputs/${index + 1}.dat` : `results/${index + 1}.dat`;
  return JSON.stringify(value || fallback);
}

function hasCondaEnvironment(template: Record<string, unknown>) {
  const conda = objectValue(objectValue(template.environment).conda);
  return Object.keys(conda).length > 0;
}

function defaultRuntimeValue(raw: unknown): RuntimeScalar | undefined {
  if (typeof raw === "string" || typeof raw === "number") return raw;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const value = (raw as Record<string, unknown>).default ?? (raw as Record<string, unknown>).value;
  return typeof value === "string" || typeof value === "number" ? value : undefined;
}

function hasWorkflowResourceMarkers(raw: unknown): boolean {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return false;
  const item = raw as Record<string, unknown>;
  return Boolean(item.acceptedTemplates || item.acceptedCapabilities || item.configKey);
}

function objectValue(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
}

function stringValue(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
}

function safeSnakemakeName(value: string) {
  const name = value.replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "rule";
  if (/^[0-9]/.test(name) || ["count", "index", "sort"].includes(name)) return `tool_${name}`;
  return name;
}
