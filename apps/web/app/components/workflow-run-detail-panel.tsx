"use client";

import { useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  FileCode,
  FileText,
  Image as ImageIcon,
  Loader2,
  Package,
  Table,
  Terminal,
  XCircle,
} from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { requestLocalApiJson } from "@/app/lib/local-api-client";

import type {
  WorkflowArtifact,
  WorkflowArtifactPreview,
  WorkflowRun,
  WorkflowRunDetail,
  WorkflowRunEvent,
} from "./workflows-page-model";

type TabKey = "overview" | "artifacts" | "stdout" | "stderr";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "概览" },
  { key: "artifacts", label: "产物" },
  { key: "stdout", label: "stdout" },
  { key: "stderr", label: "stderr" },
];

/* ─── Status helpers ─── */

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "completed" || s === "success") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700">
        <CheckCircle2 strokeWidth={1.5} className="h-4 w-4" />
        完成
      </span>
    );
  }
  if (s === "failed" || s === "error") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-3 py-1 text-sm font-medium text-red-700">
        <XCircle strokeWidth={1.5} className="h-4 w-4" />
        失败
      </span>
    );
  }
  if (s === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-sm font-medium text-blue-700">
        <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" />
        运行中
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm font-medium text-slate-600">
      <Clock strokeWidth={1.5} className="h-4 w-4" />
      {status}
    </span>
  );
}

/* ─── Timeline ─── */

