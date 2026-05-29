import type { AddedTool } from "./tools-page-model";
import {
  readRuleInputs,
  readRuleOutputs,
  readRuleParams,
  readToolRuleTemplate,
  type GeneratedWorkflowGraphDraft,
  type GeneratedWorkflowGraphNode,
  type GeneratedWorkflowStepRuntime,
  type RuleInputSpec,
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

export function GeneratedWorkflowGraphSnakefilePreview({
  draft,
  tools,
}: {
  draft: GeneratedWorkflowGraphDraft;
  tools: AddedTool[];
}) {
  const lines = graphPreviewLines({ draft, tools });
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-3">
      <div className="mb-2 text-[11px] font-semibold uppercase text-slate-400">Workflow Snakefile preview</div>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded border border-slate-100 bg-slate-950 px-3 py-2 font-mono text-[11px] leading-5 text-slate-100">
        {lines.join("\n")}
      </pre>
    </div>
  );
}

function graphPreviewLines({ draft, tools }: { draft: GeneratedWorkflowGraphDraft; tools: AddedTool[] }): string[] {
  if (draft.nodes.length === 0) return ["# Add RuleSpec nodes to preview a Snakefile."];
  const toolById = new Map(tools.map((tool) => [tool.id, tool]));
  const outputPaths = outputPathMap(draft, toolById);
  const targets = exposedTargetPaths(draft, toolById, outputPaths);
  const lines = ['configfile: "run-config.json"', "", "rule all:", "    input:"];
  lines.push(...targets.map((target) => `        ${JSON.stringify(target)},`));
  for (const node of draft.nodes) {
    const tool = toolById.get(node.toolId);
    lines.push(
      "",
      ...rulePreviewLines({
        node,
        tool,
        inputPath: (input, index) => inputPathForRulePort(draft, outputPaths, node, input, index),
        outputPath: (output, index) => outputPathForRulePort(draft, node, output, index),
      })
    );
  }
  return lines;
}

