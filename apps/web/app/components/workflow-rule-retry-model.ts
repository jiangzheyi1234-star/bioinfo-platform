import type { WorkflowRunRuleRetryExecutionPlan } from "./workflows-page-model";

export type WorkflowRuleRetryRequest = {
  planHash: string;
};

export type WorkflowRuleRetryResult = {
  schemaVersion?: string;
  runId?: string;
  accepted?: boolean;
  blocked?: boolean;
  status?: string;
  stage?: string;
  scope?: string;
  commandId?: string;
  jobId?: string;
  selectedRuleCount?: number;
  rerunRuleCount?: number;
  remainingAttempts?: number;
  availableAt?: string;
  retryRequestedAt?: string;
  planHash?: string;
};

export type WorkflowRuleRetryResponse = {
  data: WorkflowRuleRetryResult;
};

export function workflowRuleRetryCanSubmit(plan?: WorkflowRunRuleRetryExecutionPlan) {
  const readiness = plan?.activationReadiness;
  const orchestration = plan?.executorOrchestration;
  const launch = orchestration?.launchPreflight;
  const boundary = orchestration?.executionBoundary;
  return Boolean(
    plan?.executionEnabled === true &&
      plan.eligibleNow === true &&
      plan.planHash &&
      plan.planHash.length === 64 &&
      (plan.selectedRules?.length || 0) > 0 &&
      readiness?.executionReady === true &&
      readiness.executionEnabled === true &&
      (readiness.blockedCheckCount || 0) === 0 &&
      readiness.redactionPolicy?.pathsExposed !== true &&
      readiness.redactionPolicy?.storageUrisExposed !== true &&
      orchestration?.contractReady === true &&
      orchestration.executorReady === true &&
      orchestration.queueMutationAllowed === true &&
      orchestration.runStateMutationAllowed === true &&
      orchestration.launchReady === true &&
      orchestration.executionBoundaryReady === true &&
      orchestration.pathExposed !== true &&
      orchestration.storageUriExposed !== true &&
      launch?.preflightReady === true &&
      launch.launchReady === true &&
      launch.executorStartAllowed === true &&
      launch.queueMutationAllowed === true &&
      launch.runStateMutationAllowed === true &&
      launch.pathExposed !== true &&
      launch.storageUriExposed !== true &&
      boundary?.boundaryReady === true &&
      boundary.executorStartAllowed === true &&
      boundary.queueMutationAllowed === true &&
      boundary.runStateMutationAllowed === true &&
      boundary.pathExposed !== true &&
      boundary.storageUriExposed !== true
  );
}
