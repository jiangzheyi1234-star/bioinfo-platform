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
  uploadId?: string;
  artifactBlobId?: string;
  sha256?: string;
  expectedSha256?: string;
  sizeBytes?: number;
  expectedSizeBytes?: number;
  integrityStatus?: "passed" | string;
};

export type FirstRunSampleDataEvidence = {
  schemaVersion?: string;
  source?: string;
  status?: string;
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
};

export type FirstRunFinalizationNextAction = {
  code?: string;
  detail?: string;
  label?: string;
  target?: string;
};

export type FirstRunFinalization = {
  schemaVersion?: string;
  status?: "ready" | "blocked" | string;
  packageAction?: string;
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
    "## Summary",
    "",
    markdownValue(card.reportInterpretation?.summary),
    "",
    "## Official Sample Inputs",
    "",
    sampleItems.length
      ? markdownTable(["Role", "Filename", "Status", "SHA-256"], sampleItems.map((item) => [item.role, item.filename, item.integrityStatus, item.sha256]))
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
    "## Redaction",
    "",
    `Policy: ${markdownValue(card.reportInterpretation?.redaction?.policy || "metrics-only")}`,
    `Raw paths exposed: ${card.reportInterpretation?.redaction?.rawPathsExposed === true ? "yes" : "no"}`,
    `Storage URIs exposed: ${card.reportInterpretation?.redaction?.storageUrisExposed === true ? "yes" : "no"}`,
  ].join("\n");
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
