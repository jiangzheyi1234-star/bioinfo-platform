export type WorkflowRunRulesSummary = {
  schemaVersion?: string;
  ruleCount?: number;
  ruleEventCount?: number;
  statusCounts?: Record<string, number>;
  failedRuleCount?: number;
  runningRuleCount?: number;
  blockedRuleCount?: number;
  rulesWithAttemptMetadata?: number;
  inputReferenceCount?: number;
  outputReferenceCount?: number;
  logReferenceCount?: number;
  rulesWithLogReferences?: number;
  rulesWithAvailableLogEvidence?: number;
  rulesWithPathOnlyLogEvidence?: number;
  rulesWithUnavailableLogEvidence?: number;
  logEvidenceStatusCounts?: Record<string, number>;
  logEvidenceReasonCodes?: Record<string, number>;
};
