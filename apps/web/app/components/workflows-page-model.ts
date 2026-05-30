import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import { displayRuleTemplateForTool, hasRuleAction, ruleSpecReadinessForTool } from "./tool-rule-readiness";

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
  resources?: Record<string, WorkflowResourceSpec>;
  tags?: string[];
  moduleCount?: number | null;
  inputCount?: number | null;
  outputCount?: number | null;
};

export type WorkflowResourceSpec = {
  type?: string;
  required?: boolean;
  description?: string;
  configKey?: string;
  acceptedTemplates?: string[];
  acceptedCapabilities?: string[];
};

export type WorkflowCatalogResponse = {
  data: {
    items: WorkflowCatalogItem[];
    serverReady?: boolean;
    pipelineError?: string;
  };
};

export type WorkflowServer = {
  serverId: string;
  label?: string;
  connected?: boolean;
  ready?: boolean;
  reasonCode?: string;
  message?: string;
  health?: {
    startup?: WorkflowHealthCheck;
    live?: WorkflowHealthCheck;
    ready?: WorkflowHealthCheck;
    workflowRuntime?: WorkflowRuntimeHealth;
    pipelineRegistry?: WorkflowPipelineRegistryHealth;
  };
  runner?: {
    ready?: boolean;
    message?: string;
    reasonCode?: string;
    bootstrapMetadata?: {
      workflow_profile?: {
        path?: string;
        config?: string;
        written?: boolean;
      };
      canary?: {
        ok?: boolean;
        status?: string;
        message?: string;
        submission?: {
          runId?: string;
        };
        run?: {
          runId?: string;
        };
        result?: {
          resultId?: string;
          artifactCount?: number;
        };
        preview?: unknown;
      };
    };
  };
};

export type WorkflowServersResponse = {
  data: {
    items: WorkflowServer[];
  };
};

export type WorkflowRuntimeHealth = {
  ok?: boolean;
  message?: string;
  provider?: string;
  source?: string;
  version?: string;
  snakemakeVersion?: string;
  workflowProfileConfigured?: boolean;
  workflowProfileOk?: boolean;
  workflowProfileMessage?: string;
  workflowProfileDir?: string;
  workflowProfileName?: string;
  workflowProfilePath?: string;
};

export type WorkflowPipelineRegistryHealth = {
  ok?: boolean;
  message?: string;
  count?: number;
};

