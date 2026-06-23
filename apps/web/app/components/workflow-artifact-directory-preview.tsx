"use client";

import { FileText, FolderClosed } from "lucide-react";

import { cn } from "@/lib/utils";

import type { WorkflowArtifactDirectoryPreviewEntry, WorkflowArtifactPreview } from "./workflows-page-model";

export function isDirectoryArtifactPreview(preview: WorkflowArtifactPreview | undefined) {
  return preview?.preview?.kind === "directory";
}

export function DirectoryArtifactPreview({
  preview,
  compact = false,
}: {
  preview: WorkflowArtifactPreview | undefined;
  compact?: boolean;
}) {
  const data = preview?.preview;
  if (data?.kind !== "directory") return null;

  const entries = (data.entries || []).filter((entry) => entry.path);
  const visibleEntries = compact ? entries.slice(0, 5) : entries;
  const truncated = Boolean(data.truncated || visibleEntries.length < entries.length);

  return (
    <div className={cn("space-y-2", compact && "mt-3 rounded-md border border-slate-200 bg-slate-50 p-2")}>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
        <span>
          {data.fileCount ?? 0} 文件 / {data.directoryCount ?? 0} 目录 / {formatDirectoryBytes(data.logicalSizeBytes ?? 0)}
        </span>
        {data.logicalSha256 ? <span className="font-mono text-slate-400">{shortSha(data.logicalSha256)}</span> : null}
      </div>
      <div className={cn("overflow-hidden rounded-md border border-slate-200 bg-white", compact ? "max-h-40" : "max-h-[55vh] overflow-auto")}>
        {visibleEntries.length === 0 ? (
          <div className="px-3 py-4 text-center text-xs text-slate-400">空目录</div>
        ) : (
          <div className="divide-y divide-slate-100">
            {visibleEntries.map((entry) => (
              <DirectoryEntryRow key={`${entry.kind}:${entry.path}`} entry={entry} compact={compact} />
            ))}
          </div>
        )}
      </div>
      {truncated ? <div className="text-[11px] text-slate-400">仅显示前 {visibleEntries.length} 项</div> : null}
    </div>
  );
}

function DirectoryEntryRow({
  entry,
  compact,
}: {
  entry: WorkflowArtifactDirectoryPreviewEntry;
  compact: boolean;
}) {
  const isDirectory = entry.kind === "directory";
  return (
    <div className="flex items-center gap-2 px-3 py-2 text-xs">
      {isDirectory ? (
        <FolderClosed strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-amber-500" />
      ) : (
        <FileText strokeWidth={1.5} className="h-3.5 w-3.5 shrink-0 text-slate-500" />
      )}
      <span className="min-w-0 flex-1 truncate font-mono text-slate-700">{entry.path}</span>
      {!isDirectory ? <span className="shrink-0 text-slate-400">{formatDirectoryBytes(entry.sizeBytes ?? 0)}</span> : null}
      {!compact && entry.sha256 ? <span className="hidden shrink-0 font-mono text-[11px] text-slate-400 md:inline">{shortSha(entry.sha256)}</span> : null}
    </div>
  );
}

function shortSha(value: string) {
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

function formatDirectoryBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${parseFloat((bytes / k ** i).toFixed(2))} ${sizes[i]}`;
}
