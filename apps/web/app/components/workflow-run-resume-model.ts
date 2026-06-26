import type { WorkflowRunResumePlan } from "./workflows-page-model";

export type WorkflowRunResumeRequest = {
  planHash: string;
};

export type WorkflowRunResumeResult = {
  schemaVersion?: string;
  runId?: string;
  accepted?: boolean;
  blocked?: boolean;
  status?: string;
  stage?: string;
  scope?: string;
  commandId?: string;
  jobId?: string;
  remainingAttempts?: number;
  availableAt?: string;
  resumeRequestedAt?: string;
  planHash?: string;
  reasonCode?: string;
};

export type WorkflowRunResumeResponse = {
  data: WorkflowRunResumeResult;
};

export function workflowRunResumeCanSubmit(plan?: WorkflowRunResumePlan) {
  const readiness = plan?.activationReadiness;
  const workdir = plan?.workdirEvidence;
  const outputAudit = plan?.incompleteOutputAudit;
  const adoption = plan?.artifactAdoptionBoundary;
  const orchestration = plan?.executorOrchestration;
  return Boolean(
    plan?.executionEnabled === true &&
      plan.eligibleNow === true &&
      plan.commandPreviewAvailable === true &&
      plan.planHash &&
      plan.planHash.length === 64 &&
      readiness?.executionReady === true &&
      readiness.executionEnabled === true &&
      (readiness.blockedCheckCount || 0) === 0 &&
      readiness.redactionPolicy?.pathsExposed !== true &&
      readiness.redactionPolicy?.storageUrisExposed !== true &&
      workdir?.workDirReusable === true &&
      workdir.pathExposed !== true &&
      outputAudit?.available === true &&
      (outputAudit.unsafeOutputCount || 0) === 0 &&
      (outputAudit.uncheckedOutputCount || 0) === 0 &&
      (outputAudit.unverifiedOutputCount || 0) === 0 &&
      outputAudit.pathExposed !== true &&
      (adoption?.enabled === true || adoption?.available === true) &&
      adoption.pathExposed !== true &&
      adoption.storageUriExposed !== true &&
      adoption.checksumValueExposed !== true &&
      orchestration?.contractReady === true &&
      orchestration.executorReady === true &&
      orchestration.queueMutationAllowed === true &&
      orchestration.runStateMutationAllowed === true &&
      orchestration.pathExposed !== true &&
      orchestration.storageUriExposed !== true
  );
}
