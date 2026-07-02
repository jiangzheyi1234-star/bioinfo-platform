import type { GeneratedWorkflowGraphDraft } from "./generated-workflow-model";
import type { WorkflowResourceBindings } from "./workflows-page-model";

export const WORKFLOW_DESIGN_DRAFT_CONTRACT_VERSION = "workflow-design-draft-v1";
export const WORKFLOW_DESIGN_ENGINE = "snakemake";
const WORKFLOW_DESIGN_EDGE_AUDIT_KEYS = new Set(["source", "decision", "confidence", "reason", "hardChecks", "evidence"]);

type WorkflowDesignScalar = string | number | boolean;
type WorkflowDesignScalarRecord = Record<string, WorkflowDesignScalar>;

type WorkflowDesignInputBinding =
  { fromInput: string };

export type WorkflowDesignDraft = {
  contractVersion: typeof WORKFLOW_DESIGN_DRAFT_CONTRACT_VERSION;
  engine: typeof WORKFLOW_DESIGN_ENGINE;
  metadata: {
    name: string;
    description?: string;
    projectId: string;
    tags?: string[];
  };
  inputs: Array<{
    id: string;
    role: string;
    type?: string;
    kind?: string;
    path: string;
    filename?: string;
    mimeType: string;
    data?: string;
    format?: string;
    operation?: string;
    resource?: string;
    metadata?: WorkflowDesignScalarRecord;
  }>;
  nodes: Array<{
    id: string;
    toolRevisionId: string;
    inputs: Record<string, WorkflowDesignInputBinding>;
    params: WorkflowDesignScalarRecord;
    runtime: Record<string, unknown>;
    resources: WorkflowDesignScalarRecord;
    outputs: Record<string, { expose: boolean; alias?: string; metadata?: WorkflowDesignScalarRecord }>;
    metadata: WorkflowDesignScalarRecord;
    provenance: WorkflowDesignScalarRecord;
  }>;
  edges: Array<{
    id?: string;
    from: { nodeId: string; port: string };
    to: { nodeId: string; port: string };
    audit?: WorkflowDesignScalarRecord;
  }>;
  resources: {
    bindings: WorkflowResourceBindings;
    metadata?: WorkflowDesignScalarRecord;
  };
  outputs: Array<{
    from: { nodeId: string; port: string };
    as: string;
    metadata?: WorkflowDesignScalarRecord;
  }>;
  provenance: WorkflowDesignScalarRecord;
};

export type WorkflowDesignDraftRecord = {
  draftId: string;
  parentDraftId?: string | null;
  contractVersion: string;
  engine: string;
  name: string;
  projectId: string;
  revision: number;
  draft: WorkflowDesignDraft;
  createdAt: string;
  updatedAt: string;
};

export type WorkflowDesignSemanticPortDecision = {
  compatible: boolean;
  score: number | null;
  matchedFields: string[];
  genericFields: string[];
  advisoryFields: string[];
  mismatchedField: string;
  hardChecks: string[];
  advisoryChecks: string[];
  inputSpec: Record<string, string>;
  outputSpec: Record<string, string>;
};

export type WorkflowDesignSemanticPortCandidate = {
  converterToolRevisionId: string;
  converterToolId: string;
  converterToolName: string;
  inputPort: string;
  outputPort: string;
  inputScore: number;
  outputScore: number;
  totalScore: number;
  operation?: string;
  workflowStage?: string;
  confirmationRequired: boolean;
  insertionMode: "explicit-user-confirmed";
  autoInsertionBlockedReasons: string[];
  hardChecks: string[];
  evidence: string[];
  inputDecision: WorkflowDesignSemanticPortDecision;
  outputDecision: WorkflowDesignSemanticPortDecision;
  reason: string;
};

export type WorkflowDesignSemanticPortEdgePlan = {
  edgeId?: string;
  proposed?: boolean;
  from: { nodeId: string; port: string };
  to: { nodeId: string; port: string };
  decision: WorkflowDesignSemanticPortDecision;
  recommendation: {
    action: "connect" | "insert-converter" | "block";
    reasonCode: string;
    confidence: number;
    hardChecks: string[];
    evidence: string[];
    converterCandidateCount: number;
  };
  converterCandidates: WorkflowDesignSemanticPortCandidate[];
};

export type WorkflowDesignSemanticPortPlan = {
  schemaVersion: "h2ometa.workflow-design-semantic-port-plan.v1";
  edgeCount: number;
  compatibleEdgeCount: number;
  blockedEdgeCount: number;
  converterCandidateCount: number;
  edges: WorkflowDesignSemanticPortEdgePlan[];
};

