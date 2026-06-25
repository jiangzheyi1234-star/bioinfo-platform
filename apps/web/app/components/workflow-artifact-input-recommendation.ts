import type { WorkflowArtifact, WorkflowCatalogItem } from "./workflows-page-model";

export type WorkflowArtifactInputRecommendation = {
  decision: "recommended" | "manual";
  reasons: string[];
  score: number;
  targetRole: string;
};

export type RankedWorkflowArtifact<T extends ArtifactInputCandidate> = {
  artifact: T;
  recommendation: WorkflowArtifactInputRecommendation;
};

type ArtifactInputCandidate = Pick<WorkflowArtifact, "artifactId" | "kind" | "mimeType" | "sha256" | "sizeBytes"> & {
  artifactKey?: string;
};

export function workflowInputRoleForIndex(workflow: WorkflowCatalogItem | null, index: number): string {
  const roles = workflowInputRoles(workflow);
  if (roles[index]) {
    return roles[index];
  }
  if (index > 0) {
    return `${workflowInputRoleDefault(workflow)}_${index + 1}`;
  }
  return workflowInputRoleDefault(workflow);
}

export function rankArtifactInputCandidates<T extends ArtifactInputCandidate>(
  workflow: WorkflowCatalogItem | null,
  inputIndex: number,
  candidates: T[],
): Array<RankedWorkflowArtifact<T>> {
  const targetRole = workflowInputRoleForIndex(workflow, inputIndex);
  return candidates
    .map((artifact, index) => ({
      artifact,
      index,
      recommendation: recommendArtifactForRole(targetRole, artifact),
    }))
    .sort(
      (left, right) =>
        right.recommendation.score - left.recommendation.score ||
        left.index - right.index,
    )
    .map(({ artifact, recommendation }) => ({ artifact, recommendation }));
}

export function recommendArtifactForRole(
  targetRole: string,
  artifact: ArtifactInputCandidate,
): WorkflowArtifactInputRecommendation {
  const roleTokens = tokenSet(targetRole);
  const outputLabel = safeArtifactOutputLabel(artifact.artifactKey);
  const artifactTokens = tokenSet([artifact.artifactId, artifact.kind, artifact.mimeType, outputLabel].filter(Boolean).join(" "));
  const outputTokens = tokenSet(outputLabel);
  const reasons: string[] = [];
  let score = 0;

  const outputMatches = [...roleTokens].filter((token) => outputTokens.has(token));
  if (outputMatches.length > 0) {
    score += 3 + outputMatches.length;
    reasons.push("output port evidence");
  }

  for (const rule of ROLE_RECOMMENDATION_RULES) {
    if (!rule.roleTokens.some((token) => roleTokens.has(token))) continue;
    const matched = rule.artifactTokens.filter((token) => artifactTokens.has(token));
    if (matched.length === 0) continue;
    score += rule.weight + matched.length;
    reasons.push(rule.reason);
  }

  const normalizedKind = normalizeTokenText(artifact.kind);
  if (score === 0 && normalizedKind && roleTokens.has(normalizedKind)) {
    score += 2;
    reasons.push("role matches artifact kind");
  }

  return {
    decision: score >= 3 ? "recommended" : "manual",
    reasons,
    score,
    targetRole: targetRole || "input",
  };
}

function workflowInputRoles(workflow: WorkflowCatalogItem | null): string[] {
  const graph = workflow?.uiSchema?.graph;
  const nodes = graph && typeof graph === "object" && !Array.isArray(graph)
    ? (graph as { nodes?: unknown }).nodes
    : null;
  if (!Array.isArray(nodes)) {
    return [];
  }
  return nodes
    .map((node) => {
      if (!node || typeof node !== "object") return "";
      const record = node as { group?: unknown; kind?: unknown; role?: unknown };
      const isInput = record.group === "input" || record.kind === "input";
      return isInput && typeof record.role === "string" ? record.role.trim() : "";
    })
    .filter(Boolean);
}

function workflowInputRoleDefault(workflow: WorkflowCatalogItem | null): string {
  const inputs = workflow?.uiSchema?.inputs;
  if (inputs && typeof inputs === "object" && !Array.isArray(inputs)) {
    const role = (inputs as { roleDefault?: unknown }).roleDefault;
    if (typeof role === "string" && role.trim()) {
      return role.trim();
    }
  }
  return "reads";
}

function tokenSet(value: string): Set<string> {
  return new Set(normalizeTokenText(value).split(" ").filter(Boolean));
}

function normalizeTokenText(value: string | undefined): string {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

export function safeArtifactOutputLabel(value: string | undefined): string {
  const label = String(value || "").trim();
  if (!label || label.length > 80) return "";
  if (/[\\/\s]/.test(label) || label.includes("://")) return "";
  if (/secret|token|password|credential|api[_-]?key|access[_-]?key|private/i.test(label)) return "";
  return /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(label) ? label : "";
}

const ROLE_RECOMMENDATION_RULES: Array<{
  artifactTokens: string[];
  reason: string;
  roleTokens: string[];
  weight: number;
}> = [
  {
    artifactTokens: ["metadata", "table", "tsv", "tab", "csv"],
    reason: "metadata/table evidence",
    roleTokens: ["metadata"],
    weight: 3,
  },
  {
    artifactTokens: ["barcode", "barcodes", "fastq", "gzip", "gz"],
    reason: "barcode read evidence",
    roleTokens: ["barcode", "barcodes"],
    weight: 3,
  },
  {
    artifactTokens: ["reads", "read", "sequence", "sequences", "fastq", "fasta", "gzip", "gz"],
    reason: "sequence read evidence",
    roleTokens: ["reads", "read", "sequence", "sequences"],
    weight: 3,
  },
  {
    artifactTokens: ["table", "tsv", "tab", "csv"],
    reason: "table evidence",
    roleTokens: ["table"],
    weight: 3,
  },
  {
    artifactTokens: ["report", "html"],
    reason: "report evidence",
    roleTokens: ["report"],
    weight: 3,
  },
  {
    artifactTokens: ["log", "text", "plain"],
    reason: "log evidence",
    roleTokens: ["log"],
    weight: 3,
  },
];
