import type { RuleSpecEnvironment, RuleSpecPort, RuleSpecTemplate, SnakemakeWrapperMatch, ToolSearchItem } from "./tools-page-model";

export function applySelectedWrapperLock<T extends ToolSearchItem>(tool: T, selectedWrapperPath: string): T {
  if (tool.ruleSpecDraft?.source === "h2ometa-tool-profile" && tool.ruleSpecDraft.requiresUserCompletion === false) {
    return tool;
  }
  const wrapper = selectedSnakemakeWrapper(tool, selectedWrapperPath);
  if (!wrapper) {
    return tool;
  }
  const wrapperIdentifier = wrapper.wrapperIdentifier || [wrapper.wrapperRef, wrapper.wrapperPath].filter(Boolean).join("/");
  const draft = wrapper.ruleSpecDraft || tool.ruleSpecDraft || {
    source: "snakemake-wrapper",
    ruleTemplate: { wrapper: wrapperIdentifier },
  };
  const lock = {
    ...(draft.lock || {}),
    type: "snakemake-wrapper",
    wrapperRepository: wrapper.wrapperRepository,
    wrapperRef: wrapper.wrapperRef,
    wrapperPath: wrapper.wrapperPath,
    wrapperIdentifier,
  };
  return {
    ...tool,
    ruleSpecDraft: {
      ...draft,
      source: "snakemake-wrapper",
      lock,
      ruleTemplate: {
        ...(draft.ruleTemplate || {}),
        source: "snakemake-wrapper",
        wrapper: wrapperIdentifier,
      },
    },
  };
}

export function buildExecutableRuleSpecForSelectedTool<T extends ToolSearchItem>(
  tool: T,
  options: { outputPath?: string; selectedPackageSpec?: string; selectedVersion?: string } = {}
): T {
  const packageSpec = (
    options.selectedPackageSpec ||
    ("selectedPackageSpec" in tool ? String(tool.selectedPackageSpec || "") : "") ||
    tool.packageSpec ||
    ""
  ).trim();
  const selectedVersion = (options.selectedVersion || tool.version || "").trim();
  const template = executableRuleTemplateForTool(tool, {
    outputPath: options.outputPath,
    outputPathSpecified: Object.prototype.hasOwnProperty.call(options, "outputPath"),
    packageSpec,
  });
  const requiresUserCompletion = Boolean(tool.ruleSpecDraft?.requiresUserCompletion) && !canAutoConfirmRuleSpec(tool.ruleSpecDraft, template);
  const draft = tool.ruleSpecDraft
    ? {
        ...tool.ruleSpecDraft,
        status: requiresUserCompletion ? tool.ruleSpecDraft.status || "needs-user-completion" : "ready-for-validation",
        requiresUserCompletion,
        lock: {
          ...(tool.ruleSpecDraft.lock || {}),
          packageSpec,
          version: selectedVersion,
        },
        ruleTemplate: template,
      }
    : undefined;
  return {
    ...tool,
    version: selectedVersion || tool.version,
    packageSpec: packageSpec || tool.packageSpec,
    ruleTemplate: requiresUserCompletion ? tool.ruleTemplate : template,
    ruleSpecDraft: draft,
  };
}

export function isExecutableRuleSpec(tool: ToolSearchItem | RuleSpecTemplate | undefined): boolean {
  return missingRuleSpecFields(tool).length === 0;
}

export function missingRuleSpecFields(tool: ToolSearchItem | RuleSpecTemplate | undefined): string[] {
  const template = ruleTemplateFromToolOrTemplate(tool);
  const toolItem = isToolSearchItem(tool) ? tool : undefined;
  const missing: string[] = [];
  const packageSpec = toolItem ? String(toolItem.packageSpec || "").trim() : "";
  if (toolItem?.targetPlatformSupported === false) missing.push("目标平台不支持");
  if (toolItem && !packageSpecLocked(packageSpec)) missing.push("未锁定 conda 包版本");
  if (toolItem?.ruleSpecDraft?.requiresUserCompletion === true) missing.push("RuleSpec 需要补全并确认");

  const actions = ruleActionEntries(template, { requireWrapperLock: false });
  const readyActions = ruleActionEntries(template);
  if (actions.length === 0) missing.push("缺少执行动作");
  if (actions.length > 1) missing.push("执行动作冲突");
  if (actions[0] === "wrapper" && readyActions.length === 0) missing.push("wrapper ref 不能使用 latest/master");

  const inputs = Array.isArray(template.inputs) ? template.inputs : [];
  if (inputs.length === 0) missing.push("缺少输入端口");
  if (inputs.some((input) => !stringValue(input.name))) missing.push("input 缺少 name");

  const outputs = Array.isArray(template.outputs) ? template.outputs : [];
  if (outputs.length === 0) missing.push("缺少输出端口");
  if (outputs.some((output) => !stringValue(output.name))) missing.push("output 缺少 name");
  if (outputs.some((output) => !stringValue(output.path))) missing.push("缺少输出文件路径");

  if (!isRecord(template.params)) missing.push("params 必须至少是空对象 {}");
  if (!ruleRuntimeReady(template)) missing.push("runtime/log 未配置");
  if (!environmentLocked(template, packageSpec)) missing.push("environment 未锁定到明确包版本");

  const smokeMissing = missingSmokeInputs(template);
  if (smokeMissing.length > 0) {
    missing.push(smokeMissing.length === 1 ? "smoke test 输入未配置" : `smoke test 输入未配置: ${smokeMissing.join(", ")}`);
  }
  return Array.from(new Set(missing));
}

