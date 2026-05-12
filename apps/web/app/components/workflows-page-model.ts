import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";

export const GENERATED_TOOL_RUN_PIPELINE_ID = "generated-tool-run-v1";

export type WorkflowCatalogItem = {
  id: string;
  kind: "template" | "pipeline" | string;
  name: string;
  version: string;
  category: string;
  description: string;
  engine: string;
  status: string;
  runnable: boolean;
  source: string;
  inputSchema?: Record<string, unknown>;
  paramsSchema?: Record<string, unknown>;
  outputSchema?: {
    artifacts?: Array<{ kind?: string; mimeType?: string; name?: string }>;
  };
  uiSchema?: Record<string, unknown>;
  tags?: string[];
  moduleCount?: number | null;
  inputCount?: number | null;
  outputCount?: number | null;
};

export type WorkflowCatalogResponse = {
  data: {
    items: WorkflowCatalogItem[];
    serverReady?: boolean;
    pipelineError?: string;
  };
};

export type WorkflowTemplateSummary = {
  templateId: string;
  name: string;
  version: string;
  category: string;
  description: string;
  engine: string;
  status: string;
  tags?: string[];
  moduleCount?: number;
  inputCount?: number;
  outputCount?: number;
};

export type WorkflowTemplatesResponse = {
  data: {
    items: WorkflowTemplateSummary[];
  };
};

export type WorkflowServer = {
  serverId: string;
  label?: string;
  connected?: boolean;
  ready?: boolean;
};

export type WorkflowServersResponse = {
  data: {
    items: WorkflowServer[];
  };
};

export type WorkflowUpload = {
  uploadId: string;
  filename: string;
  sizeBytes?: number;
  role?: string;
  sourceUrl?: string;
};

export type WorkflowRun = {
  runId: string;
  status: string;
  stage: string;
  message?: string;
  requestId?: string;
  pipelineId?: string;
  startedAt?: string;
  finishedAt?: string;
  submittedAt?: string;
  createdAt?: string;
  updatedAt?: string;
  runSpec?: {
    pipelineId?: string;
    inputs?: Array<{ filename?: string; role?: string; uploadId?: string }>;
    params?: Record<string, unknown>;
  };
};

export type JsonSchemaProperty = {
  type?: string;
  enum?: unknown[];
  description?: string;
  default?: unknown;
  title?: string;
  minimum?: number;
  maximum?: number;
};

export type JsonSchema = {
  type?: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
};

export type WorkflowRunEvent = {
  eventId?: string;
  runId?: string;
  status?: string;
  stage?: string;
  message?: string;
  createdAt?: string;
};

export type WorkflowLogLines = {
  lines?: string[];
  nextCursor?: string;
};

export type WorkflowArtifact = {
  artifactId: string;
  kind: string;
  mimeType: string;
  sizeBytes: number;
  path?: string;
};

export type WorkflowResultDetail = {
  resultId?: string;
  runId?: string;
  resultDir?: string;
  artifacts?: WorkflowArtifact[];
};

export type WorkflowArtifactPreview = {
  artifact?: WorkflowArtifact;
  preview?: {
    kind?: string;
    content?: string;
    columns?: string[];
    rows?: string[][];
    truncated?: boolean;
  };
};

export type WorkflowRunDetail = {
  run: WorkflowRun;
  events: WorkflowRunEvent[];
  logs: {
    stdout?: WorkflowLogLines;
    stderr?: WorkflowLogLines;
  };
  results?: WorkflowResultDetail;
  previews?: WorkflowArtifactPreview[];
};

export type WorkflowRunDetailResponse = {
  data: WorkflowRunDetail;
};

export type WorkflowRunResponse = {
  data: WorkflowRun;
  location?: string;
  retryAfter?: number;
  requestId?: string;
};

export type WorkflowDatabaseBinding = {
  id: string;
  role: string;
};

export type BuildGeneratedRunSpecInput = {
  projectId: string;
  uploads: WorkflowUpload[];
  toolIds: string[];
  databases: WorkflowDatabaseBinding[];
};

export type BuildPipelineRunSpecInput = {
  projectId: string;
  pipelineId: string;
  uploads: WorkflowUpload[];
  params?: Record<string, unknown>;
};

export function buildPipelineRunSpec({ projectId, pipelineId, uploads, params }: BuildPipelineRunSpecInput) {
  return {
    projectId,
    pipelineId,
    inputs: uploads.map((upload, index) => ({
      uploadId: upload.uploadId,
      filename: upload.filename,
      role: upload.role || (index === 0 ? "reads" : `reads_${index + 1}`),
    })),
    params: params || {},
  };
}

export function buildGeneratedRunSpec({ projectId, uploads, toolIds, databases }: BuildGeneratedRunSpecInput) {
  const runSpec: Record<string, unknown> = {
    projectId,
    pipelineId: GENERATED_TOOL_RUN_PIPELINE_ID,
    inputs: uploads.map((upload, index) => ({
      uploadId: upload.uploadId,
      filename: upload.filename,
      role: index === 0 ? "input" : `input_${index + 1}`,
    })),
  };
  if (databases.length > 0) {
    runSpec.databases = databases;
  }
  if (toolIds.length === 1) {
    runSpec.tool = { id: toolIds[0] };
  } else {
    runSpec.workflow = {
      steps: toolIds.map((toolId, index) => ({
        id: `step_${index + 1}`,
        tool: { id: toolId },
      })),
    };
  }
  return runSpec;
}

export function runnableCatalogItems(items: WorkflowCatalogItem[]) {
  return items.filter((item) => item.runnable);
}

export function outputArtifactNames(item: WorkflowCatalogItem) {
  const artifacts = item.outputSchema?.artifacts || [];
  return artifacts.map((artifact) => artifact.name || artifact.kind || "artifact").filter(Boolean).join(", ");
}

export function workflowDatabaseRole(database: DatabaseItem, index: number) {
  const metadata = database.metadata || {};
  const raw = metadata.templateId || database.type || `database_${index + 1}`;
  const role = raw.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  if (!role) return `database_${index + 1}`;
  return /^\d/.test(role) ? `database_${role}` : role;
}

export function selectableTools(tools: AddedTool[]) {
  return tools.filter((tool) => tool.targetPlatformSupported === true);
}

export function selectableDatabases(databases: DatabaseItem[]) {
  return databases.filter((database) => database.status === "available");
}

export function workflowErrorMessage(err: unknown, fallback: string) {
  const message = err instanceof Error ? err.message : String(err || "");
  if (/not ready|not prepared|not connected|unreachable|Remote end closed/i.test(message)) {
    return "远程服务暂不可用，请先连接 SSH 并启动远程服务。";
  }
  if (/serverId|required/i.test(message)) {
    return "没有可用的远程服务器，请先完成 SSH 连接和远程服务准备。";
  }
  return message || fallback;
}