export type WorkflowDesignSemanticPortEvidenceEdge = {
  edgeId?: string;
  from: { nodeId: string; port: string };
  to: { nodeId: string; port: string };
  compatible: boolean;
  matchedFields: string[];
  genericFields: string[];
  advisoryFields: string[];
  mismatchedField: string;
  hardChecks: string[];
  recommendation: {
    action: "connect" | "insert-converter" | "block" | string;
    reasonCode: string;
    converterCandidateCount: number;
  };
};

export type WorkflowDesignSemanticPortEvidence = {
  schemaVersion: "h2ometa.workflow-design-semantic-port-evidence.v1";
  sourcePlanSchemaVersion: string;
  status: "passed" | "blocked" | string;
  edgeCount: number;
  compatibleEdgeCount: number;
  blockedEdgeCount: number;
  converterCandidateCount: number;
  edges: WorkflowDesignSemanticPortEvidenceEdge[];
};

export type WorkflowDesignPlan = {
  valid: boolean;
  normalizedGraph: Record<string, unknown>;
  semanticPortPlan?: WorkflowDesignSemanticPortPlan;
  orderedSteps: Array<Record<string, unknown>>;
  resolvedPorts: Record<string, unknown>;
  requiredResources: Record<string, unknown>;
  requiredDatabases: Record<string, unknown>;
  exposedOutputs: Record<string, unknown>;
  validationIssues: Array<{ code: string; message: string }>;
  previews: { snakefile: string; config: string };
  runSpec: Record<string, unknown>;
};

export type WorkflowRevisionSummary = {
  workflowRevisionId: string;
  draftId?: string | null;
  draftRevision?: number | null;
  contentHash?: string;
  manifest?: {
    schemaVersion?: string;
    layout?: Record<string, string | string[]>;
    files?: Array<{ path: string; sha256: string }>;
    runSpecSha256?: string;
    toolRevisions?: Array<{ toolRevisionId: string }>;
  };
  graphSnapshot?: {
    schemaVersion?: string;
    runSpec?: Record<string, unknown>;
    semanticPortEvidence?: WorkflowDesignSemanticPortEvidence;
  };
  runtimeLock?: Record<string, unknown>;
  compiler?: Record<string, unknown>;
  createdBy?: string | null;
  createdAt?: string;
};

export type WorkflowDesignCompileResult = {
  workflowRevisionId?: string;
  workflowRevision?: WorkflowRevisionSummary;
  semanticPortEvidence?: WorkflowDesignSemanticPortEvidence;
  layout: Record<string, string | string[]>;
  runSpec: Record<string, unknown>;
};

