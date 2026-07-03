export type WorkflowArtifact = {
  artifactId: string;
  kind: string;
  mimeType: string;
  sizeBytes: number;
  sha256?: string;
};

export type WorkflowRunSourceLocation = {
  schemaVersion?: string;
  sourceKind?: string;
  fileBasename?: string;
  fileHash?: string;
  line?: number;
};

export type WorkflowRunRuleEvent = {
  ruleEventId?: string;
  runId?: string;
  runRuleId?: string;
  ruleName?: string;
  stepId?: string;
  eventType?: string;
  status?: string;
  attemptId?: string;
  leaseGeneration?: number;
  attemptNumber?: number;
  message?: string;
  createdAt?: string;
  details?: Record<string, unknown>;
  sourceLocation?: WorkflowRunSourceLocation;
};

export type WorkflowRunRuleLogContext = {
  schemaVersion?: string;
  status?: "available" | "unavailable" | string;
  reasonCode?:
    | "PREVIEW_AVAILABLE"
    | "NO_FAILED_RULE"
    | "NO_RULE_LOGS"
    | "PATH_REFERENCE_ONLY"
    | "MATCHED_ARTIFACT_NOT_PREVIEWABLE"
    | "RESULT_ID_MISSING"
    | "PREVIEW_UNAVAILABLE"
    | string;
  message?: string;
  logReferenceCount?: number;
  matchedArtifactCount?: number;
  matchedArtifacts?: WorkflowArtifact[];
  selectedArtifact?: WorkflowArtifact;
  previewKind?: string;
  lineCount?: number;
  tail?: string[];
  truncated?: boolean;
};