function rulePreviewLines({
  inputPath,
  node,
  outputPath,
  tool,
}: {
  inputPath?: (input: RuleInputSpec, index: number) => string;
  node: GeneratedWorkflowGraphNode;
  outputPath?: (output: RuleOutputSpec, index: number) => string;
  tool: AddedTool | undefined;
}): string[] {
  const template = readToolRuleTemplate(tool);
  const inputs = readRuleInputs(tool);
  const outputs = readRuleOutputs(tool);
  const params = readRuleParams(tool);
  const commandTemplate = stringValue(template.commandTemplate);
  const wrapper = stringValue(template.wrapper);
  const script = stringValue(template.script);
  const moduleSpec = objectValue(template.module);
  const moduleRule = stringValue(moduleSpec.rule);
  const moduleSnakefile = stringValue(moduleSpec.snakefile);
  const ruleName = safeSnakemakeName(node.id);
  const moduleName = safeSnakemakeName(`${node.id}_module`);
  const lines = moduleRule && moduleSnakefile
    ? [
        `module ${moduleName}:`,
        "    snakefile:",
        `        ${JSON.stringify(moduleSnakefile)}`,
        "",
        `use rule ${moduleRule} from ${moduleName} as ${ruleName} with:`,
      ]
    : [`rule ${ruleName}:`];
  lines.push("    input:");
  lines.push(
    ...inputs.map((input, index) => `        ${safeSnakemakeName(input.name)}=${JSON.stringify(inputPath?.(input, index) || input.name)},`)
  );
  lines.push("    output:");
  lines.push(
    ...outputs.map((output, index) => `        ${safeSnakemakeName(output.name)}=${renderOutputValue(output, index, outputPath?.(output, index))},`)
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
  if (moduleRule && moduleSnakefile) {
    return lines;
  }
  if (wrapper) {
    lines.push("    wrapper:");
    lines.push(`        ${JSON.stringify(wrapper)}`);
    return lines;
  }
  if (hasRunnableCondaEnvironment(template, tool)) {
    lines.push("    conda:");
    lines.push(`        ${JSON.stringify(`envs/${safeSnakemakeName(node.id)}.yaml`)}`);
  }
  if (script) {
    lines.push("    script:");
    lines.push(`        ${JSON.stringify(script)}`);
    return lines;
  }
  lines.push("    shell:");
  lines.push("        r\"\"\"");
  lines.push(`        ${commandTemplate || "# commandTemplate required"}`);
  lines.push("        \"\"\"");
  return lines;
}

function renderOutputValue(output: RuleOutputSpec, index: number, pathOverride = "") {
  let rendered = JSON.stringify(pathOverride || output.path || `${output.name || `output_${index + 1}`}.dat`);
  if (output.directory === true) rendered = `directory(${rendered})`;
  if (output.protected === true) rendered = `protected(${rendered})`;
  if (output.temp === true) rendered = `temp(${rendered})`;
  return rendered;
}

function inputPathForRulePort(
  draft: GeneratedWorkflowGraphDraft,
  outputPaths: Map<string, string>,
  node: GeneratedWorkflowGraphNode,
  input: RuleInputSpec,
  index: number
) {
  const edge = draft.edges.find((item) => item.to.nodeId === node.id && item.to.port === input.name);
  if (edge) return outputPaths.get(portKey(edge.from.nodeId, edge.from.port)) || `results/${edge.from.nodeId}/${edge.from.port}`;
  const binding = node.inputs[input.name];
  if (typeof binding === "string") return binding || `inputs/${input.name || index + 1}`;
  if (binding && "fromUpload" in binding) return `inputs/upload_${binding.fromUpload + 1}`;
  if (binding && "fromInput" in binding) return `inputs/${binding.fromInput}`;
  return `inputs/${input.name || index + 1}`;
}

function outputPathMap(draft: GeneratedWorkflowGraphDraft, toolById: Map<string, AddedTool>) {
  const outputPaths = new Map<string, string>();
  for (const node of draft.nodes) {
    for (const [index, output] of readRuleOutputs(toolById.get(node.toolId)).entries()) {
      outputPaths.set(portKey(node.id, output.name), outputPathForRulePort(draft, node, output, index));
    }
  }
  return outputPaths;
}

function outputPathForRulePort(draft: GeneratedWorkflowGraphDraft, node: GeneratedWorkflowGraphNode, output: RuleOutputSpec, index: number) {
  const rawPath = output.path || `${output.name || `output_${index + 1}`}.dat`;
  if (draft.nodes.length <= 1) return rawPath;
  const parts = rawPath.replace(/\\/g, "/").split("/");
  const filename = parts.pop() || rawPath;
  return [...parts, `${safeSnakemakeName(node.id)}-${filename}`].filter(Boolean).join("/");
}

function exposedTargetPaths(
  draft: GeneratedWorkflowGraphDraft,
  toolById: Map<string, AddedTool>,
  outputPaths: Map<string, string>
) {
  if (draft.exposeOutputs.length > 0) {
    return draft.exposeOutputs.map((output) => outputPaths.get(portKey(output.fromStep, output.output)) || output.output);
  }
  const consumed = new Set(draft.edges.map((edge) => portKey(edge.from.nodeId, edge.from.port)));
  const leafTargets = draft.nodes.flatMap((node) =>
    readRuleOutputs(toolById.get(node.toolId))
      .map((output) => ({ output, path: outputPaths.get(portKey(node.id, output.name)) || output.name }))
      .filter(({ output }) => !consumed.has(portKey(node.id, output.name)))
      .map(({ path }) => path)
  );
  return leafTargets.length > 0 ? leafTargets : Array.from(outputPaths.values()).slice(-1);
}

function portKey(nodeId: string, port: string) {
  return `${nodeId}.${port}`;
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

function hasRunnableCondaEnvironment(template: Record<string, unknown>, tool: AddedTool | undefined) {
  const conda = objectValue(objectValue(template.environment).conda);
  return Object.keys(conda).length > 0 || Boolean(tool?.selectedPackageSpec || tool?.packageSpec);
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
