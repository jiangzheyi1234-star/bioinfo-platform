import type { FirstRunCompletionProof, FirstRunStatus } from "./first-run-types";

export function activeFirstRunCompletionProof(
  status: FirstRunStatus | null | undefined
): FirstRunCompletionProof | undefined {
  const proof = status?.evidence?.completionProof;
  if (proof?.ready !== true) return undefined;
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

function normalizedProofValue(value: string | undefined): string {
  return String(value || "").trim();
}