function RunTimeline({ events }: { events: WorkflowRunEvent[] }) {
  if (events.length === 0) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">阶段消息</div>
      <div className="space-y-2">
        {events.slice(-8).map((event, i) => (
          <div key={i} className="flex items-start gap-2 text-xs text-slate-600">
            <Clock strokeWidth={1.5} className="mt-0.5 h-3 w-3 shrink-0 text-slate-400" />
            <span className="shrink-0 text-slate-400">
              {event.createdAt
                ? new Date(event.createdAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
                : "--"}
            </span>
            <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
              {event.stage || event.status}
            </span>
            <span className="min-w-0 truncate">{event.message || "—"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Diagnosis ─── */

function RunDiagnosis({
  run,
  events,
  stderrLines,
}: {
  run: WorkflowRun;
  events: WorkflowRunEvent[];
  stderrLines: string[];
}) {
  const failed = run.status === "failed" || run.status === "error";
  if (!failed) return null;

  const messages: string[] = [];
  if (run.message) messages.push(run.message);
  const failureEvent = events.find((e) => e.status === "failed" || e.status === "error");
  if (failureEvent?.message && !messages.includes(failureEvent.message)) {
    messages.push(failureEvent.message);
  }
  if (run.stage === "uploading") messages.push("文件上传阶段失败，请检查网络连接或文件大小。");
  else if (run.stage === "submitted") messages.push("任务提交到远程 runner 失败，请确认远程服务已就绪。");
  else if (run.stage === "running") messages.push("Snakemake 运行失败，请查看 stderr 日志和输入文件格式。");

  const lastStderr = stderrLines.slice(-30);

  return (
    <div className="space-y-3">
      <Alert variant="destructive" className="border-red-200 bg-red-50 text-red-800">
        <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
        <AlertDescription className="space-y-1">
          <div className="font-medium">运行失败</div>
          {messages.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-4 text-xs">
              {messages.map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ul>
          ) : (
            <div className="text-xs">未知错误，请查看日志。</div>
          )}
        </AlertDescription>
      </Alert>
      {lastStderr.length > 0 && (
        <div className="rounded-lg border border-red-200 bg-slate-950 p-3">
          <div className="mb-2 text-xs font-medium text-red-400">stderr 最后 {lastStderr.length} 行</div>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-xs text-red-100">{lastStderr.join("\n")}</pre>
        </div>
      )}
    </div>
  );
}

/* ─── Artifacts ─── */

function artifactIcon(mimeType: string) {
  if (mimeType.includes("html")) return <FileCode strokeWidth={1.5} className="h-4 w-4 text-blue-500" />;
  if (mimeType.includes("csv") || mimeType.includes("tsv") || mimeType.includes("tab")) return <Table strokeWidth={1.5} className="h-4 w-4 text-emerald-500" />;
  if (mimeType.includes("image")) return <ImageIcon strokeWidth={1.5} className="h-4 w-4 text-purple-500" />;
  return <FileText strokeWidth={1.5} className="h-4 w-4 text-slate-500" />;
}

function artifactName(artifact: WorkflowArtifact) {
  const path = artifact.path || "";
  return path.split(/[\\/]/).filter(Boolean).pop() || artifact.kind || artifact.artifactId;
}

function isPreviewable(mimeType: string) {
  return /text|html|csv|tsv|json|xml|md|log/.test(mimeType);
}

function downloadArtifact(name: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function RunArtifacts({
  resultId,
  artifacts,
  previews,
}: {
  resultId?: string;
  artifacts: WorkflowArtifact[];
  previews: WorkflowArtifactPreview[];
}) {
  const [open, setOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const [previewKind, setPreviewKind] = useState<string>("text");
  const [loading, setLoading] = useState(false);

  const previewMap = new Map<string, WorkflowArtifactPreview>();
  for (const p of previews) {
    if (p.artifact?.artifactId) previewMap.set(p.artifact.artifactId, p);
  }

  async function openPreview(artifact: WorkflowArtifact) {
    const existing = previewMap.get(artifact.artifactId);
    if (existing?.preview?.content) {
      setPreviewTitle(artifactName(artifact));
      setPreviewContent(existing.preview.content);
      setPreviewKind(existing.preview.kind || "text");
      setOpen(true);
      return;
    }
    if (!resultId) return;
    setLoading(true);
    try {
      const data = await requestLocalApiJson<{ data: WorkflowArtifactPreview }>(
        "GET",
        `/api/v1/results/${resultId}/preview?artifact_id=${encodeURIComponent(artifact.artifactId)}`,
        { cache: "no-store" }
      );
      setPreviewTitle(artifactName(artifact));
      setPreviewContent(data.data.preview?.content || "（无预览内容）");
      setPreviewKind(data.data.preview?.kind || "text");
      setOpen(true);
    } catch {
      setPreviewTitle(artifactName(artifact));
      setPreviewContent("预览加载失败");
      setPreviewKind("text");
      setOpen(true);
    } finally {
      setLoading(false);
    }
  }

  if (artifacts.length === 0) {
    return <div className="py-8 text-center text-sm text-slate-400">暂无产物</div>;
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {artifacts.map((artifact) => {
          const previewable = isPreviewable(artifact.mimeType);
          const existingPreview = previewMap.get(artifact.artifactId);
          return (
            <div key={artifact.artifactId} className="flex flex-col rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-center gap-2">
                {artifactIcon(artifact.mimeType)}
                <div className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">{artifactName(artifact)}</div>
              </div>
              <div className="mt-1 truncate font-mono text-[11px] text-slate-500">{artifact.mimeType}</div>
              <div className="mt-1 text-[11px] text-slate-400">{formatBytes(artifact.sizeBytes)}</div>
              <div className="mt-3 flex items-center gap-2">
                {previewable && (
                  <Button variant="outline" size="sm" className="h-7 px-2 text-xs" disabled={loading} onClick={() => openPreview(artifact)}>
                    <Terminal strokeWidth={1.5} className="mr-1 h-3 w-3" />
                    预览
                  </Button>
                )}
                {existingPreview?.preview?.content && (
                  <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => downloadArtifact(artifactName(artifact), existingPreview.preview!.content || "", artifact.mimeType)}>
                    下载
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="text-base">{previewTitle}</DialogTitle>
            <DialogDescription className="text-xs">产物预览</DialogDescription>
          </DialogHeader>
          {previewKind === "html" && previewContent ? (
            <div className="max-h-[60vh] overflow-auto rounded border border-slate-200 bg-white">
              <iframe title={previewTitle} srcDoc={previewContent} className="h-[50vh] w-full" sandbox="allow-same-origin" />
            </div>
          ) : (
            <div className="max-h-[60vh] overflow-auto rounded border border-slate-200 bg-slate-950 p-3">
              <pre className="whitespace-pre-wrap text-xs text-slate-100">{previewContent}</pre>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / k ** i).toFixed(2))} ${sizes[i]}`;
}

/* ─── Log block ─── */

function LogBlock({ title, lines }: { title: string; lines: string[] }) {
  if (lines.length === 0) {
    return <div className="py-8 text-center text-sm text-slate-400">暂无 {title} 日志</div>;
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-950 p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</div>
        <span className="text-[11px] text-slate-500">{lines.length} 行</span>
      </div>
      <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-slate-100">
        {lines.join("\n")}
      </pre>
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium text-slate-400">{label}</div>
      <div className="mt-1 truncate text-sm font-medium text-slate-900">{value}</div>
    </div>
  );
}

function RunStateInline({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "completed" || s === "success") {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-emerald-600">
        <span className="h-2 w-2 rounded-full bg-emerald-500" />
        完成
      </span>
    );
  }
  if (s === "failed" || s === "error") {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-red-600">
        <span className="h-2 w-2 rounded-full bg-red-500" />
        失败
      </span>
    );
  }
  if (s === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-600">
        <Loader2 strokeWidth={1.5} className="h-3.5 w-3.5 animate-spin" />
        运行中
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-500">
      <span className="h-2 w-2 rounded-full bg-slate-300" />
      {status}
    </span>
  );
}

function formatDateTime(value?: string) {
  return value ? new Date(value).toLocaleString("zh-CN") : "—";
}

function durationText(startedAt?: string, finishedAt?: string) {
  if (!startedAt || !finishedAt) return "—";
  const seconds = Math.max(0, Math.round((new Date(finishedAt).getTime() - new Date(startedAt).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function TablePreview({ preview }: { preview: WorkflowArtifactPreview | undefined }) {
  const columns = preview?.preview?.columns || [];
  const rows = preview?.preview?.rows || [];
  if (columns.length === 0 || rows.length === 0) return null;

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div className="text-sm font-medium text-slate-900">{preview?.artifact ? artifactName(preview.artifact) : "表格预览"}</div>
        <span className="text-xs text-slate-400">{rows.length} 行预览</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              {columns.map((column) => (
                <th key={column} className="whitespace-nowrap px-3 py-2 font-medium">{column}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.slice(0, 5).map((row, index) => (
              <tr key={index}>
                {columns.map((column, columnIndex) => (
                  <td key={`${column}-${columnIndex}`} className="max-w-[220px] truncate px-3 py-2 text-slate-700">
                    {row[columnIndex] || ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function preferredTablePreview(previews: WorkflowArtifactPreview[]) {
  const tables = previews.filter((preview) => preview.preview?.kind === "table");
  return (
    tables.find((preview) => preview.artifact && artifactName(preview.artifact) === "summary.tsv") ||
    tables.find((preview) => preview.artifact && artifactName(preview.artifact) === "qc-summary.tsv") ||
    tables.find((preview) => preview.artifact && artifactName(preview.artifact) !== "feature-table.tsv") ||
    tables[0]
  );
}

/* ─── Main Panel ─── */

export function WorkflowRunDetailPanel({
  detail,
  error,
}: {
  detail: WorkflowRunDetail;
  error: string;
}) {
  const [tab, setTab] = useState<TabKey>("overview");
  const run = detail.run;
  const artifacts = detail.results?.artifacts || [];
  const previews = detail.previews || [];
  const events = detail.events || [];
  const stdout = detail.logs.stdout?.lines || [];
  const stderr = detail.logs.stderr?.lines || [];
  const tablePreview = preferredTablePreview(previews);
  const inputs = (run.runSpec?.inputs as Array<{ filename?: string }> | undefined) || [];
  const pipelineId = typeof run.pipelineId === "string" ? run.pipelineId : String(run.runSpec?.pipelineId || "—");

  return (
    <div className="space-y-5">
      <div className="border-y border-slate-100 bg-white py-5">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_440px] lg:items-center">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h2 className="truncate text-[17px] font-semibold leading-6 text-slate-950">{pipelineId}</h2>
              <RunStateInline status={run.status} />
            </div>
            <div className="mt-2 flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
              <FileText strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-300" />
              <span className="truncate">{inputs.map((input) => input.filename).filter(Boolean).join(", ") || run.runId}</span>
            </div>
            <div className="mt-1.5 flex min-w-0 items-center gap-1.5 font-mono text-[11px] text-slate-400">
              <Package strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-300" />
              <span className="truncate">{run.runId}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4 lg:border-l lg:border-slate-100 lg:pl-8">
            <SummaryMetric label="阶段" value={run.stage || "—"} />
            <SummaryMetric label="耗时" value={durationText(run.startedAt, run.finishedAt)} />
            <SummaryMetric label="提交时间" value={formatDateTime(run.submittedAt || run.createdAt)} />
            <SummaryMetric label="产物" value={`${artifacts.length} 个`} />
          </div>
        </div>
      </div>

      {/* Error banner */}
      {error ? (
        <Alert variant="destructive">
          <AlertCircle strokeWidth={1.5} className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "relative px-4 py-2 text-sm font-medium transition",
              tab === t.key ? "text-slate-900" : "text-slate-500 hover:text-slate-700"
            )}
          >
            {t.label}
            {tab === t.key && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-slate-900" />}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="min-h-[200px]">
        {tab === "overview" && (
          <div className="space-y-4">
            <RunDiagnosis run={run} events={events} stderrLines={stderr} />
            <TablePreview preview={tablePreview} />
            {artifacts.length > 0 && (
              <div className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="mb-3 text-sm font-medium text-slate-900">产物概览</div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {artifacts.map((a) => (
                    <span key={a.artifactId} className="inline-flex min-w-0 items-center rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs text-slate-600">
                      {artifactIcon(a.mimeType)}
                      <span className="ml-1.5 truncate">{artifactName(a)}</span>
                      <span className="ml-1 shrink-0 text-slate-400">{formatBytes(a.sizeBytes)}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            <RunTimeline events={events} />
          </div>
        )}

        {tab === "artifacts" && (
          <RunArtifacts resultId={detail.results?.resultId} artifacts={artifacts} previews={previews} />
        )}

        {tab === "stdout" && <LogBlock title="stdout" lines={stdout} />}

        {tab === "stderr" && <LogBlock title="stderr" lines={stderr} />}
      </div>
    </div>
  );
}