export type WorkflowHealthCheck = {
  ok?: boolean;
  message?: string;
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

export type WorkflowResourceBinding = {
  databaseId: string;
};

export type WorkflowResourceBindings = Record<string, WorkflowResourceBinding>;

export type BuildPipelineRunSpecInput = {
  projectId: string;
  pipelineId: string;
  uploads: WorkflowUpload[];
  params?: Record<string, unknown>;
  resourceBindings?: WorkflowResourceBindings;
};

export function buildPipelineRunSpec({ projectId, pipelineId, uploads, params, resourceBindings }: BuildPipelineRunSpecInput) {
  const runSpec: Record<string, unknown> = {
    projectId,
    pipelineId,
    inputs: uploads.map((upload, index) => ({
      uploadId: upload.uploadId,
      filename: upload.filename,
      role: upload.role || (index === 0 ? "reads" : `reads_${index + 1}`),
    })),
    params: params || {},
  };
  if (resourceBindings && Object.keys(resourceBindings).length > 0) {
    runSpec.resourceBindings = resourceBindings;
  }
  return runSpec;
}

export function generatedToolResourceEntries(tools: Pick<AddedTool, "ruleTemplate" | "ruleSpecDraft">[]) {
  const entries: [string, WorkflowResourceSpec][] = [];
  const seen = new Set<string>();
  for (const tool of tools) {
    const resources = (readToolRuleTemplate(tool) as { resources?: unknown }).resources;
    if (!resources || typeof resources !== "object" || Array.isArray(resources)) continue;
    for (const [key, value] of Object.entries(resources as Record<string, unknown>)) {
      if (seen.has(key) || !value || typeof value !== "object" || Array.isArray(value)) continue;
      const spec = value as WorkflowResourceSpec;
      if ((spec.type || "database") !== "database") continue;
      seen.add(key);
      entries.push([key, spec]);
    }
  }
  return entries;
}

export function runnableCatalogItems(items: WorkflowCatalogItem[]) {
  return items.filter((item) => item.runnable);
}

export function outputArtifactNames(item: WorkflowCatalogItem) {
  const artifacts = item.outputSchema?.artifacts || [];
  return artifacts.map((artifact) => artifact.name || artifact.kind || "artifact").filter(Boolean).join(", ");
}

export function selectableTools(tools: AddedTool[]) {
  return tools
    .map((tool, index) => ({ tool, index, score: ruleReadyToolScore(tool) }))
    .filter((entry) => ruleSpecReadinessForTool(entry.tool).workflowReady)
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .map((entry) => entry.tool);
}

function ruleReadyToolScore(tool: AddedTool) {
  const template = readToolRuleTemplate(tool);
  let score = 0;
  if (toolHasRuleAction(template)) score += 4;
  if (Array.isArray(template.inputs) && template.inputs.length > 0) score += 2;
  if (Array.isArray(template.outputs) && template.outputs.length > 0) score += 2;
  if (Array.isArray(tool.capabilities) && tool.capabilities.length > 0) score += 1;
  return score;
}

function readToolRuleTemplate(tool: Pick<AddedTool, "ruleTemplate" | "ruleSpecDraft">): Record<string, unknown> {
  return displayRuleTemplateForTool(tool as AddedTool);
}

function toolHasRuleAction(template: Record<string, unknown>) {
  return hasRuleAction(template);
}

export function selectableDatabases(databases: DatabaseItem[]) {
  return databases.filter((database) => database.status === "available");
}

export function workflowResourceEntries(item: WorkflowCatalogItem | null) {
  const resources = item?.resources || {};
  return Object.entries(resources).filter(([, spec]) => (spec.type || "database") === "database");
}

export function databaseMatchesWorkflowResource(database: DatabaseItem, spec: WorkflowResourceSpec) {
  if (database.status !== "available") return false;
  const metadata = database.metadata || {};
  if (spec.acceptedTemplates?.length && !spec.acceptedTemplates.includes(String(metadata.templateId || ""))) {
    return false;
  }
  if (spec.acceptedCapabilities?.length) {
    const rawCapabilities = (metadata as { capabilities?: unknown }).capabilities;
    const capabilities = Array.isArray(rawCapabilities) ? rawCapabilities.map(String) : [];
    return spec.acceptedCapabilities.some((capability) => capabilities.includes(capability));
  }
  return true;
}

export function buildWorkflowResourceBindings(
  selectedResourceDatabaseIds: Record<string, string>,
  item: WorkflowCatalogItem | null,
  databases: DatabaseItem[]
): WorkflowResourceBindings {
  const availableIds = new Set(databases.filter((database) => database.status === "available").map((database) => database.id));
  return Object.fromEntries(
    workflowResourceEntries(item)
      .map(([key, spec]) => [key, spec, selectedResourceDatabaseIds[key]] as const)
      .filter(([, spec, databaseId]) => {
        if (!databaseId || !availableIds.has(databaseId)) return false;
        const database = databases.find((item) => item.id === databaseId);
        return Boolean(database && databaseMatchesWorkflowResource(database, spec));
      })
      .map(([key, , databaseId]) => [key, { databaseId }])
  );
}

export function workflowErrorMessage(err: unknown, fallback: string) {
  const message = err instanceof Error ? err.message : String(err || "");
  if (/WORKFLOW_TOOL_NOT_READY/.test(message)) {
    return "所选工具还未通过合同验证，请先在工具页完成 dry-run、smoke run 和输出验证。";
  }
  if (/not ready|not prepared|not connected|unreachable|Remote end closed/i.test(message)) {
    return "远程服务暂不可用，请先连接 SSH 并启动远程服务。";
  }
  if (/serverId|required/i.test(message)) {
    return "没有可用的远程服务器，请先完成 SSH 连接和远程服务准备。";
  }
  return message || fallback;
}