export function buildWorkflowDesignDraft({
  graphDraft,
  files,
  projectId,
  resourceBindings,
  name,
  existingDraft,
}: {
  graphDraft: GeneratedWorkflowGraphDraft;
  files: File[];
  projectId: string;
  resourceBindings: WorkflowResourceBindings;
  name: string;
  existingDraft?: WorkflowDesignDraft;
}): WorkflowDesignDraft {
  const inputs = files.length > 0
    ? files.map((file, index) => {
        const role = index === 0 ? "input" : `input_${index + 1}`;
        const existingInput = existingDraft?.inputs.find((input) => input.role === role);
        return {
          id: existingInput?.id || role,
          role,
          ...workflowDesignInputSemanticsForDraft(existingInput),
          path: `inputs/${file.name || role}`,
          filename: file.name || role,
          mimeType: file.type || existingInput?.mimeType || "application/octet-stream",
          metadata: existingInput?.metadata || {},
        };
      })
    : existingDraft?.inputs || [];
  return {
    contractVersion: WORKFLOW_DESIGN_DRAFT_CONTRACT_VERSION,
    engine: WORKFLOW_DESIGN_ENGINE,
    metadata: {
      name: name.trim() || "Untitled workflow design",
      description: existingDraft?.metadata.description || "",
      projectId,
      tags: existingDraft?.metadata.tags || [],
    },
    inputs,
    nodes: graphDraft.nodes.map((node) => {
      const existingNode = existingDraft?.nodes.find((item) => item.id === node.id && item.toolRevisionId === node.toolRevisionId);
      const exposedOutputs = graphDraft.outputs.filter((output) => output.fromStep === node.id);
      const exposedOutputNames = new Set(exposedOutputs.map((output) => output.output));
      const existingNodeOutputEntries = Object.entries(existingNode?.outputs || {})
        .filter(([outputName]) => !exposedOutputNames.has(outputName))
        .map(([outputName, output]) => [
          outputName,
          {
            expose: false,
            ...(output.alias ? { alias: output.alias } : {}),
            metadata: output.metadata || {},
          },
        ]);
      return {
        id: node.id,
        toolRevisionId: node.toolRevisionId,
        inputs: Object.fromEntries(
          Object.entries(node.inputs)
            .filter(([, binding]) => binding !== "")
            .map(([inputName, binding]) => [inputName, workflowDesignInputBindingForDraft(binding, inputs)])
        ),
        params: { ...node.params },
        runtime: workflowDesignRuntimeForDraft(node.runtime),
        resources: existingNode?.resources || {},
        outputs: Object.fromEntries(
          existingNodeOutputEntries.concat(
            exposedOutputs
            .map((output) => {
              const existingOutput = existingNode?.outputs?.[output.output];
              return [
                output.output,
                {
                  expose: true,
                  alias: output.as,
                  metadata: existingOutput?.metadata || {},
                },
              ];
            })
          )
        ),
        metadata: { ...(existingNode?.metadata || {}), ...(node.metadata || {}) },
        provenance: existingNode?.provenance || { source: "workflow-builder" },
      };
    }),
    edges: graphDraft.edges.map((edge) => ({
      id: edge.id,
      from: { ...edge.from },
      to: { ...edge.to },
      ...(edge.audit ? { audit: workflowDesignEdgeAuditForDraft(edge.audit) } : {}),
    })),
    resources: { bindings: resourceBindings, metadata: existingDraft?.resources.metadata || {} },
    outputs: graphDraft.outputs.map((output) => {
      const existingOutput = existingDraft?.outputs.find(
        (item) => item.from.nodeId === output.fromStep && item.from.port === output.output && item.as === output.as
      );
      return {
        from: { nodeId: output.fromStep, port: output.output },
        as: output.as,
        metadata: existingOutput?.metadata || {},
      };
    }),
    provenance: existingDraft?.provenance || { createdBy: "workflow-builder" },
  };
}

function workflowDesignInputSemanticsForDraft(
  input: WorkflowDesignDraft["inputs"][number] | undefined
): Partial<WorkflowDesignDraft["inputs"][number]> {
  return workflowDesignStringFields(input, ["type", "kind", "data", "format", "operation", "resource"]);
}

function workflowDesignStringFields<T extends string>(
  source: Partial<Record<T, unknown>> | undefined,
  fields: T[]
): Partial<Record<T, string>> {
  const result: Partial<Record<T, string>> = {};
  for (const field of fields) {
    const value = typeof source?.[field] === "string" ? source[field].trim() : "";
    if (value) result[field] = value;
  }
  return result;
}

function workflowDesignRuntimeForDraft(
  runtime: GeneratedWorkflowGraphDraft["nodes"][number]["runtime"]
): Record<string, unknown> {
  return {
    ...(runtime.threads !== undefined ? { threads: runtime.threads } : {}),
    resources: { ...(runtime.resources || {}) },
    schedulerResources: { ...(runtime.schedulerResources || {}) },
    ...(runtime.log !== undefined ? { log: runtime.log } : {}),
  };
}

export function workflowDesignDraftToGraphDraft(draft: WorkflowDesignDraft): GeneratedWorkflowGraphDraft {
  return {
    nodes: draft.nodes.map((node) => ({
      id: node.id,
      toolRevisionId: node.toolRevisionId,
      inputs: Object.fromEntries(
        Object.entries(node.inputs).map(([inputName, binding]) => [
          inputName,
          workflowDesignInputBindingToGraph(binding, draft.inputs),
        ])
      ) as GeneratedWorkflowGraphDraft["nodes"][number]["inputs"],
      params: node.params,
      runtime: node.runtime as GeneratedWorkflowGraphDraft["nodes"][number]["runtime"],
      metadata: node.metadata || {},
    })),
    edges: draft.edges.map((edge, index) => ({
      id: edge.id || `${edge.from.nodeId}.${edge.from.port}->${edge.to.nodeId}.${edge.to.port}:${index}`,
      from: { ...edge.from },
      to: { ...edge.to },
      audit: workflowDesignEdgeAuditToGraph(edge.audit),
    })),
    outputs: draft.outputs.map((output) => ({
      fromStep: output.from.nodeId,
      output: output.from.port,
      as: output.as,
    })),
  };
}

