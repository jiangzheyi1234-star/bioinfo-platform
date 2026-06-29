"use client";

import { Archive, ClipboardCheck, Download, FileArchive, Loader2, RefreshCw } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { FirstRunValidationCard } from "./workflow-first-run-api";
import { workflowResultPackageDownloadHref } from "./workflows-page-api";
import type {
  WorkflowArtifact,
  WorkflowResultPackageExport,
  WorkflowRun,
  WorkflowRunDetail,
  WorkflowServer,
  WorkflowUpload,
} from "./workflows-page-model";

type ResultDetail = NonNullable<WorkflowRunDetail["results"]>;
export type FirstRunInputArtifacts = NonNullable<ResultDetail["inputArtifacts"]>;

export function ResultPackagePanel({
  disabledReason,
  error,
  exporting,
  latestPackage,
  loading,
  onExport,
  onRefresh,
  resultId,
}: {
  disabledReason: string;
  error: string;
  exporting: boolean;
  latestPackage?: WorkflowResultPackageExport;
  loading: boolean;
  onExport: () => void;
  onRefresh: () => void;
  resultId: string;
}) {
  const downloadHref = latestPackage ? workflowResultPackageDownloadHref(latestPackage) : "";
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <FileArchive strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            导出结果包
          </div>
          <div className="mt-1 truncate font-mono text-[11px] text-slate-400">{resultId || "result unavailable"}</div>
        </div>
        <Button variant="ghost" size="sm" className="h-8 px-2 text-xs text-slate-500" disabled={!resultId || loading} onClick={onRefresh}>
          <RefreshCw strokeWidth={1.5} className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
        </Button>
      </div>

      {disabledReason ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800">
          {disabledReason}
        </div>
      ) : null}

      {error ? (
        <Alert variant="destructive" className="mt-3">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          className="h-9 bg-slate-950 px-3 text-xs text-white hover:bg-slate-800"
          disabled={Boolean(disabledReason) || exporting}
          onClick={onExport}
          data-testid="first-run-export-package"
        >
          {exporting ? <Loader2 strokeWidth={1.5} className="mr-2 h-3.5 w-3.5 animate-spin" /> : <Archive strokeWidth={1.5} className="mr-2 h-3.5 w-3.5" />}
          导出完整结果包
        </Button>
        {downloadHref ? (
          <Button asChild variant="outline" className="h-9 px-3 text-xs">
            <a href={downloadHref} download={latestPackage?.download?.filename || undefined}>
              <Download strokeWidth={1.5} className="mr-2 h-3.5 w-3.5" />
              下载
            </a>
          </Button>
        ) : null}
      </div>

      {latestPackage ? (
        <div className="mt-4 grid gap-2 text-xs">
          <KeyValue label="package" value={latestPackage.packageExportId} mono />
          <KeyValue label="payload" value={latestPackage.artifactPayloadMode || (latestPackage.includeArtifacts ? "full" : "metadata-only")} />
          <KeyValue label="size" value={formatBytes(latestPackage.sizeBytes)} />
          <KeyValue label="sha256" value={latestPackage.sha256} mono />
          <KeyValue label="manifest" value={latestPackage.manifestSha256} mono />
          <KeyValue label="evidence" value={latestPackage.evidenceId} mono />
        </div>
      ) : null}
    </section>
  );
}

export function firstRunResultPackageReady(item: WorkflowResultPackageExport) {
  return (
    item.lifecycleState === "active" &&
    item.packageBytesState === "available" &&
    Boolean(item.download) &&
    (item.artifactPayloadMode === "full" || item.includeArtifacts === true)
  );
}

