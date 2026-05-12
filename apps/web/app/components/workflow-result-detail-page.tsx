"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { fetchWorkflowRunDetail } from "./workflows-page-api";
import { workflowErrorMessage, type WorkflowRunDetail } from "./workflows-page-model";
import { WorkflowRunDetailPanel } from "./workflow-run-detail-panel";
import { WorkflowPageHeader } from "./workflow-page-header";

export function WorkflowResultDetailPage() {
  const searchParams = useSearchParams();
  const runId = searchParams.get("run") || "";

  const [detail, setDetail] = useState<WorkflowRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    setError("");
    try {
      const data = await fetchWorkflowRunDetail(runId);
      setDetail(data);
    } catch (err) {
      setError(workflowErrorMessage(err, "读取运行详情失败"));
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!runId) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [runId, load]);

  return (
    <div className="relative flex-1 w-full h-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <div className="mx-auto max-w-5xl space-y-6">
        <WorkflowPageHeader
          title="运行结果详情"
          leading={
            <Button asChild variant="outline" className="h-9 bg-white px-3 text-slate-600">
              <Link href="/workflows/results">
                <ArrowLeft strokeWidth={1.5} className="mr-2 h-4 w-4" />
                返回运行记录
              </Link>
            </Button>
          }
          actions={<span className="font-mono text-xs text-slate-400">{runId || "—"}</span>}
        />

        {!runId ? (
          <Alert variant="destructive">
            <AlertDescription>缺少 run 参数</AlertDescription>
          </Alert>
        ) : loading && !detail ? (
          <div className="flex h-48 items-center justify-center text-sm text-slate-400">
            <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
            正在读取运行详情
          </div>
        ) : error && !detail ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : detail ? (
          <WorkflowRunDetailPanel detail={detail} error={error} />
        ) : null}
      </div>
    </div>
  );
}
