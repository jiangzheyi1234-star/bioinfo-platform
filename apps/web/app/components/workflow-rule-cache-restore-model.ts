import type { WorkflowRunRuleCacheRestorePlan } from "./workflows-page-model";

export type WorkflowRuleCacheRestoreStage =
  | "pins"
  | "staged-files"
  | "final-outputs"
  | "adoption";

export type WorkflowRuleCacheRestoreAction = "prepare" | "apply";

export type WorkflowRuleCacheRestoreRequest = {
  stage: WorkflowRuleCacheRestoreStage;
  action: WorkflowRuleCacheRestoreAction;
  planHash: string;
  attemptId: string;
  leaseGeneration: number;
};

export type WorkflowRuleCacheRestoreResult = {
  schemaVersion?: string;
  runId?: string;
  planHash?: string;
  status?: string;
  evidenceId?: string;
  attemptId?: string;
  leaseGeneration?: number;
  eligiblePinCount?: number;
  preparedPinCount?: number;
  appliedPinCount?: number;
  createdPinCount?: number;
  reusedPinCount?: number;
  cacheEntryCount?: number;
  targetCount?: number;
  stagedFileCount?: number;
  finalOutputCount?: number;
  candidateOutputCount?: number;
  verifiedCandidateOutputCount?: number;
  adoptedArtifactCount?: number;
  pendingAdoptionCount?: number;
  releasedPinCount?: number;
  activePinCount?: number;
  runStateMutated?: boolean;
  retryEnqueued?: boolean;
  artifactIdsExposed?: boolean;
  ownerIdExposed?: boolean;
  cacheKeyExposed?: boolean;
  storageUriExposed?: boolean;
  pathExposed?: boolean;
};

export type WorkflowRuleCacheRestoreResponse = {
  data: WorkflowRuleCacheRestoreResult;
};

export function workflowRuleCacheRestorePlanReady(plan?: WorkflowRunRuleCacheRestorePlan) {
  return Boolean(plan?.planHash && plan.cacheHitCount && plan.cacheHitCount > 0);
}
