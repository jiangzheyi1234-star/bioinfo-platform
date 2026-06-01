"use client";

import { useMemo, useState } from "react";
import { Loader2, Save, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import type { AddedTool, RuleSpecParam, RuleSpecScalar, RuleSpecTemplate } from "./tools-page-model";

type ActionKind = "commandTemplate" | "wrapper" | "script" | "module";

type RuleSpecFormState = {
  actionKind: ActionKind;
  actionValue: string;
  moduleSnakefile: string;
  moduleRule: string;
  inputName: string;
  inputType: string;
  inputKind: string;
  outputName: string;
  outputPath: string;
  outputKind: string;
  outputMimeType: string;
  params: string;
  threads: string;
  memMb: string;
  log: string;
  channels: string;
  dependencies: string;
  smokeFilename: string;
  smokeContent: string;
  smokeMimeType: string;
};

export function ToolRuleSpecEditor({
  error,
  saving,
  tool,
  onCancel,
  onSave,
}: {
  error: string;
  saving: boolean;
  tool: AddedTool;
  onCancel: () => void;
  onSave: (ruleTemplate: RuleSpecTemplate) => void;
}) {
  const initialRule = useMemo(() => ruleTemplateForEditor(tool), [tool]);
  const [form, setForm] = useState(() => formStateForTemplate(initialRule));
  const [localError, setLocalError] = useState("");

  function update(key: keyof RuleSpecFormState, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function save() {
    setLocalError("");
    const missing = requiredFields(form).filter((item) => !form[item].trim());
    if (missing.length > 0) {
      setLocalError(`RuleSpec 字段缺失: ${missing.join(", ")}`);
      return;
    }
    onSave(buildRuleTemplate(form, initialRule));
  }

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="text-[11px] font-medium uppercase text-slate-400">RuleSpec 合同确认</div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-500" onClick={onCancel} title="取消">
            <X strokeWidth={1.5} className="h-3.5 w-3.5" />
            <span className="sr-only">取消</span>
          </Button>
          <Button className="h-7 bg-slate-950 px-2.5 text-xs text-white hover:bg-slate-800" disabled={saving} onClick={save}>
            {saving ? <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Save strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />}
            保存 RuleSpec
          </Button>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Section title="Command">
          <label className="grid gap-1 text-xs text-slate-600">
            Action
            <select
              value={form.actionKind}
              onChange={(event) => update("actionKind", event.target.value as ActionKind)}
              className="h-9 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-800 outline-none focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
            >
              <option value="commandTemplate">command</option>
              <option value="wrapper">wrapper</option>
              <option value="script">script</option>
              <option value="module">module</option>
            </select>
          </label>
          {form.actionKind === "module" ? (
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label="Module Snakefile" value={form.moduleSnakefile} onChange={(value) => update("moduleSnakefile", value)} />
              <Field label="Module Rule" value={form.moduleRule} onChange={(value) => update("moduleRule", value)} />
            </div>
          ) : (
            <Field label="Action value" value={form.actionValue} onChange={(value) => update("actionValue", value)} />
          )}
        </Section>

        <Section title="Input">
          <div className="grid gap-2 sm:grid-cols-3">
            <Field label="Name" value={form.inputName} onChange={(value) => update("inputName", value)} />
            <Field label="Type" value={form.inputType} onChange={(value) => update("inputType", value)} />
            <Field label="Kind" value={form.inputKind} onChange={(value) => update("inputKind", value)} />
          </div>
        </Section>

        <Section title="Output">
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Name" value={form.outputName} onChange={(value) => update("outputName", value)} />
            <Field label="Path" value={form.outputPath} onChange={(value) => update("outputPath", value)} />
            <Field label="Kind" value={form.outputKind} onChange={(value) => update("outputKind", value)} />
            <Field label="MIME" value={form.outputMimeType} onChange={(value) => update("outputMimeType", value)} />
          </div>
        </Section>

        <Section title="Params">
          <Field label="Names" value={form.params} onChange={(value) => update("params", value)} />
        </Section>

        <Section title="Runtime">
          <div className="grid gap-2 sm:grid-cols-3">
            <Field label="Threads" value={form.threads} onChange={(value) => update("threads", value)} />
            <Field label="mem_mb" value={form.memMb} onChange={(value) => update("memMb", value)} />
            <Field label="Log" value={form.log} onChange={(value) => update("log", value)} />
          </div>
        </Section>

        <Section title="Environment">
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Channels" value={form.channels} onChange={(value) => update("channels", value)} />
            <Field label="Dependencies" value={form.dependencies} onChange={(value) => update("dependencies", value)} />
          </div>
        </Section>

        <Section title="Smoke">
          <div className="grid gap-2 sm:grid-cols-3">
            <Field label="Filename" value={form.smokeFilename} onChange={(value) => update("smokeFilename", value)} />
            <Field label="Content" value={form.smokeContent} onChange={(value) => update("smokeContent", value)} />
            <Field label="MIME" value={form.smokeMimeType} onChange={(value) => update("smokeMimeType", value)} />
          </div>
        </Section>
      </div>

      {localError || error ? <div className="mt-2 text-xs leading-5 text-red-600">{localError || error}</div> : null}
    </div>
  );
}

function Section({ children, title }: { children: React.ReactNode; title: string }) {
  return (
    <div className="space-y-2 rounded-md border border-slate-200 bg-white p-3">
      <div className="text-[11px] font-semibold uppercase text-slate-500">{title}</div>
      {children}
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="grid gap-1 text-xs text-slate-600">
      {label}
      <Input value={value} onChange={(event) => onChange(event.target.value)} className="h-9 rounded-md text-xs" />
    </label>
  );
}

function ruleTemplateForEditor(tool: AddedTool): RuleSpecTemplate {
  const manifest = objectValue(tool.ruleTemplate);
  const draft = objectValue(tool.ruleSpecDraft?.ruleTemplate);
  if (hasRuleTemplate(manifest)) return manifest as RuleSpecTemplate;
  if (hasRuleTemplate(draft)) return draft as RuleSpecTemplate;
  return starterRuleTemplate(tool);
}

function starterRuleTemplate(tool: AddedTool): RuleSpecTemplate {
  const packageSpec = (tool.selectedPackageSpec || tool.packageSpec || "").trim();
  const name = safeName(tool.name || "tool");
  const template: RuleSpecTemplate = {
    commandTemplate: `${tool.name || "tool"} {input.primary:q} > {output.report:q}`,
    inputs: [{ name: "primary", type: "file", required: true }],
    outputs: [{ name: "report", path: `results/${name}-report.txt`, kind: "report", mimeType: "text/plain" }],
    params: {},
    resources: { threads: { default: 1 }, mem_mb: { default: 512 } },
    log: `logs/${name}.log`,
    smokeTest: {
      inputs: {
        primary: {
          filename: "input.txt",
          content: "smoke\n",
          mimeType: "text/plain",
        },
      },
    },
  };
  if (packageSpec) {
    template.environment = {
      conda: {
        channels: uniqueChannels(tool.source),
        dependencies: [packageSpec],
      },
    };
  }
  return template;
}

function formStateForTemplate(template: RuleSpecTemplate): RuleSpecFormState {
  const actionKind = actionKindForTemplate(template);
  const input = objectValue(template.inputs?.[0]);
  const output = objectValue(template.outputs?.[0]);
  const resources = objectValue(template.resources);
  const smokeInputs = objectValue(template.smokeTest?.inputs);
  const inputName = stringValue(input.name) || "primary";
  const smoke = objectValue(smokeInputs[inputName]);
  return {
    actionKind,
    actionValue: actionValueForTemplate(template, actionKind),
    moduleSnakefile: stringValue(template.module?.snakefile),
    moduleRule: stringValue(template.module?.rule),
    inputName,
    inputType: stringValue(input.type) || "file",
    inputKind: stringValue(input.kind),
    outputName: stringValue(output.name) || "report",
    outputPath: stringValue(output.path),
    outputKind: stringValue(output.kind) || "report",
    outputMimeType: stringValue(output.mimeType) || "text/plain",
    params: Object.keys(objectValue(template.params)).join(", "),
    threads: String(resourceDefault(resources.threads) || template.threads || 1),
    memMb: String(resourceDefault(resources.mem_mb) || 512),
    log: typeof template.log === "string" ? template.log : Object.values(template.log || {})[0] || "",
    channels: (template.environment?.conda?.channels || []).join(", "),
    dependencies: (template.environment?.conda?.dependencies || []).join(", "),
    smokeFilename: stringValue(smoke.filename) || "input.txt",
    smokeContent: stringValue(smoke.content) || "smoke\\n",
    smokeMimeType: stringValue(smoke.mimeType) || "text/plain",
  };
}

function buildRuleTemplate(form: RuleSpecFormState, initial: RuleSpecTemplate): RuleSpecTemplate {
  const inputName = safePortName(form.inputName, "primary");
  const outputName = safePortName(form.outputName, "report");
  const resources = { ...objectValue(initial.resources), threads: { default: toPositiveInt(form.threads, 1) }, mem_mb: { default: toPositiveInt(form.memMb, 512) } };
  const primaryInput = { ...(initial.inputs?.[0] || {}), name: inputName, type: form.inputType.trim() || "file", kind: form.inputKind.trim() || undefined, required: true };
  const primaryOutput = {
    ...(initial.outputs?.[0] || {}),
    name: outputName,
    path: form.outputPath.trim(),
    kind: form.outputKind.trim() || "report",
    mimeType: form.outputMimeType.trim() || "text/plain",
  };
  const template: RuleSpecTemplate = {
    inputs: preserveAdditionalPorts(initial.inputs, primaryInput),
    outputs: preserveAdditionalPorts(initial.outputs, primaryOutput),
    params: paramSchema(form.params, initial.params),
    resources,
    log: form.log.trim(),
    environment: {
      ...initial.environment,
      conda: {
        channels: splitList(form.channels),
        dependencies: splitList(form.dependencies),
      },
    },
    smokeTest: {
      ...initial.smokeTest,
      inputs: {
        ...(initial.smokeTest?.inputs || {}),
        [inputName]: {
          filename: form.smokeFilename.trim() || "input.txt",
          content: form.smokeContent,
          mimeType: form.smokeMimeType.trim() || "text/plain",
        },
      },
    },
  };
  if (form.actionKind === "module") {
    template.module = { snakefile: form.moduleSnakefile.trim(), rule: form.moduleRule.trim() };
  } else {
    template[form.actionKind] = form.actionValue.trim();
  }
  return template;
}

function preserveAdditionalPorts<T>(existing: T[] | undefined, primary: T): T[] {
  return [primary, ...(existing || []).slice(1)];
}

function requiredFields(form: RuleSpecFormState): Array<keyof RuleSpecFormState> {
  const actionFields: Array<keyof RuleSpecFormState> = form.actionKind === "module" ? ["moduleSnakefile", "moduleRule"] : ["actionValue"];
  return [...actionFields, "inputName", "outputName", "outputPath", "outputKind", "outputMimeType", "threads", "memMb", "log", "channels", "dependencies", "smokeFilename", "smokeContent"];
}

function actionKindForTemplate(template: RuleSpecTemplate): ActionKind {
  if (stringValue(template.wrapper)) return "wrapper";
  if (stringValue(template.script)) return "script";
  if (template.module?.snakefile || template.module?.rule) return "module";
  return "commandTemplate";
}

function actionValueForTemplate(template: RuleSpecTemplate, kind: ActionKind) {
  if (kind === "module") return "";
  return stringValue(template[kind]);
}

function paramSchema(rawNames: string, existing: RuleSpecTemplate["params"]): Record<string, RuleSpecParam | RuleSpecScalar> {
  const current = objectValue(existing);
  return Object.fromEntries(splitList(rawNames).map((name) => [name, current[name] || {}]));
}

function splitList(value: string) {
  return value.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean);
}

function resourceDefault(value: unknown) {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as { default?: unknown; value?: unknown }).default || (value as { value?: unknown }).value : value;
}

function toPositiveInt(value: string, fallback: number) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function hasRuleTemplate(template: Record<string, unknown>) {
  return Boolean(
    stringValue(template.commandTemplate) ||
      stringValue(template.wrapper) ||
      stringValue(template.script) ||
      Object.keys(objectValue(template.module)).length > 0 ||
      Array.isArray(template.inputs) ||
      Array.isArray(template.outputs)
  );
}

function uniqueChannels(source: string) {
  return Array.from(new Set(["conda-forge", source === "conda-forge" ? "bioconda" : source].filter(Boolean)));
}

function objectValue(raw: unknown): Record<string, unknown> {
  return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {};
}

function stringValue(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
}

function safeName(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "") || "tool";
}

function safePortName(value: string, fallback: string) {
  return value.trim().replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || fallback;
}
