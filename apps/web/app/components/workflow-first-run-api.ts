"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type { WorkflowResultPackageExport } from "./workflows-page-model";

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

export async function fetchFirstRunValidationCard(
  runId: string,
  options: { serverId?: string } = {}
): Promise<FirstRunValidationCard> {
  const query = new URLSearchParams();
  if (options.serverId) query.set("serverId", options.serverId);
  const response = await requestLocalApiJson<{ data: FirstRunValidationCard }>(
    "GET",
    `/api/v1/first-run/runs/${encodeURIComponent(runId)}/validation-card${queryString(query)}`,
    { cache: "no-store", timeoutMs: 30_000 }
  );
  return response.data;
}

export async function finalizeFirstRun(
  runId: string,
  options: { actor?: string; serverId?: string } = {}
): Promise<FirstRunFinalization> {
  const response = await requestLocalApiJson<{ data: FirstRunFinalization }>(
    "POST",
    `/api/v1/first-run/runs/${encodeURIComponent(runId)}/finalize`,
    {
      body: {
        ...(options.serverId ? { serverId: options.serverId } : {}),
        ...(options.actor ? { actor: options.actor } : {}),
      },
      cache: "no-store",
      timeoutMs: 60_000,
    }
  );
  return response.data;
}

export async function downloadFirstRunValidationCard({
  card,
  resultId,
  runId,
  serverId,
}: {
  card?: FirstRunValidationCard | null;
  resultId: string;
  runId: string;
  serverId?: string;
}) {
  const resolvedCard = card || (await fetchFirstRunValidationCard(runId, { serverId }));
  const blob = new Blob([JSON.stringify(resolvedCard, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${resultId || runId}.validation-card.json`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

export async function downloadFirstRunValidationCardMarkdown({
  card,
  resultId,
  runId,
  serverId,
}: {
  card?: FirstRunValidationCard | null;
  resultId: string;
  runId: string;
  serverId?: string;
}) {
  const resolvedCard = card || (await fetchFirstRunValidationCard(runId, { serverId }));
  downloadTextFile({
    content: firstRunValidationCardMarkdown(resolvedCard),
    filename: `${resultId || runId}.validation-card.md`,
    type: "text/markdown;charset=utf-8",
  });
}

export async function downloadFirstRunHandoffManifest({
  card,
  resultId,
  runId,
  serverId,
}: {
  card?: FirstRunValidationCard | null;
  resultId: string;
  runId: string;
  serverId?: string;
}) {
  const resolvedCard = card || (await fetchFirstRunValidationCard(runId, { serverId }));
  downloadTextFile({
    content: firstRunHandoffManifestMarkdown(resolvedCard),
    filename: `${resultId || runId}.pilot-handoff.md`,
    type: "text/markdown;charset=utf-8",
  });
}

export function firstRunValidationCardMarkdown(card: FirstRunValidationCard) {
  const checks = card.checks || [];
  const passedChecks = checks.filter((item) => item.status === "passed").length;
  const software = card.softwareEnvironment;
  const runtime = software?.runtime;
  const workflow = card.workflowRevision;
  const packageExport = card.resultPackage;
  const sampleItems = card.sampleData?.items || [];
  const keyResults = card.keyResults || [];
  const metrics = card.reportInterpretation?.metrics || [];
  return [
    "# H2OMeta First Successful Run Validation Card",
    "",
    `Generated: ${markdownValue(card.generatedAt)}`,
    `Scenario: ${markdownValue(card.scenario?.pipelineName || card.scenario?.scenarioId || "Moving Pictures 16S")}`,
    `Dataset: ${markdownValue(card.scenario?.dataset || "QIIME 2 Moving Pictures tutorial")}`,
    `Run: ${markdownValue(card.run?.runId)} (${markdownValue(card.run?.status)})`,
    `WorkflowRevision: ${markdownValue(workflow?.workflowRevisionId || software?.workflowRevisionId)}`,
    `Software: ${markdownValue([runtime?.engine, runtime?.platform, runtime?.pipelineVersion].filter(Boolean).join(" / "))}`,
    `Result package: ${markdownValue(packageExport?.packageExportId)}`,
    `Package SHA-256: ${markdownValue(packageExport?.sha256)}`,
    `Manifest SHA-256: ${markdownValue(packageExport?.manifestSha256)}`,
    `Checks: ${passedChecks}/${checks.length} passed`,
    "",
    "## Customer Proof",
    "",
    ...firstRunCustomerProofMarkdown(card),
    "",
    "## Summary",
    "",
    markdownValue(card.reportInterpretation?.summary),
    "",
    "## Official Sample Inputs",
    "",
    sampleItems.length
      ? markdownTable(
          ["Role", "Filename", "Status", "Cache", "Download", "SHA-256"],
          sampleItems.map((item) => [
            item.role,
            item.filename,
            item.integrityStatus,
            item.prepProof?.cacheStatus,
            item.prepProof?.downloadStatus,
            item.sha256,
          ])
        )
      : "No sample input evidence recorded.",
    "",
    "## Key Results",
    "",
    keyResults.length
      ? markdownTable(["Result", "Kind", "Size", "SHA-256"], keyResults.map((item) => [item.displayName || item.artifactKey || item.artifactId, item.kind, String(item.sizeBytes || ""), item.sha256]))
      : "No key results recorded.",
    "",
    "## Metrics",
    "",
    metrics.length
      ? markdownTable(["Metric", "Value", "Source"], metrics.map((item) => [item.label || item.metricId, item.displayValue || String(item.value ?? ""), item.source]))
      : "No report metrics recorded.",
    "",
    "## Validation Checks",
    "",
    checks.length
      ? markdownTable(["Code", "Status", "Detail"], checks.map((item) => [item.code, item.status, item.detail]))
      : "No validation checks recorded.",
    "",
    "## Pilot Handoff",
    "",
    ...firstRunPilotHandoffMarkdown(card.pilotHandoff),
    "",
    "## Redaction",
    "",
    `Policy: ${markdownValue(card.reportInterpretation?.redaction?.policy || "metrics-only")}`,
    `Raw paths exposed: ${card.reportInterpretation?.redaction?.rawPathsExposed === true ? "yes" : "no"}`,
    `Storage URIs exposed: ${card.reportInterpretation?.redaction?.storageUrisExposed === true ? "yes" : "no"}`,
  ].join("\n");
}

export function firstRunHandoffManifestMarkdown(card: FirstRunValidationCard) {
  const checks = card.checks || [];
  const passedChecks = checks.filter((item) => item.status === "passed").length;
  const packageExport = card.resultPackage;
  const handoff = card.pilotHandoff;
  if (!handoff) throw new Error("FIRST_RUN_PILOT_HANDOFF_REQUIRED");
  const bundle = handoff.evidenceBundle;
  if (!bundle) throw new Error("FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED");
  const evidence = handoff?.evidence || {};
  const backup = handoff?.backupRestore;
  const scenarios = handoff?.nextScenarios || [];
  return [
    "# H2OMeta First Successful Run Pilot Handoff",
    "",
    `Run: ${markdownValue(evidence.runId || card.run?.runId)}`,
    `Result: ${markdownValue(evidence.resultId || card.result?.resultId)}`,
    `WorkflowRevision: ${markdownValue(evidence.workflowRevisionId || card.workflowRevision?.workflowRevisionId)}`,
    `Result package: ${markdownValue(evidence.packageExportId || packageExport?.packageExportId)}`,
    `Package SHA-256: ${markdownValue(evidence.packageSha256 || packageExport?.sha256)}`,
    `Manifest SHA-256: ${markdownValue(evidence.manifestSha256 || packageExport?.manifestSha256)}`,
    `Validation checks: ${evidence.validationChecksPassed ?? passedChecks}/${evidence.validationChecksTotal ?? checks.length} passed`,
    "",
    "## Pilot Scope",
    "",
    `Scope: ${markdownValue(handoff?.scope)}`,
    `Status: ${markdownValue(handoff?.status)}`,
    `Next action: ${markdownValue(handoff?.nextAction?.label || handoff?.nextAction?.code)}`,
    `Next action target: ${markdownValue(handoff?.nextAction?.target)}`,
    `Exclusions: ${markdownValue(handoff?.exclusions?.join(", "))}`,
    "",
    "## Evidence Bundle",
    "",
    `Bundle: ${markdownValue(bundle.bundleId)}`,
    `Status: ${markdownValue(bundle.status)}`,
    `Purpose: ${markdownValue(bundle.purpose)}`,
    bundle.requiredFiles?.length
      ? markdownTable(
          ["Role", "Filename", "Source", "SHA-256", "Manifest SHA-256"],
          bundle.requiredFiles.map((item) => [
            item.role,
            item.filename,
            item.source,
            item.sha256,
            item.manifestSha256,
          ])
        )
      : "No evidence bundle files recorded.",
    "",
    "## Backup And Restore",
    "",
    `Plan command: ${markdownValue(backup?.planCommand)}`,
    `Restore proof: ${markdownValue(backup?.restoreProofCommand)}`,
    `Runbook: ${markdownValue(backup?.runbookPath)}`,
    `Manual secret rebind required: ${backup?.requiresManualSecretRebind === true ? "yes" : "no"}`,
    `Automatic backup: ${backup?.noAutomaticBackup === true ? "not supported" : "not recorded"}`,
    `Unsupported actions: ${markdownValue(backup?.excludedActions?.join(", "))}`,
    "",
    "## Next Scenario Pilots",
    "",
    scenarios.length
      ? markdownTable(
          ["Scenario", "Status", "Blocked checks", "DB packs", "Ready scan", "Registration prefill", "Missing DB pack templates"],
          scenarios.map((item) => [
            item.name || item.scenarioId,
            item.status,
            String(item.blockedChecks?.length || 0),
            String(item.databasePackCoverage?.packCount || 0),
            item.databaseInstallHandoff?.readyScan?.path || "",
            item.databaseInstallHandoff?.registration?.prefillSource || "",
            item.databasePackCoverage?.missingTemplates?.join(", "),
          ])
        )
      : "No next scenario pilots recorded.",
    "",
    "Tool promotion evidence: toolRevisionId, capability-bundle-v1, RuleSpec, environment-lock, smoke-fixture, expected-output-artifacts.",
    "",
    "## Validation Card",
    "",
    "Keep every required evidence bundle file together. Verify the result package SHA-256 and manifest SHA-256 before sharing or reusing lineage.",
  ].join("\n");
}

function firstRunPilotHandoffMarkdown(handoff?: FirstRunPilotHandoff) {
  if (!handoff) throw new Error("FIRST_RUN_PILOT_HANDOFF_REQUIRED");
  if (!handoff.evidenceBundle) throw new Error("FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED");
  const backup = handoff.backupRestore;
  const scenarios = handoff.nextScenarios || [];
  return [
    `Scope: ${markdownValue(handoff.scope)}`,
    `Status: ${markdownValue(handoff.status)}`,
    `Evidence bundle: ${markdownValue(handoff.evidenceBundle.bundleId)} (${handoff.evidenceBundle.requiredFiles?.length || 0} files)`,
    `Backup plan: ${markdownValue(backup?.planCommand)}`,
    `Restore proof: ${markdownValue(backup?.restoreProofCommand)}`,
    "",
    scenarios.length
      ? markdownTable(
          ["Scenario", "Status", "Blocked checks", "DB packs", "Ready scan", "Registration prefill", "Missing DB pack templates"],
          scenarios.map((item) => [
            item.name || item.scenarioId,
            item.status,
            String(item.blockedChecks?.length || 0),
            String(item.databasePackCoverage?.packCount || 0),
            item.databaseInstallHandoff?.readyScan?.path || "",
            item.databaseInstallHandoff?.registration?.prefillSource || "",
            item.databasePackCoverage?.missingTemplates?.join(", "),
          ])
        )
      : "No next scenario handoff recorded.",
    "",
    "Tool promotion evidence: toolRevisionId, capability-bundle-v1, RuleSpec, environment-lock, smoke-fixture, expected-output-artifacts.",
  ];
}

function firstRunCustomerProofMarkdown(card: FirstRunValidationCard) {
  const software = card.softwareEnvironment;
  const runtime = [software?.runtime?.engine, software?.runtime?.platform, software?.runtime?.pipelineVersion]
    .filter(Boolean)
    .join(" / ");
  const packageExport = card.resultPackage;
  const fullPackage = packageExport?.artifactPayloadMode === "full" || packageExport?.includeArtifacts === true;
  const metrics = card.reportInterpretation?.metrics || [];
  const keyResults = card.keyResults || [];
  return [
    `- Official inputs: ${card.sampleData?.status === "verified" ? `${card.sampleData.items?.length || 0} files verified by checksum with ${card.sampleData.prepProof?.cachePolicy || "sample prep proof"}` : "waiting for checksum evidence"}`,
    `- Software environment: ${software?.status === "verified" ? runtime || "locked and verified" : "waiting for environment evidence"}`,
    "- Database: no external reference database is required for this Moving Pictures first run",
    `- Key results: ${card.reportInterpretation?.status === "ready" ? `${keyResults.length} outputs and ${metrics.length} metrics interpreted` : "waiting for report interpretation"}`,
    `- Result package: ${fullPackage && packageExport?.sha256 && packageExport?.manifestSha256 ? `full package with SHA-256 ${packageExport.sha256}` : "waiting for full package hash"}`,
    `- Evidence bundle: ${card.pilotHandoff?.evidenceBundle?.status === "ready" ? `${card.pilotHandoff.evidenceBundle.requiredFiles?.length || 0} required files listed` : "waiting for evidence bundle manifest"}`,
  ];
}

function queryString(query: URLSearchParams) {
  const value = query.toString();
  return value ? `?${value}` : "";
}

function downloadTextFile({ content, filename, type }: { content: string; filename: string; type: string }) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function markdownTable(headers: string[], rows: Array<Array<string | number | undefined>>) {
  return [
    `| ${headers.map(markdownCell).join(" | ")} |`,
    `| ${headers.map(() => "---").join(" | ")} |`,
    ...rows.map((row) => `| ${row.map((cell) => markdownCell(String(cell ?? ""))).join(" | ")} |`),
  ].join("\n");
}

function markdownCell(value?: string | number) {
  return markdownValue(value).replace(/\|/g, "\\|").replace(/\n/g, " ");
}

function markdownValue(value?: string | number) {
  const text = String(value ?? "").trim();
  return text || "-";
}
