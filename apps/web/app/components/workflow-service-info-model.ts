export type WorkflowProductionGovernanceCheckStatus =
  | "pass"
  | "pending"
  | "partial"
  | "blocked"
  | "not_applicable"
  | string;

export type WorkflowProductionGovernanceCheck = {
  id?: string;
  status?: WorkflowProductionGovernanceCheckStatus;
  reasonCode?: string;
  blocksCurrentMode?: boolean;
  requiredFor?: string;
  evidence?: string[];
};

export type WorkflowProductionGovernanceReadiness = {
  schemaVersion?: string;
  currentModeStatus?: string;
  publicMultiUserStatus?: string;
  publicMultiUserReady?: boolean;
  currentModeBlockingCheckIds?: string[];
  publicMultiUserBlockingCheckIds?: string[];
  checks?: WorkflowProductionGovernanceCheck[];
};

export type WorkflowLocalServiceInfo = {
  deployment?: {
    mode?: string;
  };
  productionGovernance?: WorkflowProductionGovernanceReadiness;
};

export type WorkflowLocalServiceInfoResponse = {
  item?: unknown;
};
