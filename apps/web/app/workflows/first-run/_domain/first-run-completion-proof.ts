import type { FirstRunCompletionProof, FirstRunStatus } from "./first-run-types";

const FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION = "h2ometa.first-run.completion-proof.v1";
const MIN_VALIDATION_CHECKS = 10;
const REQUIRED_COMPLETION_PROOF_FIELDS: Array<keyof FirstRunCompletionProof> = [
  "serverId",
  "runId",
  "resultId",
  "workflowRevisionId",
  "packageExportId",
  "packageEvidenceId",
  "resultPackageSha256",
  "resultPackageManifestSha256",
  "validationCardGeneratedAt",
  "validationCardJsonSha256",
  "evidenceBundleId",
  "savedAt",
];
const REQUIRED_REPORT_OUTPUT_NAMES = ["summary.tsv", "qc-summary.tsv", "feature-table.tsv", "run-report.html"];
const REQUIRED_EVIDENCE_BUNDLE_ROLES = [
  "result-package",
  "validation-card-json",
  "validation-card-markdown",
  "pilot-handoff",
];
const REQUIRED_EVIDENCE_BUNDLE_ZIP_ROLES = [
  "completion-proof-json",
  "evidence-bundle-json",
  "pilot-handoff",
  "readme",
  "validation-card-json",
  "validation-card-markdown",
];

export function activeFirstRunCompletionProof(
  status: FirstRunStatus | null | undefined
): FirstRunCompletionProof | undefined {
  const proof = status?.evidence?.completionProof;
  if (!firstRunCompletionProofContractReady(proof)) return undefined;
  const proofRunId = normalizedProofValue(proof.runId);
  if (!proofRunId) return undefined;
  const statusRunId = normalizedProofValue(status?.evidence?.run?.runId || status?.latestEligibleRun?.runId);
  if (statusRunId && statusRunId !== proofRunId) return undefined;
  const proofServerId = normalizedProofValue(proof.serverId);
  const statusServerId = normalizedProofValue(status?.serverId);
  if (proofServerId && statusServerId && proofServerId !== statusServerId) return undefined;
  if (statusRunId === proofRunId) return proof;
  return undefined;
}

export function firstRunCompletionProofReady(status: FirstRunStatus | null | undefined): boolean {
  return Boolean(activeFirstRunCompletionProof(status));
}

function firstRunCompletionProofContractReady(proof: FirstRunCompletionProof | undefined): proof is FirstRunCompletionProof {
  if (proof?.ready !== true) return false;
  if (normalizedProofValue(proof.schemaVersion) !== FIRST_RUN_COMPLETION_PROOF_SCHEMA_VERSION) return false;
  if (REQUIRED_COMPLETION_PROOF_FIELDS.some((field) => !normalizedProofValue(proof[field]))) return false;
  if (![proof.resultPackageSha256, proof.resultPackageManifestSha256, proof.validationCardJsonSha256].every(validSha256)) {
    return false;
  }
  const generatedAt = utcTimestampMs(proof.validationCardGeneratedAt);
  const savedAt = utcTimestampMs(proof.savedAt);
  if (generatedAt === null || savedAt === null || savedAt < generatedAt) return false;
  const validationChecksPassed = proof.validationChecksPassed;
  const validationChecksTotal = proof.validationChecksTotal;
  if (!validProofCount(validationChecksPassed) || !validProofCount(validationChecksTotal)) return false;
  if (validationChecksPassed !== validationChecksTotal) return false;
  if (validationChecksTotal < MIN_VALIDATION_CHECKS) return false;
  if (proof.reportReady !== true) return false;
  if (!exactProofSet(proof.reportOutputNames, REQUIRED_REPORT_OUTPUT_NAMES)) return false;
  if (proof.evidenceBundleReady !== true) return false;
  if (!exactProofSet(proof.evidenceBundleFileRoles, REQUIRED_EVIDENCE_BUNDLE_ROLES)) return false;
  if (!exactProofSet(proof.evidenceBundleZipFileRoles, REQUIRED_EVIDENCE_BUNDLE_ZIP_ROLES)) return false;
  const proofRunId = normalizedProofValue(proof.runId);
  const proofResultId = normalizedProofValue(proof.resultId);
  if (proofResultId !== canonicalResultId(proofRunId)) return false;
  if (normalizedProofValue(proof.evidenceBundleId) !== `${proofResultId}.first-run-evidence`) return false;
  return true;
}

function validSha256(value: unknown): boolean {
  return /^[0-9a-f]{64}$/.test(normalizedProofValue(value).toLowerCase());
}

function validProofCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function utcTimestampMs(value: unknown): number | null {
  const normalized = normalizedProofValue(value);
  if (!normalized) return null;
  if (!normalized.endsWith("Z") && !normalized.endsWith("+00:00") && !normalized.endsWith("-00:00")) return null;
  const parsed = Date.parse(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function exactProofSet(values: string[] | undefined, required: readonly string[]): boolean {
  if (!Array.isArray(values)) return false;
  const normalizedValues = values.map(normalizedProofValue);
  const valueSet = new Set(normalizedValues);
  return (
    valueSet.size === required.length &&
    normalizedValues.length === required.length &&
    required.every((value) => valueSet.has(value))
  );
}

function canonicalResultId(runId: string): string {
  return runId.startsWith("res_") ? runId : `res_${runId}`;
}

function normalizedProofValue(value: unknown): string {
  return String(value || "").trim();
}
