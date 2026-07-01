"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

import { fetchWorkflowRunLogs, type WorkflowRunLogStream } from "./workflow-run-logs-api";
import { workflowErrorMessage, type WorkflowLogLines } from "./workflows-page-model";

export function WorkflowRunLogBlock({
  initialLog,
  runId,
  stream,
}: {
  initialLog?: WorkflowLogLines;
  runId: string;
  stream: WorkflowRunLogStream;
}) {
  const [lines, setLines] = useState<string[]>(() => initialLog?.lines || []);
  const [nextCursor, setNextCursor] = useState(initialLog?.nextCursor || "");
  const [loadingMore, setLoadingMore] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setLines(initialLog?.lines || []);
    setNextCursor(initialLog?.nextCursor || "");
    setStatus("");
    setError("");
  }, [initialLog, runId, stream]);

  async function loadMore() {
    if (loadingMore) return;
    if (lines.length > 0 && !nextCursor) {
      setError("RUN_LOG_CURSOR_REQUIRED");
      return;
    }
    setLoadingMore(true);
    setError("");
    setStatus("");
    try {
      const page = await fetchWorkflowRunLogs(runId, stream, nextCursor || undefined);
      const nextLines = page.lines || [];
      setLines((current) => [...current, ...nextLines]);
      setNextCursor(page.nextCursor || nextCursor);
      setStatus(nextLines.length > 0 ? `新增 ${nextLines.length} 行` : "暂无新增日志");
    } catch (err) {
      setError(workflowErrorMessage(err, "读取运行日志失败"));
    } finally {
      setLoadingMore(false);
    }
  }

  if (lines.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-slate-400">暂无 {stream} 日志</div>
          <LogRefreshButton loading={loadingMore} onClick={loadMore} />
        </div>
        {error ? <div className="mt-2 text-xs text-red-600">{error}</div> : null}
        {status ? <div className="mt-2 text-xs text-slate-500">{status}</div> : null}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-950 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{stream}</div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-[11px] text-slate-500">{lines.length} 行</span>
          <LogRefreshButton loading={loadingMore} onClick={loadMore} />
        </div>
      </div>
      <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-slate-100">
        {lines.join("\n")}
      </pre>
      {error ? <div className="mt-2 text-xs text-red-300">{error}</div> : null}
      {status ? <div className="mt-2 text-xs text-slate-400">{status}</div> : null}
    </div>
  );
}

function LogRefreshButton({
  loading,
  onClick,
}: {
  loading: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="outline"
      className="h-7 shrink-0 bg-white px-2 text-xs"
      disabled={loading}
      onClick={onClick}
      data-testid="workflow-run-log-load-more"
    >
      {loading ? (
        <Loader2 strokeWidth={1.5} className="mr-1 h-3 w-3 animate-spin" />
      ) : (
        <RefreshCw strokeWidth={1.5} className="mr-1 h-3 w-3" />
      )}
      加载新日志
    </Button>
  );
}
