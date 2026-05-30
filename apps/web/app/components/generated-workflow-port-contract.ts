export const COMPATIBILITY_FIELDS = ["type", "kind", "mimeType", "data", "format"] as const;

export type RulePortCompatibilityField = (typeof COMPATIBILITY_FIELDS)[number];
export type RulePortCompatibilitySpec = Partial<Record<RulePortCompatibilityField, string>>;

export function readPortCompatibility(item: Record<string, unknown>): RulePortCompatibilitySpec {
  const spec: RulePortCompatibilitySpec = {};
  for (const field of COMPATIBILITY_FIELDS) {
    const value = stringValue(item[field]);
    if (value) spec[field] = value;
  }
  if (!spec.format) {
    const value = stringValue(item.edamFormat);
    if (value) spec.format = value;
  }
  if (!spec.data) {
    const value = stringValue(item.edamData);
    if (value) spec.data = value;
  }
  return spec;
}

export function describePortCompatibility(
  input: RulePortCompatibilitySpec,
  output: RulePortCompatibilitySpec
): string {
  const matched: RulePortCompatibilityField[] = [];
  const referenced: RulePortCompatibilityField[] = [];
  for (const field of COMPATIBILITY_FIELDS) {
    const inputValue = stringValue(input[field]);
    const outputValue = stringValue(output[field]);
    if (inputValue && outputValue && inputValue !== outputValue) {
      return `不兼容: ${compatibilityFieldLabel(field)} 不一致`;
    }
    if (inputValue && outputValue) matched.push(field);
    else if (inputValue || outputValue) referenced.push(field);
  }
  if (matched.length > 0) {
    return `匹配 ${matched.map(compatibilityFieldLabel).join(" / ")}`;
  }
  if (referenced.length > 0) {
    return `参考 ${referenced.map(compatibilityFieldLabel).join(" / ")}`;
  }
  return "未声明类型，允许手动连接";
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function compatibilityFieldLabel(field: RulePortCompatibilityField): string {
  return field === "mimeType" ? "MIME" : field;
}