export function defaultRuleSpecOutputPath(tool: ToolSearchItem | undefined, selectedWrapperPath = "") {
  if (!tool) return "";
  const template = ruleTemplateFromToolOrTemplate(applySelectedWrapperLock(tool, selectedWrapperPath));
  const firstOutput = Array.isArray(template.outputs) ? template.outputs[0] : undefined;
  const path = stringValue(firstOutput?.path);
  if (path) return path;
  return defaultOutputPathForTool(tool, selectedWrapperPath);
}

function executableRuleTemplateForTool(
  tool: ToolSearchItem,
  options: { outputPath?: string; outputPathSpecified?: boolean; packageSpec: string }
): RuleSpecTemplate {
  const template = { ...ruleTemplateFromToolOrTemplate(tool) };
  const inputSpecs = normalizeRuleInputs(template.inputs);
  const outputSpecs = normalizeRuleOutputs(template.outputs, tool, {
    outputPath: options.outputPath,
    outputPathSpecified: options.outputPathSpecified === true,
  });
  const resources = {
    ...objectValue(template.resources),
    threads: objectValue(template.resources).threads || { default: template.threads || 1 },
    mem_mb: objectValue(template.resources).mem_mb || { default: 512 },
  };
  return {
    ...template,
    inputs: inputSpecs,
    outputs: outputSpecs,
    params: isRecord(template.params) ? template.params : {},
    resources,
    log: template.log || `logs/${safeSlug(tool.name || "tool")}.log`,
    environment: executableEnvironment(template, tool, options.packageSpec),
    smokeTest: executableSmokeTest(template, inputSpecs),
  };
}

function selectedSnakemakeWrapper(tool: ToolSearchItem, selectedWrapperPath: string): SnakemakeWrapperMatch | undefined {
  const wrappers = tool.snakemakeWrappers || [];
  return wrappers.find((wrapper) => wrapper.wrapperPath === selectedWrapperPath) || wrappers[0];
}

function normalizeRuleInputs(raw: RuleSpecTemplate["inputs"]): RuleSpecPort[] {
  const inputs = Array.isArray(raw) && raw.length > 0 ? raw : [defaultInputForTool()];
  return inputs.map((input, index) => ({
    ...input,
    name: stringValue(input.name) || (index === 0 ? "primary" : `input_${index + 1}`),
    type: stringValue(input.type) || "file",
    required: input.required !== false,
  }));
}

function normalizeRuleOutputs(
  raw: RuleSpecTemplate["outputs"],
  tool: ToolSearchItem,
  options: { outputPath?: string; outputPathSpecified: boolean }
): RuleSpecPort[] {
  const outputs = Array.isArray(raw) && raw.length > 0 ? raw : [defaultOutputForTool(tool)];
  return outputs.map((output, index) => {
    const fallback = defaultOutputForTool(tool);
    const firstOutputPath = options.outputPathSpecified ? stringValue(options.outputPath) : stringValue(output.path) || fallback.path;
    return {
      ...output,
      name: stringValue(output.name) || (index === 0 ? fallback.name : `output_${index + 1}`),
      path: index === 0 ? firstOutputPath : stringValue(output.path) || fallback.path,
      ...(stringValue(output.kind) || stringValue(fallback.kind) ? { kind: stringValue(output.kind) || fallback.kind } : {}),
      ...(stringValue(output.mimeType) || stringValue(fallback.mimeType) ? { mimeType: stringValue(output.mimeType) || fallback.mimeType } : {}),
    };
  });
}

