"use client";

import type { ServerDoctorReport, WorkflowServerProfile, WorkflowSpecView } from "./detection_workspace_types";

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
      {
        node_id: "step_1",
        tool_id: "fastp",
        label: "Quality Control",
        params: {},
      },
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

export function buildProfileFromDoctor(doctor: ServerDoctorReport | null): WorkflowServerProfile {
  const recommended = doctor?.recommended_profile_details;
  if (recommended) {
    return recommended;
  }
  return {
    profile_id: "personal_conda",
    server_id: doctor?.server_id || "current",
    profile_kind: "personal_conda",
    executor: "local",
    packaging_mode: "conda",
    container_runtime: "",
    work_dir: "~/.bioflow/runs/work",
    output_dir: "~/.bioflow/runs/output",
    cache_dir: "~/.bioflow/cache/conda",
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
