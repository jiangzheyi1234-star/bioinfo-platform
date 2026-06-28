export const HARD_COMPATIBILITY_FIELDS = ["type", "kind", "mimeType", "data", "format", "resource"] as const;
export const ADVISORY_COMPATIBILITY_FIELDS = ["operation"] as const;
export const COMPATIBILITY_FIELDS = [...HARD_COMPATIBILITY_FIELDS, ...ADVISORY_COMPATIBILITY_FIELDS] as const;

const EDAM_COMPATIBILITY_FIELDS = new Set<RulePortCompatibilityField>(["data", "format", "operation"]);
const EDAM_FIELD_PREFIXES: Partial<Record<RulePortCompatibilityField, string>> = {
  data: "data",
  format: "format",
  operation: "operation",
};
const UNSUPPORTED_GENERIC_EDAM_VALUES: Partial<Record<RulePortCompatibilityField, Set<string>>> = {
  data: new Set(["data_0006"]),
  format: new Set(["format_1915"]),
};

export type RulePortCompatibilityField = (typeof COMPATIBILITY_FIELDS)[number];
export type RulePortCompatibilitySpec = Partial<Record<RulePortCompatibilityField, string>>;
export type RulePortCompatibilityDecision = {
  compatible: boolean;
  score: number | null;
  matchedFields: RulePortCompatibilityField[];
  genericFields: RulePortCompatibilityField[];
  advisoryFields: RulePortCompatibilityField[];
  mismatchedField?: RulePortCompatibilityField;
  hardChecks: string[];
  advisoryChecks: string[];
};

export function readPortCompatibility(item: Record<string, unknown>): RulePortCompatibilitySpec {
  const spec: RulePortCompatibilitySpec = {};
  for (const field of COMPATIBILITY_FIELDS) {
    const value = stringValue(item[field]);
    if (value) spec[field] = value;
  }
  return spec;
}

export function describePortCompatibility(
  input: RulePortCompatibilitySpec,
  output: RulePortCompatibilitySpec
): string {
  const mismatch = mismatchedPortCompatibilityField(input, output);
  if (mismatch) {
    return `不兼容: ${compatibilityFieldLabel(mismatch)} 不一致`;
  }
  const genericFields = genericPortCompatibilityFields(input, output);
  if (genericFields.length > 0) {
    return `不兼容: ${genericFields.map(compatibilityFieldLabel).join(" / ")} 使用泛化 EDAM 根术语`;
  }
  const matched = matchedPortCompatibilityFields(input, output);
  const referenced: RulePortCompatibilityField[] = [];
  for (const field of HARD_COMPATIBILITY_FIELDS) {
    const inputValue = stringValue(input[field]);
    const outputValue = stringValue(output[field]);
    if (Boolean(inputValue) !== Boolean(outputValue)) referenced.push(field);
  }
  if (matched.length > 0) {
    return `匹配 ${matched.map(compatibilityFieldLabel).join(" / ")}`;
  }
  if (referenced.length > 0) {
    return `参考 ${referenced.map(compatibilityFieldLabel).join(" / ")}`;
  }
  return "未声明类型，允许手动连接";
}

export function portsCompatible(input: RulePortCompatibilitySpec, output: RulePortCompatibilitySpec): boolean {
  return portCompatibilityDecision(input, output).compatible;
}

export function portCompatibilityDecision(
  input: RulePortCompatibilitySpec,
  output: RulePortCompatibilitySpec
): RulePortCompatibilityDecision {
  const mismatchedField = mismatchedPortCompatibilityField(input, output);
  const score = portCompatibilityScore(input, output);
  const genericFields = genericPortCompatibilityFields(input, output);
  const advisoryFields = matchedAdvisoryPortCompatibilityFields(input, output);
  return {
    compatible: score !== null,
    score,
    matchedFields: matchedPortCompatibilityFields(input, output),
    genericFields,
    advisoryFields,
    ...(mismatchedField ? { mismatchedField } : {}),
    hardChecks: hardCompatibilityChecks(mismatchedField, genericFields),
    advisoryChecks: advisoryCompatibilityChecks(advisoryFields),
  };
}

export function portCompatibilityScore(
  input: RulePortCompatibilitySpec,
  output: RulePortCompatibilitySpec
): number | null {
  let score = 0;
  for (const field of HARD_COMPATIBILITY_FIELDS) {
    const inputValue = normalizedCompatibilityValue(field, input[field]);
    const outputValue = normalizedCompatibilityValue(field, output[field]);
    const relation = compatibilityRelation(field, inputValue, outputValue);
    if (relation === "conflict" || relation === "generic") return null;
    if (relation === "exact") score += 4;
    else if (inputValue || outputValue) score += 1;
  }
  return score;
}