function canAutoConfirmRuleSpec(draft: ToolSearchItem["ruleSpecDraft"], _template: RuleSpecTemplate) {
  return !draft?.requiresUserCompletion;
}

function executableEnvironment(template: RuleSpecTemplate, tool: ToolSearchItem, packageSpec: string): RuleSpecEnvironment {
  const current = template.environment || {};
  const conda = current.conda || {};
  const dependencies = replaceSelectedToolDependency(conda.dependencies || [], tool, packageSpec);
  return {
    ...current,
    conda: {
      channels: conda.channels && conda.channels.length > 0 ? conda.channels : uniqueChannels(tool.source),
      dependencies,
    },
  };
}

function replaceSelectedToolDependency(dependencies: string[], tool: ToolSearchItem, packageSpec: string) {
  const selected = stringValue(packageSpec);
  if (!selected) return dependencies;
  if (dependencies.length === 0) return [selected];
  const selectedName = packageName(selected) || stringValue(tool.name);
  let replaced = false;
  const next = dependencies.map((dependency) => {
    if (packageName(dependency) !== selectedName) return dependency;
    replaced = true;
    return selected;
  });
  return replaced ? next : [...next, selected];
}

function executableSmokeTest(template: RuleSpecTemplate, inputs: RuleSpecPort[]): RuleSpecTemplate["smokeTest"] {
  const current = template.smokeTest || {};
  const smokeInputs = objectValue(current.inputs);
  const nextInputs: NonNullable<RuleSpecTemplate["smokeTest"]>["inputs"] = {};
  for (const input of inputs.filter((item) => item.required !== false)) {
    const name = stringValue(input.name);
    const existing = objectValue(smokeInputs[name]);
    nextInputs[name] = smokeInputReady(existing) ? existing : defaultSmokeFixture(input);
  }
  return { ...current, inputs: nextInputs };
}

function defaultInputForTool(): RuleSpecPort {
  return { name: "primary", type: "file", required: true };
}

function defaultOutputForTool(tool: ToolSearchItem): RuleSpecPort {
  return { name: "output", path: defaultOutputPathForTool(tool), type: "file" };
}

function defaultOutputPathForTool(tool: ToolSearchItem, selectedWrapperPath = "") {
  const wrapperPath = selectedWrapperPath || selectedSnakemakeWrapper(tool, selectedWrapperPath)?.wrapperPath || "";
  const slug = safeSlug([tool.name, wrapperPath.split("/").at(-1)].filter(Boolean).join("-"));
  return `results/${slug}.out`;
}

function defaultSmokeFixture(input: RuleSpecPort) {
  const name = stringValue(input.name) || "input";
  const kind = stringValue(input.kind).toLowerCase();
  const mimeType = stringValue(input.mimeType).toLowerCase();
  if (kind.includes("sequence") || mimeType.includes("fastq")) {
    return { filename: `${name}.fastq`, content: "@smoke\nACGT\n+\nFFFF\n", mimeType: "text/plain" };
  }
  return { filename: `${name}.txt`, content: "smoke\n", mimeType: input.mimeType || "text/plain" };
}

function ruleTemplateFromToolOrTemplate(raw: ToolSearchItem | RuleSpecTemplate | undefined): RuleSpecTemplate {
  if (!raw) return {};
  if (!isToolSearchItem(raw)) return raw;
  const manifest = objectValue(raw.ruleTemplate) as RuleSpecTemplate;
  const draftTemplate = objectValue(raw.ruleSpecDraft?.ruleTemplate) as RuleSpecTemplate;
  return hasRuleTemplateShape(manifest) ? manifest : draftTemplate;
}

function isToolSearchItem(raw: unknown): raw is ToolSearchItem {
  return isRecord(raw) && ("packageSpec" in raw || "ruleSpecDraft" in raw || "snakemakeWrappers" in raw);
}

function hasRuleTemplateShape(template: RuleSpecTemplate) {
  return Boolean(
    ruleActionEntries(template, { requireWrapperLock: false }).length > 0 ||
      Array.isArray(template.inputs) ||
      Array.isArray(template.outputs) ||
      isRecord(template.params)
  );
}

function ruleActionEntries(template: RuleSpecTemplate, options: { requireWrapperLock?: boolean } = { requireWrapperLock: true }) {
  return (["commandTemplate", "wrapper", "script", "module"] as const).filter((field) => {
    if (field === "module") return Boolean(stringValue(template.module?.snakefile) && stringValue(template.module?.rule));
    if (field === "wrapper") {
      const wrapper = stringValue(template.wrapper);
      return Boolean(wrapper && (options.requireWrapperLock === false || wrapperRefLocked(wrapper)));
    }
    return Boolean(stringValue(template[field]));
  });
}

