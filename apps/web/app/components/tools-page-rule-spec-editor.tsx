"use client";

import { useMemo, useState } from "react";
import { Loader2, Save, X } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { AddedTool, RuleSpecTemplate } from "./tools-page-model";

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
  const initialText = useMemo(() => JSON.stringify(ruleTemplateForEditor(tool), null, 2), [tool]);
  const [draftText, setDraftText] = useState(initialText);
  const [localError, setLocalError] = useState("");

  function save() {
    setLocalError("");
    let parsed: unknown;
    try {
      parsed = JSON.parse(draftText);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "RuleSpec JSON 无效");
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      setLocalError("RuleSpec 必须是 JSON object");
      return;
    }
    onSave(parsed as RuleSpecTemplate);
  }

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-[11px] font-medium uppercase text-slate-400">RuleSpec JSON</div>
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
      <textarea
        value={draftText}
        onChange={(event) => setDraftText(event.target.value)}
        spellCheck={false}
        className="h-72 w-full resize-y rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-[11px] leading-5 text-slate-800 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100"
      />
      {localError || error ? <div className="mt-2 text-xs leading-5 text-red-600">{localError || error}</div> : null}
    </div>
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
    resources: { threads: { default: 1 } },
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
