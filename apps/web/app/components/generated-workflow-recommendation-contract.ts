import {
  describePortCompatibility,
  portCompatibilityDecision,
  type RulePortCompatibilityField,
  type RulePortCompatibilitySpec,
} from "./generated-workflow-port-contract";

export type RulePortRecommendationDecision = "recommended" | "blocked" | "ambiguous";

export type RulePortRecommendation = {
  decision: RulePortRecommendationDecision;
  hardChecks: string[];
  evidence: string[];
  confidence: number;
  reason: string;
};

export type RulePortEdgeAudit = {
  source: "auto" | "manual";
  decision: RulePortRecommendationDecision | "manual";
  hardChecks: string[];
  evidence: string[];
  confidence: number;
  reason: string;
};

type RulePortRecommendationPort = RulePortCompatibilitySpec & {
  name?: string;
  required?: boolean;
};

export function explainPortRecommendation(
  input: RulePortRecommendationPort,
  output: RulePortRecommendationPort
): RulePortRecommendation {
  const compatibility = describePortCompatibility(input, output);
  const compatibilityDecision = portCompatibilityDecision(input, output);
  const mismatch = compatibilityDecision.mismatchedField;
  if (mismatch) {
    return {
      decision: "blocked",
      hardChecks: compatibilityDecision.hardChecks,
      evidence: [compatibility],
      confidence: 0,
      reason: compatibility,
    };
  }

  const matched = compatibilityDecision.matchedFields;
  const strongMatched = matched.filter((field) => field !== "type");
  const hasStrongEvidence = strongMatched.length > 0;
  const evidence = [
    hasStrongEvidence ? compatibility : "类型证据不足，保留为手动连接",
    hasStrongEvidence ? portNameEvidence(input, output) : "",
    hasStrongEvidence ? (input.required !== false ? "目标 input 为必填端口" : "目标 input 为可选端口") : "",
    hasStrongEvidence ? advisoryEvidence(compatibilityDecision.advisoryChecks) : "",
  ].filter((value): value is string => Boolean(value));
  const recommendationDecision = hasStrongEvidence ? "recommended" : "ambiguous";
  return {
    decision: recommendationDecision,
    hardChecks: compatibilityDecision.hardChecks,
    evidence,
    confidence: hasStrongEvidence
      ? recommendationConfidence({ matchedFields: strongMatched.length, required: input.required !== false })
      : 0.2,
    reason: compatibility,
  };
}

export function isAutoBindablePortRecommendation(recommendation: RulePortRecommendation): boolean {
  return recommendation.decision === "recommended";
}

export function autoEdgeAudit(recommendation: RulePortRecommendation): RulePortEdgeAudit {
  return { source: "auto", ...recommendation };
}

export function manualEdgeAudit(): RulePortEdgeAudit {
  return {
    source: "manual",
    decision: "manual",
    hardChecks: ["用户手动选择上游输出"],
    evidence: ["手动连接"],
    confidence: 1,
    reason: "手动连接",
  };
}

function portNameEvidence(input: RulePortRecommendationPort, output: RulePortRecommendationPort): string {
  const inputName = stringValue(input.name);
  const outputName = stringValue(output.name);
  if (!inputName || !outputName || inputName !== outputName) return "";
  return `端口名相同: ${inputName}`;
}

function advisoryEvidence(checks: string[]): string {
  if (checks.length === 0) return "";
  return `辅助语义匹配: ${checks.join(" / ")}`;
}

function recommendationConfidence({
  matchedFields,
  required,
}: {
  matchedFields: number;
  required: boolean;
}) {
  const score = 0.35 + matchedFields * 0.1 + (required ? 0.05 : 0);
  return Math.min(0.95, Number(score.toFixed(2)));
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function compatibilityFieldLabel(field: RulePortCompatibilityField): string {
  return field === "mimeType" ? "MIME" : field;
}
