export type RunStatus = "queued" | "running" | "completed" | "failed";

export type ReadinessCheck = {
  key: "startup" | "live" | "ready";
  label: string;
  status: "ok" | "warning" | "failed";
  value: string;
  reasonCode?: string;
};

export type RecentRun = {
  runId: string;
  serverId?: string;
  pipelineId: string;
  serverLabel: string;
  projectId?: string;
  projectLabel: string;
  status: RunStatus;
  stage: string;
  stateVersion: number;
  requestId: string;
  message: string;
  lastUpdatedAt: string;
  startedAt: string | null;
  finishedAt?: string | null;
  resultDir: string;
  progress: number | null;
  pipelineVersion?: string;
  runSpecVersion?: string;
  resumeSupported?: boolean;
  runSpec?: Record<string, unknown>;
  lastError?: {
    code: string;
    message: string;
    scope: string;
    at: string;
    requestId: string;
  } | null;
};

export type RecentResult = {
  id: string;
  title: string;
  sourceRunId: string;
  artifactCount: number;
  producedAt: string;
};

export type RunEvent = {
  eventId: string;
  eventType: string;
  fromStatus?: RunStatus;
  toStatus?: RunStatus;
  stage: string;
  stateVersion: number;
  message: string;
  requestId: string;
  createdAt: string;
};

export type RunArtifact = {
  artifactId: string;
  name?: string;
  kind: string;
  path: string;
  size?: string;
  sizeBytes?: number;
  mimeType: string;
  createdAt: string;
};

export const homeSummary = [
  { label: "Connected Server", value: "omics-prod-01" },
  { label: "Runner Ready", value: "Ready" },
  { label: "Running Runs", value: "03" },
  { label: "New Results Today", value: "12" },
] as const;

export const serverReadiness: ReadinessCheck[] = [
  { key: "startup", label: "Startup", status: "ok", value: "Healthy" },
  { key: "live", label: "Live", status: "ok", value: "Reachable" },
  {
    key: "ready",
    label: "Ready",
    status: "warning",
    value: "Runner control plane is up; execution capability comes next.",
    reasonCode: "RUNNER_CONTROL_PLANE_ONLY",
  },
];

export const recentRuns: RecentRun[] = [
  {
    runId: "run_2026_0419_001",
    pipelineId: "taxonomy-v1",
    serverLabel: "omics-prod-01",
    projectLabel: "Gut Microbiome Cohort A",
    status: "running",
    stage: "snakemake",
    stateVersion: 7,
    requestId: "req_f2b8f4f0",
    message: "Running taxonomy step",
    lastUpdatedAt: "2 min ago",
    startedAt: "2026-04-21 10:03",
    finishedAt: null,
    resultDir: "/srv/h2ometa/results/run_2026_0419_001",
    progress: null,
    lastError: null,
  },
  {
    runId: "run_2026_0419_000",
    pipelineId: "assembly-v2",
    serverLabel: "omics-prod-01",
    projectLabel: "Soil Metagenome Pilot",
    status: "failed",
    stage: "validate",
    stateVersion: 4,
    requestId: "req_8ca3f12c",
    message: "Input file not found",
    lastUpdatedAt: "18 min ago",
    startedAt: "2026-04-21 09:42",
    finishedAt: "2026-04-21 09:49",
    resultDir: "",
    progress: null,
    lastError: {
      code: "INPUT_NOT_FOUND",
      message: "FASTQ input missing on remote path",
      scope: "validate",
      at: "2026-04-21 09:49",
      requestId: "req_8ca3f12c",
    },
  },
  {
    runId: "run_2026_0418_014",
    pipelineId: "taxonomy-v1",
    serverLabel: "omics-prod-02",
    projectLabel: "Water Quality Batch 7",
    status: "completed",
    stage: "finalize",
    stateVersion: 12,
    requestId: "req_218ce099",
    message: "Completed successfully",
    lastUpdatedAt: "1 h ago",
    startedAt: "2026-04-21 08:15",
    finishedAt: "2026-04-21 08:53",
    resultDir: "/srv/h2ometa/results/run_2026_0418_014",
    progress: null,
    lastError: null,
  },
];

export const recentResults: RecentResult[] = [
  {
    id: "res_taxonomy_001",
    title: "Taxonomy Report",
    sourceRunId: "run_2026_0418_014",
    artifactCount: 18,
    producedAt: "35 min ago",
  },
  {
    id: "res_qc_002",
    title: "QC Summary",
    sourceRunId: "run_2026_0419_001",
    artifactCount: 6,
    producedAt: "2 h ago",
  },
  {
    id: "res_table_003",
    title: "Abundance Matrix",
    sourceRunId: "run_2026_0417_023",
    artifactCount: 4,
    producedAt: "today",
  },
];

export const runEvents: RunEvent[] = [
  {
    eventId: "evt_001",
    eventType: "status-transition",
    fromStatus: "queued",
    toStatus: "running",
    stage: "prepareInputs",
    stateVersion: 2,
    message: "Input staging started",
    requestId: "req_f2b8f4f0",
    createdAt: "10:04",
  },
  {
    eventId: "evt_002",
    eventType: "stage-transition",
    fromStatus: "running",
    toStatus: "running",
    stage: "snakemake",
    stateVersion: 5,
    message: "Snakemake execution entered taxonomy workflow",
    requestId: "req_f2b8f4f0",
    createdAt: "10:09",
  },
  {
    eventId: "evt_003",
    eventType: "heartbeat",
    fromStatus: "running",
    toStatus: "running",
    stage: "snakemake",
    stateVersion: 7,
    message: "Remote worker heartbeat received",
    requestId: "req_f2b8f4f0",
    createdAt: "10:17",
  },
];

export const runArtifacts: RunArtifact[] = [
  {
    artifactId: "art_001",
    name: "taxonomy-report.html",
    kind: "report",
    path: "/srv/h2ometa/results/run_2026_0419_001/taxonomy-report.html",
    size: "1.4 MB",
    mimeType: "text/html",
    createdAt: "10:18",
  },
  {
    artifactId: "art_002",
    name: "abundance-matrix.tsv",
    kind: "table",
    path: "/srv/h2ometa/results/run_2026_0419_001/abundance-matrix.tsv",
    size: "420 KB",
    mimeType: "text/tab-separated-values",
    createdAt: "10:18",
  },
  {
    artifactId: "art_003",
    name: "raw-log.txt",
    kind: "log",
    path: "/srv/h2ometa/results/run_2026_0419_001/raw-log.txt",
    size: "84 KB",
    mimeType: "text/plain",
    createdAt: "10:17",
  },
];

export const runLogLines = [
  "[10:09:11] validating runSpec and remote runtime",
  "[10:09:18] snakemake --profile default --cores 24",
  "[10:09:33] rule classify_reads started",
  "[10:12:02] rule aggregate_taxonomy started",
  "[10:17:44] heartbeat stateVersion=7 stage=snakemake",
];

export const runSpecExample = {
  runId: "run_2026_0419_001",
  pipelineId: "taxonomy-v1",
  pipelineVersion: "1.4.0",
  runSpecVersion: "2026-04-21",
  serverId: "srv_omics_prod_01",
  projectId: "proj_gut_cohort_a",
  inputs: [
    { sampleId: "sample_001", uploadId: "upl_001", kind: "fastq_pair" },
    { sampleId: "sample_002", uploadId: "upl_002", kind: "fastq_pair" },
  ],
};
