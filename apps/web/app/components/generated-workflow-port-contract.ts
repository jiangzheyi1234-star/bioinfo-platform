import type { AddedTool, ToolCapability, ToolCapabilitySlot } from "./tools-page-model";

export const COMPATIBILITY_FIELDS = ["type", "kind", "mimeType", "data", "format"] as const;

export type RulePortCompatibilityField = (typeof COMPATIBILITY_FIELDS)[number];
export type RulePortCompatibilitySpec = Partial<Record<RulePortCompatibilityField, string>>;
export type RulePortCapabilityMetadata = {
  capabilityId?: string;
  capabilityLabel?: string;
  capabilityOperation?: string;
};

export type CapabilityPortSlot = ToolCapabilitySlot & RulePortCapabilityMetadata;

export function capabilityPortItemsForTool(
  tool: AddedTool | undefined,
  direction: "inputs" | "outputs"
): Array<Record<string, unknown> & CapabilityPortSlot> {
  return capabilitySlotsForTool(tool, direction).map((slot, index) => ({
    ...slot,
    name: slot.name || `${direction === "inputs" ? "input" : "output"}_${index + 1}`,
  }));
}

export function capabilitySlotForRulePort(
  tool: AddedTool | undefined,
  direction: "inputs" | "outputs",
  name: string,
  fallbackIndex: number
): CapabilityPortSlot | undefined {
  const normalizedName = name.trim();
  const slots = capabilitySlotsForTool(tool, direction);
  if (normalizedName) {
    const exact = slots.find((slot) => slot.name === normalizedName);
    if (exact) return exact;
  }
  const genericPrimaryName = ["primary", "tool_output", "output"].includes(normalizedName);
  const primary = slots.find((slot) => slot.primary === true);
  if (primary && (fallbackIndex === 0 || genericPrimaryName)) return primary;
  return slots[fallbackIndex];
}

export function readPortCompatibility(
  item: Record<string, unknown>,
  capabilitySlot?: ToolCapabilitySlot
): RulePortCompatibilitySpec {
  const spec: RulePortCompatibilitySpec = {};
  for (const field of COMPATIBILITY_FIELDS) {
    const value = stringValue(item[field]) || stringValue(capabilitySlot?.[field]);
    if (value) spec[field] = value;
  }
  if (!spec.format) {
    const value = stringValue(item.edamFormat) || stringValue(capabilitySlot?.edamFormat);
    if (value) spec.format = value;
  }
  if (!spec.data) {
    const value = stringValue(item.edamData) || stringValue(capabilitySlot?.edamData);
    if (value) spec.data = value;
  }
  return spec;
}

export function readCapabilityMetadata(
  item: Record<string, unknown>,
  capabilitySlot?: ToolCapabilitySlot
): RulePortCapabilityMetadata {
  const slot = capabilitySlot as CapabilityPortSlot | undefined;
  const capabilityId = stringValue(item.capabilityId) || stringValue(slot?.capabilityId);
  const capabilityLabel = stringValue(item.capabilityLabel) || stringValue(slot?.capabilityLabel);
  const capabilityOperation = stringValue(item.capabilityOperation) || stringValue(slot?.capabilityOperation);
  return {
    ...(capabilityId ? { capabilityId } : {}),
    ...(capabilityLabel ? { capabilityLabel } : {}),
    ...(capabilityOperation ? { capabilityOperation } : {}),
  };
}

function capabilitySlotsForTool(tool: AddedTool | undefined, direction: "inputs" | "outputs"): CapabilityPortSlot[] {
  return (tool?.capabilities || []).flatMap((capability: ToolCapability) =>
    (capability[direction] || []).map((slot) => ({
      ...slot,
      capabilityId: capability.id,
      capabilityLabel: capability.label || capability.operation || capability.id,
      capabilityOperation: capability.operation,
    }))
  );
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
