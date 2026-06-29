"use client";

import { requestLocalApiJson } from "@/app/lib/local-api-client";

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
    sha256?: string;
    manifestSha256?: string;
  };
  checks?: Array<{ code?: string; status?: string; detail?: string }>;
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

function queryString(query: URLSearchParams) {
  const value = query.toString();
  return value ? `?${value}` : "";
}
