import {
  COMPATIBILITY_FIELDS,
  describePortCompatibility,
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
  const mismatch = mismatchedField(input, output);
  if (mismatch) {
    return {
      decision: "blocked",
      hardChecks: ["端口方向 output -> input", `${compatibilityFieldLabel(mismatch)} 字段必须兼容`],
      evidence: [compatibility],
      confidence: 0,
      reason: compatibility,
    };
  }

  const matched = matchedFields(input, output);
  const hasStrongEvidence = matched.length > 0;
  const evidence = [
    hasStrongEvidence ? compatibility : "类型证据不足，保留为手动连接",
    hasStrongEvidence ? portNameEvidence(input, output) : "",
    hasStrongEvidence ? (input.required !== false ? "目标 input 为必填端口" : "目标 input 为可选端口") : "",
  ].filter((value): value is string => Boolean(value));
  const decision = hasStrongEvidence ? "recommended" : "ambiguous";
  return {
    decision,
    hardChecks: ["端口方向 output -> input", "类型字段无冲突"],
    evidence,
    confidence: hasStrongEvidence
      ? recommendationConfidence({ matchedFields: matched.length, required: input.required !== false })
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

function matchedFields(input: RulePortRecommendationPort, output: RulePortRecommendationPort): RulePortCompatibilityField[] {
  return COMPATIBILITY_FIELDS.filter((field) => stringValue(input[field]) && stringValue(input[field]) === stringValue(output[field]));
}

function mismatchedField(
  input: RulePortRecommendationPort,
  output: RulePortRecommendationPort
): RulePortCompatibilityField | undefined {
  return COMPATIBILITY_FIELDS.find((field) => {
    const inputValue = stringValue(input[field]);
    const outputValue = stringValue(output[field]);
    return Boolean(inputValue && outputValue && inputValue !== outputValue);
  });
}

function portNameEvidence(input: RulePortRecommendationPort, output: RulePortRecommendationPort): string {
  const inputName = stringValue(input.name);
  const outputName = stringValue(output.name);
  if (!inputName || !outputName || inputName !== outputName) return "";
  return `端口名相同: ${inputName}`;
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
