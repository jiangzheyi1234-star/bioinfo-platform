"use client";

import { useState } from "react";
import { AlertCircle, Download, Loader2, Package } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { exportWorkflowResultPackage, workflowResultPackageDownloadHref } from "./workflows-page-api";
import { workflowErrorMessage } from "./workflows-page-model";
import type { WorkflowResultPackageExport, WorkflowRun } from "./workflows-page-model";

type ExportMode = "full" | "metadata";

export function WorkflowResultPackagePanel({
  resultId,
  run,
  workflowRevisionId,
}: {
  resultId?: string;
  run: WorkflowRun;
  workflowRevisionId?: string;
}) {
  const [exportingMode, setExportingMode] = useState<ExportMode | "">("");
  const [exportError, setExportError] = useState("");
  const [exportResult, setExportResult] = useState<WorkflowResultPackageExport | null>(null);
  const disabledReason = resultPackageDisabledReason({ resultId, run, workflowRevisionId });
  const canExport = disabledReason.length === 0;

  async function handleExport(mode: ExportMode) {
    if (!resultId || !canExport) return;
    setExportingMode(mode);
    setExportError("");
    try {
      setExportResult(await exportWorkflowResultPackage(resultId, mode === "full"));
    } catch (err) {
      setExportError(workflowErrorMessage(err, "结果包导出失败"));
    } finally {
      setExportingMode("");
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Package strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
            结果包
          </div>
          <div className="mt-1 truncate font-mono text-[11px] text-slate-400">
            {resultId || "resultId unavailable"}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8 px-2 text-xs"
            disabled={!canExport || Boolean(exportingMode)}
            onClick={() => handleExport("metadata")}
          >
            {exportingMode === "metadata" ? <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" /> : null}
            metadata-only
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 px-2 text-xs"
            disabled={!canExport || Boolean(exportingMode)}
            onClick={() => handleExport("full")}
          >
            {exportingMode === "full" ? <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" /> : null}
            含产物文件
          </Button>
        </div>
      </div>

      {disabledReason ? (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-700">
          {disabledReason}
        </div>
      ) : null}

      {exportError ? (
        <Alert variant="destructive" className="mt-3">
          <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
          <AlertDescription>{exportError}</AlertDescription>
        </Alert>
      ) : null}

      {exportResult ? <ResultPackageSummary item={exportResult} /> : null}
    </div>
  );
}

function ResultPackageSummary({ item }: { item: WorkflowResultPackageExport }) {
  const downloadHref = workflowResultPackageDownloadHref(item);
  return (
    <div className="mt-3 grid gap-2 border-t border-slate-100 pt-3 text-xs">
      {downloadHref ? (
        <div className="flex justify-end">
          <Button asChild variant="outline" size="sm" className="h-8 px-2 text-xs">
            <a href={downloadHref} download={item.download?.filename || undefined}>
              <Download strokeWidth={1.5} className="h-3 w-3" />
              下载结果包
            </a>
          </Button>
        </div>
      ) : null}
      <PackageField label="package" value={item.packageExportId} mono />
      <PackageField label="payload" value={item.artifactPayloadMode || (item.includeArtifacts ? "full" : "metadata-only")} />
      <PackageField label="size" value={formatPackageBytes(item.sizeBytes)} />
      <PackageField label="sha256" value={item.sha256} mono />
      <PackageField label="manifest" value={item.manifestSha256} mono />
      <PackageField label="evidence" value={item.evidenceId} mono />
    </div>
  );
}

function PackageField({ label, mono = false, value }: { label: string; mono?: boolean; value?: string }) {
  if (!value) return null;
  return (
    <div className="grid min-w-0 gap-1 sm:grid-cols-[90px_minmax(0,1fr)]">
      <span className="text-slate-400">{label}</span>
      <span className={mono ? "truncate font-mono text-[11px] text-slate-700" : "truncate text-slate-700"}>{value}</span>
    </div>
  );
}

function resultPackageDisabledReason({
  resultId,
  run,
  workflowRevisionId,
}: {
  resultId?: string;
  run: WorkflowRun;
  workflowRevisionId?: string;
}) {
  if (!resultId) return "缺少 resultId";
  if (!isResultPackageExportableRunStatus(run.status)) return "仅 completed/failed 运行可导出";
  if (!workflowRevisionId) return "缺少 WorkflowRevision";
  return "";
}

function isResultPackageExportableRunStatus(status: string | undefined) {
  return status === "completed" || status === "failed";
}

function formatPackageBytes(bytes: number | undefined): string {
  if (!bytes) return "";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.min(sizes.length - 1, Math.floor(Math.log(bytes) / Math.log(k)));
  return `${parseFloat((bytes / k ** i).toFixed(2))} ${sizes[i]}`;
}
