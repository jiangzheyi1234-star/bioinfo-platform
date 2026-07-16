"use client";

import type { AgentPlanRevision } from "./agent-workbench-model";

export async function sha256Hex(value: ArrayBuffer | string): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) throw new Error("AGENT_WORKBENCH_WEB_CRYPTO_REQUIRED");
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  const digest = await subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, "0")).join("");
}

export async function assertAgentPlanHash(plan: AgentPlanRevision): Promise<void> {
  const payload = {
    budget: plan.budget,
    contractVersion: plan.contractVersion,
    draftId: plan.draftId,
    draftRevision: plan.draftRevision,
    parentPlanRevisionId: plan.parentPlanRevisionId ?? null,
    planGeneration: plan.planGeneration,
    proposal: plan.proposal,
    sessionId: plan.sessionId,
    validation: plan.validation,
  };
  let boundPayload: unknown;
  try {
    boundPayload = JSON.parse(plan.canonicalPayload);
  } catch {
    throw new Error("AGENT_PLAN_CANONICAL_PAYLOAD_INVALID");
  }
  if (!agentJsonEqual(boundPayload, payload)) {
    throw new Error("AGENT_PLAN_CANONICAL_PAYLOAD_MISMATCH");
  }
  const actual = await sha256Hex(plan.canonicalPayload);
  if (actual !== plan.planHash) throw new Error("AGENT_PLAN_CANONICAL_HASH_MISMATCH");
}

export function agentJsonEqual(left: unknown, right: unknown): boolean {
  return canonicalAgentJson(left) === canonicalAgentJson(right);
}

export function canonicalAgentJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error("AGENT_PLAN_CANONICAL_NUMBER_UNSUPPORTED");
    }
    if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
      throw new Error("AGENT_PLAN_CANONICAL_INTEGER_UNSAFE");
    }
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalAgentJson(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record).sort();
    if (keys.some((key) => record[key] === undefined)) {
      throw new Error("AGENT_PLAN_CANONICAL_VALUE_UNSUPPORTED");
    }
    return `{${keys
      .map((key) => `${JSON.stringify(key)}:${canonicalAgentJson(record[key])}`)
      .join(",")}}`;
  }
  throw new Error("AGENT_PLAN_CANONICAL_VALUE_UNSUPPORTED");
}