function wrapperRefLocked(raw: unknown) {
  const parts = stringValue(raw).split("/").map((part) => part.trim()).filter(Boolean);
  if (parts.length < 2) return false;
  const ref = parts[0];
  if (["bio", "master", "main", "latest", "head", "dev"].includes(ref.toLowerCase())) return false;
  return /^v?\d+(?:\.\d+){1,}(?:[-+._A-Za-z0-9]*)?$/.test(ref) || /^[0-9a-fA-F]{7,40}$/.test(ref);
}

function ruleRuntimeReady(template: RuleSpecTemplate) {
  const resources = objectValue(template.resources);
  const hasThreads = positiveInt(template.threads) || positiveInt(resourceDefault(resources.threads));
  return hasThreads && schedulerResourcesReady(template) && logReady(template.log);
}

function schedulerResourcesReady(template: RuleSpecTemplate) {
  const resources = { ...objectValue(template.resources), ...objectValue(template.schedulerResources), ...objectValue(template.runtimeResources) };
  return Object.entries(resources).some(([name, value]) => name !== "threads" && schedulerValueReady(value));
}

function schedulerValueReady(raw: unknown): boolean {
  if (typeof raw === "number") return Number.isFinite(raw);
  if (typeof raw === "string") return raw.trim().length > 0;
  const value = objectValue(raw);
  return schedulerValueReady(value.default) || schedulerValueReady(value.value);
}

function environmentLocked(template: RuleSpecTemplate, packageSpec: string) {
  const conda = template.environment?.conda;
  const channels = conda?.channels || [];
  const dependencies = conda?.dependencies || [];
  return channels.length > 0 && channelPriorityStrict(channels) && dependencies.length > 0 && dependencies.every(packageSpecLocked) && (!packageSpec || dependencies.includes(packageSpec));
}

function missingSmokeInputs(template: RuleSpecTemplate) {
  const inputs = Array.isArray(template.inputs) ? template.inputs : [];
  const smokeInputs = objectValue(template.smokeTest?.inputs);
  return inputs
    .filter((input) => input.required !== false)
    .map((input) => stringValue(input.name))
    .filter((name) => !smokeInputReady(smokeInputs[name]));
}

function smokeInputReady(raw: unknown) {
  const input = objectValue(raw);
  return typeof input.content === "string" || stringValue(input.contentBase64).length > 0;
}

function packageSpecLocked(value: string) {
  const spec = String(value || "").trim();
  if (!spec || /[<>*]/.test(spec)) return false;
  const packageName = spec.split("::").at(-1) || "";
  const separator = packageName.includes("==") ? "==" : packageName.includes("=") ? "=" : "";
  if (!separator) return false;
  const [name, version] = packageName.split(separator);
  return Boolean(name.trim() && version.trim());
}

function packageName(value: string) {
  const spec = stringValue(value).split("::").at(-1) || "";
  const separator = spec.includes("==") ? "==" : spec.includes("=") ? "=" : "";
  return (separator ? spec.split(separator)[0] : spec).trim();
}

function resourceDefault(raw: unknown) {
  const value = objectValue(raw);
  return value.default ?? value.value ?? raw;
}

function positiveInt(raw: unknown) {
  return typeof raw === "number" && Number.isInteger(raw) && raw >= 1;
}

function logReady(raw: unknown) {
  if (typeof raw === "string") return raw.trim().length > 0;
  const record = objectValue(raw);
  return Object.keys(record).length > 0 && Object.entries(record).every(([name, path]) => name.trim() && stringValue(path));
}

function channelPriorityStrict(channels: string[]) {
  const condaForgeIndex = channels.indexOf("conda-forge");
  const biocondaIndex = channels.indexOf("bioconda");
  return condaForgeIndex >= 0 && (biocondaIndex < 0 || condaForgeIndex < biocondaIndex);
}

function uniqueChannels(source: string) {
  return Array.from(new Set(["conda-forge", source === "conda-forge" ? "bioconda" : source].filter(Boolean)));
}

function safeSlug(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "") || "tool";
}

function objectValue(raw: unknown): Record<string, unknown> {
  return isRecord(raw) ? raw : {};
}

function isRecord(raw: unknown): raw is Record<string, unknown> {
  return Boolean(raw && typeof raw === "object" && !Array.isArray(raw));
}

function stringValue(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
}
