import type { WorkflowResultPackageExport } from "@/app/components/workflows-page-model";

export type FirstRunValidationMetric = {
  metricId?: string;
  label?: string;
  value?: number | string;
  displayValue?: string;
  source?: string;
};

export type FirstRunValidationOutput = {
  name?: string;
  label?: string;
  kind?: string;
  present?: boolean;
  artifactId?: string;
  sha256?: string;
  interpretation?: string;
};

export type FirstRunValidationKeyResult = {
  artifactId?: string;
  artifactKey?: string;
  displayName?: string;
  kind?: string;
  mimeType?: string;
  sizeBytes?: number;
  sha256?: string;
};

export type FirstRunValidationCheck = {
  code?: string;
  status?: string;
  detail?: string;
};

export type FirstRunReportInterpretation = {
  schemaVersion?: string;
  status?: string;
  summary?: string;
  outputs?: FirstRunValidationOutput[];
  metrics?: FirstRunValidationMetric[];
  redaction?: {
    rawPathsExposed?: boolean;
    storageUrisExposed?: boolean;
    previewRowsEmbedded?: boolean;
    policy?: string;
  };
};

export type FirstRunSampleDataItem = {
  role?: string;
  filename?: string;
  sourceUrl?: string;
  prepProof?: FirstRunSamplePrepProofItem;
  uploadId?: string;
  artifactBlobId?: string;
  sha256?: string;
  expectedSha256?: string;
  sizeBytes?: number;
  expectedSizeBytes?: number;
  integrityStatus?: "passed" | string;
};

export type FirstRunSamplePrepProofItem = {
  schemaVersion?: string;
  role?: string;
  filename?: string;
  sourceUrl?: string;
  sha256?: string;
  expectedSha256?: string;
  expectedSizeBytes?: number;
  cacheStatus?: string;
  downloadStatus?: string;
  downloadAttempts?: number;
};

export type FirstRunSampleDataEvidence = {
  schemaVersion?: string;
  source?: string;
  status?: string;
  prepProof?: {
    schemaVersion?: string;
    source?: string;
    cachePolicy?: string;
    items?: FirstRunSamplePrepProofItem[];
  };
  items?: FirstRunSampleDataItem[];
};

export type FirstRunSoftwareEnvironment = {
  schemaVersion?: string;
  status?: string;
  workflowRevisionId?: string;
  contentHash?: string;
  compiler?: { name?: string; version?: string };
  runtime?: {
    engine?: string;
    platform?: string;
    pipelineId?: string;
    pipelineVersion?: string;
    runtimeLockSha256?: string;
  };
  workflow?: {
    source?: string;
    pipelineId?: string;
    pipelineVersion?: string;
    snakefile?: string;
    runSpecSha256?: string;
    sourceFileCount?: number;
    sourceFiles?: Array<{ path?: string; sha256?: string }>;
  };
  graph?: { pipelineId?: string; nodeCount?: number; ruleCount?: number };
  toolRevisions?: Array<{
    toolRevisionId?: string;
    toolId?: string;
    name?: string;
    version?: string;
    packageSpec?: string;
    environmentLock?: { packageSpec?: string; dependencies?: string[] };
  }>;
};

export type FirstRunValidationCard = {
  schemaVersion?: string;
  generatedAt?: string;
  scenario?: {
    scenarioId?: string;
    dataset?: string;
    datasetUrl?: string;
    pipelineId?: string;
    pipelineName?: string;
  };
  run?: {
    runId?: string;
    status?: string;
    stage?: string;
    startedAt?: string;
    finishedAt?: string;
  };
  workflowRevision?: {
    workflowRevisionId?: string;
    contentHash?: string;
  };
  sampleData?: FirstRunSampleDataEvidence;
  softwareEnvironment?: FirstRunSoftwareEnvironment;
  reportInterpretation?: FirstRunReportInterpretation;
  result?: {
    resultId?: string;
    artifactCount?: number;
    inputArtifactCount?: number;
  };
  resultPackage?: {
    packageExportId?: string;
    artifactPayloadMode?: string;
    includeArtifacts?: boolean;
    sizeBytes?: number;
    sha256?: string;
    manifestSha256?: string;
    evidenceId?: string;
  };
  keyResults?: FirstRunValidationKeyResult[];
  checks?: FirstRunValidationCheck[];
  pilotHandoff?: FirstRunPilotHandoff;
};

export type FirstRunFinalizationNextAction = {
  code?: string;
  detail?: string;
  label?: string;
  target?: string;
};

export type FirstRunPilotHandoffEvidence = {
  runId?: string;
  resultId?: string;
  workflowRevisionId?: string;
  packageExportId?: string;
  packageSha256?: string;
  manifestSha256?: string;
  validationChecksPassed?: number;
  validationChecksTotal?: number;
};