export function matchedPortCompatibilityFields(
  input: RulePortCompatibilitySpec,
  output: RulePortCompatibilitySpec
): RulePortCompatibilityField[] {
  return HARD_COMPATIBILITY_FIELDS.filter((field) => {
    const inputValue = normalizedCompatibilityValue(field, input[field]);
    return Boolean(inputValue && inputValue === normalizedCompatibilityValue(field, output[field]));
  });
}

export function genericPortCompatibilityFields(
  input: RulePortCompatibilitySpec,
  output: RulePortCompatibilitySpec
): RulePortCompatibilityField[] {
  return HARD_COMPATIBILITY_FIELDS.filter((field) => {
    const inputValue = normalizedCompatibilityValue(field, input[field]);
    const outputValue = normalizedCompatibilityValue(field, output[field]);
    return compatibilityRelation(field, inputValue, outputValue) === "generic";
  });
}

export function matchedAdvisoryPortCompatibilityFields(
  input: RulePortCompatibilitySpec,
  output: RulePortCompatibilitySpec
): RulePortCompatibilityField[] {
  return ADVISORY_COMPATIBILITY_FIELDS.filter((field) => {
    const inputValue = normalizedCompatibilityValue(field, input[field]);
    return Boolean(inputValue && inputValue === normalizedCompatibilityValue(field, output[field]) && !isInvalidEdamValue(field, inputValue));
  });
}

export function mismatchedPortCompatibilityField(
  input: RulePortCompatibilitySpec,
  output: RulePortCompatibilitySpec
): RulePortCompatibilityField | undefined {
  return HARD_COMPATIBILITY_FIELDS.find((field) => {
    const inputValue = normalizedCompatibilityValue(field, input[field]);
    const outputValue = normalizedCompatibilityValue(field, output[field]);
    return compatibilityRelation(field, inputValue, outputValue) === "conflict";
  });
}

export function normalizedCompatibilityValue(field: RulePortCompatibilityField, value: unknown): string {
  const text = stringValue(value);
  if (!text) return "";
  if (!EDAM_COMPATIBILITY_FIELDS.has(field)) return text;
  const withoutUri = text.includes("/") ? text.split("/").at(-1) || text : text;
  return withoutUri.replace(/^EDAM:/i, "");
}

function compatibilityRelation(
  field: RulePortCompatibilityField,
  inputValue: string,
  outputValue: string
): "exact" | "generic" | "conflict" | "missing" {
  if (inputValue && outputValue && isGenericEdamValue(field, inputValue, outputValue)) return "generic";
  if ((inputValue && isInvalidEdamValue(field, inputValue)) || (outputValue && isInvalidEdamValue(field, outputValue))) {
    return "conflict";
  }
  if (inputValue && outputValue && inputValue === outputValue) return "exact";
  if (inputValue && outputValue) return "conflict";
  return "missing";
}

function isGenericEdamValue(field: RulePortCompatibilityField, left: string, right: string): boolean {
  const generic = UNSUPPORTED_GENERIC_EDAM_VALUES[field];
  return Boolean(generic?.has(left) || generic?.has(right));
}

function isInvalidEdamValue(field: RulePortCompatibilityField, value: string): boolean {
  const prefix = EDAM_FIELD_PREFIXES[field];
  if (!prefix || !value) return false;
  return !new RegExp(`^${prefix}_\\d+$`).test(value);
}

function hardCompatibilityChecks(
  mismatchedField: RulePortCompatibilityField | undefined,
  genericFields: RulePortCompatibilityField[]
): string[] {
  if (mismatchedField) return ["port-direction:output-to-input", `${mismatchedField}:conflict`];
  if (genericFields.length > 0) {
    return ["port-direction:output-to-input", ...genericFields.map((field) => `${field}:generic-root-unsupported`)];
  }
  return [
    "port-direction:output-to-input",
    "semantic-fields-compatible",
  ];
}

function advisoryCompatibilityChecks(advisoryFields: RulePortCompatibilityField[]): string[] {
  return advisoryFields.map((field) => `${field}:advisory-compatible`);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function compatibilityFieldLabel(field: RulePortCompatibilityField): string {
  return field === "mimeType" ? "MIME" : field;
}