export function ValidationCard({
  artifacts,
  card,
  downloading,
  error,
  inputArtifacts,
  loadingCard,
  onDownload,
  packageExport,
  ready,
  resultId,
  run,
  sampleUploads,
  server,
  workflowRevisionId,
}: {
  artifacts: WorkflowArtifact[];
  card: FirstRunValidationCard | null;
  downloading: boolean;
  error: string;
  inputArtifacts: FirstRunInputArtifacts;
  loadingCard: boolean;
  onDownload: () => void;
  packageExport?: WorkflowResultPackageExport;
  ready: boolean;
  resultId: string;
  run: WorkflowRun | null;
  sampleUploads: WorkflowUpload[];
  server: WorkflowServer | null;
  workflowRevisionId: string;
}) {
  const interpretation = card?.reportInterpretation;
  const cardReady = interpretation?.status === "ready";
  return (
    <section
      className={cn("rounded-lg border bg-white p-5", ready ? "border-emerald-200" : "border-slate-200")}
      data-testid="first-run-validation-card"
      data-validation-ready={ready ? "true" : "false"}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
            <ClipboardCheck strokeWidth={1.5} className={cn("h-4 w-4", ready ? "text-emerald-600" : "text-slate-500")} />
            结果验证卡
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {loadingCard ? "正在生成服务端验证卡" : cardReady ? "服务端验证卡已生成" : ready ? "等待服务端验证卡" : "等待结果包与 WorkflowRevision"}
          </div>
        </div>
        <Button variant="outline" size="sm" className="h-8 px-2.5 text-xs" disabled={!ready || downloading} onClick={onDownload}>
          {downloading ? <Loader2 strokeWidth={1.5} className="h-3.5 w-3.5 animate-spin" /> : <Download strokeWidth={1.5} className="h-3.5 w-3.5" />}
          JSON
        </Button>
      </div>

      {error ? (
        <Alert variant="destructive" className="mt-3">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="mt-4 grid gap-2 text-xs">
        <KeyValue label="dataset" value="QIIME 2 Moving Pictures tutorial" />
        <KeyValue label="pipeline" value="moving-pictures-16s-rulegraph-v1" mono />
        <KeyValue label="run" value={run?.runId} mono />
        <KeyValue label="result" value={resultId} mono />
        <KeyValue label="status" value={run?.status} />
        <KeyValue label="runner" value={server?.label || server?.serverId} mono />
        <KeyValue label="runtime" value={runtimeLabel(server)} />
        <KeyValue label="database" value="不需要外部数据库" />
        <KeyValue label="revision" value={workflowRevisionId} mono />
        <KeyValue label="inputs" value={`${sampleUploads.length || inputArtifacts.length || 0} files`} />
        <KeyValue label="outputs" value={`${artifacts.length} artifacts`} />
        <KeyValue label="package" value={packageExport?.packageExportId} mono />
        <KeyValue label="package sha" value={packageExport?.sha256} mono />
        <KeyValue label="manifest" value={packageExport?.manifestSha256} mono />
        <KeyValue label="evidence" value={packageExport?.evidenceId} mono />
        <KeyValue label="card" value={card?.schemaVersion} mono />
        <KeyValue label="generated" value={card?.generatedAt} mono />
        <KeyValue label="checks" value={card?.checks?.length ? `${card.checks.length} passed checks` : ""} />
      </div>

      {interpretation ? <ValidationCardInterpretation interpretation={interpretation} /> : null}
    </section>
  );
}

function ValidationCardInterpretation({
  interpretation,
}: {
  interpretation: NonNullable<FirstRunValidationCard["reportInterpretation"]>;
}) {
  const metrics = interpretation.metrics || [];
  const outputs = interpretation.outputs || [];
  return (
    <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3" data-testid="first-run-validation-card-interpretation">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-semibold text-slate-900">报告解读已写入验证卡</div>
        <span className={cn("rounded-full border px-2 py-0.5 text-[11px]", interpretation.status === "ready" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-amber-200 bg-amber-50 text-amber-700")}>
          {interpretation.status || "unknown"}
        </span>
      </div>
      {interpretation.summary ? <div className="mt-2 text-xs leading-5 text-slate-600">{interpretation.summary}</div> : null}
      {metrics.length > 0 ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {metrics.slice(0, 6).map((metric) => (
            <div key={metric.metricId || metric.label} className="min-w-0 rounded border border-slate-200 bg-white px-3 py-2">
              <div className="truncate text-[11px] text-slate-400">{metric.label || metric.metricId}</div>
              <div className="mt-1 truncate text-sm font-semibold text-slate-900">{metric.displayValue || String(metric.value ?? "")}</div>
            </div>
          ))}
        </div>
      ) : null}
      {outputs.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {outputs.map((output) => (
            <span key={output.name || output.artifactId} className="inline-flex max-w-full items-center gap-1 rounded border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600">
              <span className={cn("h-1.5 w-1.5 rounded-full", output.present ? "bg-emerald-500" : "bg-amber-500")} />
              <span className="truncate">{output.name || output.label || output.artifactId}</span>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function KeyValue({ label, mono = false, value }: { label: string; mono?: boolean; value?: string }) {
  if (!value) return null;
  return (
    <div className="grid min-w-0 gap-1 sm:grid-cols-[82px_minmax(0,1fr)]">
      <span className="text-slate-400">{label}</span>
      <span className={cn("truncate text-slate-700", mono ? "font-mono text-[11px]" : "")}>{value}</span>
    </div>
  );
}

export function artifactName(artifact: WorkflowArtifact) {
  return (
    artifactDisplayValue(artifact, "artifactKey") ||
    artifactDisplayValue(artifact, "name") ||
    artifactDisplayValue(artifact, "path").split("/").pop() ||
    artifact.kind ||
    artifact.artifactId
  );
}

function artifactDisplayValue(artifact: WorkflowArtifact, key: "artifactKey" | "name" | "path") {
  const display = artifact as WorkflowArtifact & Record<typeof key, string | undefined>;
  return display[key] || "";
}

export function runtimeLabel(server: WorkflowServer | null) {
  const runtime = server?.health?.workflowRuntime;
  return [runtime?.provider, runtime?.source, runtime?.version, runtime?.snakemakeVersion ? `snakemake ${runtime.snakemakeVersion}` : ""]
    .filter(Boolean)
    .join(" / ");
}

export function formatBytes(bytes?: number) {
  if (!bytes) return "";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const index = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)));
  return `${parseFloat((bytes / k ** index).toFixed(2))} ${sizes[index]}`;
}
