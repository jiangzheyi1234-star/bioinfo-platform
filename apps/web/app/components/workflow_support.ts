"use client";

import type { WorkflowSpecView } from "./detection_workspace_types";

export type SchemaFieldKind = "string" | "number" | "integer" | "boolean";

export type SchemaField = {
  key: string;
  label: string;
  kind: SchemaFieldKind;
  defaultValue: string | number | boolean;
  enumValues: string[];
  description: string;
  required: boolean;
};

export type WorkflowNodeTemplate = {
  key: string;
  tool_id: string;
  label: string;
  description: string;
};

export const WORKFLOW_NODE_TEMPLATES: WorkflowNodeTemplate[] = [
  { key: "fastp", tool_id: "fastp", label: "Quality Control", description: "FASTQ 质控与过滤。" },
  { key: "kraken2", tool_id: "kraken2", label: "Taxonomy", description: "物种分类与 kreport 产物。" },
  { key: "bracken", tool_id: "bracken", label: "Abundance", description: "基于 kraken2 的丰度估计。" },
  { key: "krona", tool_id: "krona", label: "Visualization", description: "交互式 Krona 报告。" },
  { key: "quast", tool_id: "quast", label: "Assembly QC", description: "组装质量汇总。" },
  { key: "custom", tool_id: "custom_tool", label: "Custom Step", description: "从空白步骤开始手动编辑。" },
];

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function createStarterWorkflow(projectId: string): WorkflowSpecView {
  const workflowId = slugify(projectId || "workflow") || "workflow";
  return {
    workflow_id: `${workflowId}-main`,
    name: "FASTQ QC Workflow",
    version: "0.1.0",
    nodes: [
      createWorkflowNodeDraft({ index: 1, templateKey: "fastp" }),
    ],
    edges: [],
    params_schema: {
      type: "object",
      properties: {
        sample_name: {
          type: "string",
          title: "样本名",
          default: "demo_sample",
        },
        thread: {
          type: "integer",
          title: "线程数",
          default: 4,
        },
        qualified_quality_phred: {
          type: "integer",
          title: "最低质量值",
          default: 20,
        },
        length_required: {
          type: "integer",
          title: "最短读长",
          default: 50,
        },
      },
      required: ["sample_name", "thread", "qualified_quality_phred", "length_required"],
      additionalProperties: true,
    },
  };
}

export function getSchemaFields(schema: Record<string, unknown>): { fields: SchemaField[]; unsupported: string[] } {
  const rootType = typeof schema.type === "string" ? schema.type : "object";
  if (rootType !== "object") {
    return { fields: [], unsupported: ["当前仅支持顶层 object schema。"] };
  }
  const rawProperties = schema.properties;
  if (!rawProperties || typeof rawProperties !== "object" || Array.isArray(rawProperties)) {
    return { fields: [], unsupported: [] };
  }
  const requiredSet = new Set(Array.isArray(schema.required) ? schema.required.map((item: unknown) => String(item)) : []);
  const fields: SchemaField[] = [];
  const unsupported: string[] = [];
  for (const [key, rawField] of Object.entries(rawProperties)) {
    if (!rawField || typeof rawField !== "object" || Array.isArray(rawField)) {
      unsupported.push(key);
      continue;
    }
    const type = typeof rawField.type === "string" ? rawField.type : "string";
    if (!["string", "number", "integer", "boolean"].includes(type)) {
      unsupported.push(key);
      continue;
    }
    const enumValues = Array.isArray(rawField.enum) ? rawField.enum.map((item: unknown) => String(item)) : [];
    fields.push({
      key,
      label: typeof rawField.title === "string" && rawField.title.trim() ? rawField.title.trim() : key,
      kind: type as SchemaFieldKind,
      defaultValue:
        type === "boolean"
          ? Boolean(rawField.default)
          : type === "number" || type === "integer"
            ? Number(rawField.default ?? 0)
            : typeof rawField.default === "string"
              ? rawField.default
              : "",
      enumValues,
      description: typeof rawField.description === "string" ? rawField.description : "",
      required: requiredSet.has(key),
    });
  }
  return { fields, unsupported };
}

export function normalizeFieldValue(kind: SchemaFieldKind, value: string | number | boolean): string | number | boolean {
  if (kind === "boolean") {
    return Boolean(value);
  }
  if (kind === "number") {
    return value === "" ? 0 : Number(value);
  }
  if (kind === "integer") {
    return value === "" ? 0 : Math.trunc(Number(value));
  }
  return String(value);
}

export function formatDateTime(value: number): string {
  if (!value) {
    return "未记录";
  }
  return new Date(value * 1000).toLocaleString("zh-CN", { hour12: false });
}

export function mapWorkflowRunStatus(status: string): string {
  const normalized = status.trim();
  if (normalized === "draft") return "草稿";
  if (normalized === "pending") return "待提交";
  if (normalized === "running") return "运行中";
  if (normalized === "completed") return "已完成";
  if (normalized === "failed") return "失败";
  if (normalized === "cancelled") return "已取消";
  return normalized || "未知";
}