function workflowDesignEdgeAuditForDraft(
  audit: GeneratedWorkflowGraphDraft["edges"][number]["audit"]
): WorkflowDesignScalarRecord | undefined {
  if (!audit) return undefined;
  return {
    source: audit.source,
    decision: audit.decision,
    confidence: audit.confidence,
    reason: audit.reason,
    hardChecks: JSON.stringify(audit.hardChecks),
    evidence: JSON.stringify(audit.evidence),
  };
}

function workflowDesignEdgeAuditToGraph(
  audit: unknown
): GeneratedWorkflowGraphDraft["edges"][number]["audit"] {
  if (audit === undefined) return undefined;
  if (!audit || typeof audit !== "object" || Array.isArray(audit)) {
    throw new Error("WORKFLOW_DESIGN_EDGE_AUDIT_INVALID");
  }
  const rawAudit = audit as Record<string, unknown>;
  workflowDesignValidateScalarRecord(rawAudit);
  const scalarAudit = rawAudit as WorkflowDesignScalarRecord;
  const source = scalarAudit.source === "auto" || scalarAudit.source === "manual" ? scalarAudit.source : "";
  const decision = workflowDesignAuditDecision(scalarAudit.decision);
  const confidence = typeof scalarAudit.confidence === "number" ? scalarAudit.confidence : Number.NaN;
  const reason = typeof scalarAudit.reason === "string" ? scalarAudit.reason.trim() : "";
  if (!source || !decision || !Number.isFinite(confidence) || !reason) {
    throw new Error("WORKFLOW_DESIGN_EDGE_AUDIT_INVALID");
  }
  return {
    source,
    decision,
    confidence,
    reason,
    hardChecks: workflowDesignAuditStringArray(scalarAudit.hardChecks, "hardChecks"),
    evidence: workflowDesignAuditStringArray(scalarAudit.evidence, "evidence"),
  };
}

function workflowDesignValidateScalarRecord(audit: Record<string, unknown>) {
  const invalidEntry = Object.entries(audit).find(([key, value]) => {
    return !WORKFLOW_DESIGN_EDGE_AUDIT_KEYS.has(key)
      || (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean");
  });
  if (invalidEntry) {
    throw new Error(`WORKFLOW_DESIGN_EDGE_AUDIT_INVALID: ${invalidEntry[0]}`);
  }
}

function workflowDesignAuditDecision(value: WorkflowDesignScalar | undefined) {
  return value === "recommended" || value === "blocked" || value === "ambiguous" || value === "manual"
    ? value
    : "";
}

function workflowDesignAuditStringArray(value: WorkflowDesignScalar | undefined, field: string) {
  if (typeof value !== "string") {
    throw new Error(`WORKFLOW_DESIGN_EDGE_AUDIT_INVALID: ${field}`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`WORKFLOW_DESIGN_EDGE_AUDIT_INVALID: ${field}`);
  }
  if (!Array.isArray(parsed) || parsed.some((item) => typeof item !== "string")) {
    throw new Error(`WORKFLOW_DESIGN_EDGE_AUDIT_INVALID: ${field}`);
  }
  return parsed;
}

function workflowDesignInputBindingForDraft(
  binding: unknown,
  inputs: WorkflowDesignDraft["inputs"]
): WorkflowDesignInputBinding {
  if (binding && typeof binding === "object" && "fromUpload" in binding) {
    const index = Number((binding as { fromUpload?: unknown }).fromUpload);
    const role = Number.isInteger(index) && index >= 0 ? inputs[index]?.role : "";
    if (role) return { fromInput: role };
    throw new Error(`WORKFLOW_DESIGN_INPUT_UPLOAD_UNKNOWN: ${index}`);
  }
  if (binding && typeof binding === "object" && "fromStep" in binding) {
    throw new Error("WORKFLOW_DESIGN_NODE_INPUT_EDGE_UNSUPPORTED");
  }
  throw new Error("WORKFLOW_DESIGN_INPUT_BINDING_INVALID");
}

function workflowDesignInputBindingToGraph(
  binding: WorkflowDesignInputBinding,
  inputs: WorkflowDesignDraft["inputs"]
): unknown {
  const index = inputs.findIndex((input) => input.role === binding.fromInput);
  if (index >= 0) return { fromUpload: index };
  throw new Error(`WORKFLOW_DESIGN_INPUT_ROLE_UNKNOWN: ${binding.fromInput}`);
}