export type FirstRunEvidenceBundleFile = {
  role?: string;
  filename?: string;
  source?: string;
  schemaVersion?: string;
  packageExportId?: string;
  sha256?: string;
  manifestSha256?: string;
  artifactPayloadMode?: string;
  includeArtifacts?: boolean;
};

export type FirstRunEvidenceBundle = {
  schemaVersion?: string;
  status?: string;
  bundleId?: string;
  purpose?: string;
  requiredFiles?: FirstRunEvidenceBundleFile[];
  integrity?: FirstRunPilotHandoffEvidence;
  redaction?: {
    rawPathsExposed?: boolean;
    storageUrisExposed?: boolean;
    previewRowsEmbedded?: boolean;
    policy?: string;
  };
  standards?: {
    workflowRunCrate?: string;
    w3cProv?: string;
  };
  consumerChecklist?: string[];
};

export type FirstRunPilotHandoff = {
  schemaVersion?: string;
  scope?: string;
  status?: string;
  evidence?: FirstRunPilotHandoffEvidence;
  evidenceBundle?: FirstRunEvidenceBundle;
  backupRestore?: {
    schemaVersion?: string;
    mode?: string;
    planCommand?: string;
    restoreProofCommand?: string;
    runbookPath?: string;
    requiresIsolatedRestore?: boolean;
    requiresManualSecretRebind?: boolean;
    noAutomaticBackup?: boolean;
    excludedActions?: string[];
  };
  nextScenarios?: Array<{
    scenarioId?: string;
    name?: string;
    status?: string;
    target?: string;
    blockedChecks?: Array<{ code?: string; requirement?: string; target?: string }>;
    databasePackCoverage?: { packCount?: number; missingTemplates?: string[] };
    toolSlicePromotionHandoff?: {
      schemaVersion?: string;
      status?: string;
      requiredState?: string;
      noAutomaticExecution?: boolean;
      sliceSize?: { min?: number; max?: number; actual?: number };
      toolOptions?: Array<{
        toolId?: string;
        name?: string;
        kind?: string;
        role?: string;
        contractState?: string;
        acceptanceEvidence?: string;
        acceptanceEvidenceContract?: {
          schemaVersion?: string;
          status?: string;
          evidenceRef?: string;
          requiredEvidence?: string[];
          evidencePointers?: Record<string, { status?: string; ref?: string; evidence?: string }>;
          target?: string;
          rejectedEvidence?: string[];
        };
      }>;
      checklist?: Array<{ code?: string; label?: string; status?: string; target?: string; evidence?: string }>;
      promotionContract?: {
        schemaVersion?: string;
        requiredState?: string;
        requiredEvidence?: string[];
        perToolChecklist?: Array<{ code?: string; status?: string; target?: string; evidence?: string }>;
        scenarioRunEvidence?: { requiredEvidence?: string[]; target?: string };
        excludedActions?: string[];
      };
      excludedActions?: string[];
    };
    databaseInstallHandoff?: {
      schemaVersion?: string;
      mode?: string;
      status?: string;
      noAutomaticExecution?: boolean;
      readyScan?: {
        schemaVersion?: string;
        method?: string;
        path?: string;
        requestFields?: string[];
        acceptedStatus?: string;
        mutatesRegistry?: boolean;
        requiresOperatorReadyPath?: boolean;
        auditAction?: string;
      };
      registration?: {
        method?: string;
        path?: string;
        requiresReadyScan?: boolean;
        prefillSource?: string;
        prefillFields?: string[];
        acceptedStatus?: string;
      };
      checklist?: Array<{ code?: string; label?: string; status?: string; target?: string; evidence?: string }>;
      packOptions?: Array<{
        packId?: string;
        templateId?: string;
        checksum?: string;
        sourceUrl?: string;
        readyDirHint?: string;
        registrationScriptPath?: string;
        installedLayer?: string;
      }>;
      evidencePolicy?: {
        acceptedEvidenceType?: string;
        requiresRegisteredStatus?: string;
        requiresRunResourceBinding?: boolean;
        rejectsCatalogLayerAsEvidence?: boolean;
        validationFixtureAccepted?: boolean;
      };
      excludedActions?: string[];
    };
  }>;
  nextAction?: FirstRunFinalizationNextAction;
  exclusions?: string[];
};

export type FirstRunFinalization = {
  schemaVersion?: string;
  status?: "ready" | "blocked" | string;
  packageAction?: string;
  evidenceBundle?: FirstRunEvidenceBundle;
  pilotHandoff?: FirstRunPilotHandoff;
  resultPackage?: WorkflowResultPackageExport;
  validationCard?: FirstRunValidationCard;
  nextAction?: FirstRunFinalizationNextAction;
};
