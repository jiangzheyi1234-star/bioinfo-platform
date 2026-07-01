"use client";

export const DEFAULT_GC_RETENTION_DAYS = "30";
export const DEFAULT_GC_REASON = "retention_expired";
export const DEFAULT_GC_POLICY_ID = "request";
export const DEFAULT_GC_POLICY_VERSION = 0;
export const DEFAULT_ELIGIBLE_RUN_STATUSES = ["canceled", "cancelled", "completed", "failed"];

const ARTIFACT_LIFECYCLE_REASON_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;

export type ArtifactGcPolicyInput = {
  retentionDays: number;
  eligibleRunStatuses: string[];
  quotaBytes?: number | null;
  maxDeleteBytesPerTick?: number | null;
  reason: string;
};

export async function artifactLifecyclePolicyFingerprint(policy: ArtifactGcPolicyInput) {
  if (!globalThis.crypto?.subtle) {
    throw new Error("当前浏览器不支持 Web Crypto，无法生成 artifact lifecycle policy fingerprint。");
  }
  const encoded = new TextEncoder().encode(artifactLifecyclePolicyFingerprintJson(policy));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", encoded);
  const hex = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `alpfp_${hex}`;
}

export function normalizeArtifactGcReason(reasonInput: string) {
  const reason = reasonInput.trim();
  if (!ARTIFACT_LIFECYCLE_REASON_PATTERN.test(reason)) {
    throw new Error("GC 原因必须以字母或数字开头，且只能包含字母、数字、点、下划线、冒号或短横线。");
  }
  return reason;
}

export function parseRequiredNonNegativeInteger(value: string, label: string) {
  const parsed = parseOptionalNonNegativeInteger(value, label);
  if (parsed === undefined) {
    throw new Error(`${label}不能为空`);
  }
  return parsed;
}

export function parseOptionalPositiveInteger(value: string, label: string) {
  const normalized = value.trim();
  if (!normalized) return undefined;
  if (!/^\d+$/.test(normalized)) {
    throw new Error(`${label}必须是正整数`);
  }
  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${label}必须是正整数`);
  }
  return parsed;
}

export function parseOptionalNonNegativeInteger(value: string, label: string) {
  const normalized = value.trim();
  if (!normalized) return undefined;
  if (!/^\d+$/.test(normalized)) {
    throw new Error(`${label}必须是非负整数`);
  }
  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed)) {
    throw new Error(`${label}必须是非负整数`);
  }
  return parsed;
}

function artifactLifecyclePolicyFingerprintJson(policy: ArtifactGcPolicyInput) {
  const eligibleRunStatuses = [...policy.eligibleRunStatuses].sort();
  return [
    '{"eligibleRunStatuses":[',
    eligibleRunStatuses.map((item) => JSON.stringify(item)).join(","),
    '],"maxDeleteBytesPerTick":',
    optionalNumberJson(policy.maxDeleteBytesPerTick),
    ',"quotaBytes":',
    optionalNumberJson(policy.quotaBytes),
    ',"reason":',
    JSON.stringify(policy.reason),
    ',"retentionDays":',
    String(policy.retentionDays),
    "}",
  ].join("");
}

function optionalNumberJson(value?: number | null) {
  return value === undefined || value === null ? "null" : String(value);
}
