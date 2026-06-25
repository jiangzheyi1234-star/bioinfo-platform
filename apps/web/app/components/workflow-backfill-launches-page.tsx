"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, ArrowLeft, Loader2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { WorkflowPageHeader } from "./workflow-page-header";
import {
  cancelWorkflowBackfillLaunch,
  fetchWorkflowBackfillLaunch,
  fetchWorkflowBackfillLaunches,
} from "./workflow-backfill-api";
import { WorkflowBackfillLaunchControl } from "./workflow-backfill-launch-control";
import { WorkflowBackfillLaunchPanel } from "./workflow-backfill-launch-panel";
import type {
  WorkflowBackfillLaunch,
  WorkflowBackfillLaunchDetail,
} from "./workflow-backfill-model";
import { fetchWorkflowTriggers } from "./workflow-trigger-api";
import type { WorkflowTrigger } from "./workflow-trigger-model";
import { workflowErrorMessage } from "./workflows-page-model";

export function WorkflowBackfillLaunchesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const launchFromQuery = searchParams.get("launch") || "";

  const [launches, setLaunches] = useState<WorkflowBackfillLaunch[]>([]);
  const [selectedLaunchId, setSelectedLaunchId] = useState(launchFromQuery);
  const [detail, setDetail] = useState<WorkflowBackfillLaunchDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [cancelingLaunchId, setCancelingLaunchId] = useState("");
  const [backfillTriggers, setBackfillTriggers] = useState<WorkflowTrigger[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");

  const loadBackfillTriggers = useCallback(async (forceRefresh = false) => {
    try {
      const data = await fetchWorkflowTriggers({ forceRefresh });
      setBackfillTriggers((data.items || []).filter((trigger) => trigger.sourceType === "backfill"));
    } catch (err) {
      setError(workflowErrorMessage(err, "读取 backfill trigger 失败"));
    }
  }, []);

  const loadLaunches = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchWorkflowBackfillLaunches({ forceRefresh, limit: 50 });
      setLaunches(data.items || []);
    } catch (err) {
      setError(workflowErrorMessage(err, "读取回填批次失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (forceRefresh = false) => {
    if (!selectedLaunchId) {
      setDetail(null);
      return;
    }
    if (!forceRefresh) {
      setDetailLoading(true);
    }
    setDetailError("");
    try {
      const data = await fetchWorkflowBackfillLaunch(selectedLaunchId, { forceRefresh });
      setDetail(data);
      const { partitions: _partitions, ...launchSummary } = data;
      setLaunches((current) =>
        current.map((launch) => (launch.launchId === data.launchId ? { ...launch, ...launchSummary } : launch))
      );
    } catch (err) {
      setDetailError(workflowErrorMessage(err, "读取回填分区失败"));
    } finally {
      setDetailLoading(false);
    }
  }, [selectedLaunchId]);

  useEffect(() => {
    void loadBackfillTriggers();
    void loadLaunches();
  }, [loadBackfillTriggers, loadLaunches]);

  useEffect(() => {
    if (launchFromQuery && launchFromQuery !== selectedLaunchId) {
      setDetail(null);
      setSelectedLaunchId(launchFromQuery);
      return;
    }
    if (!selectedLaunchId && launches[0]?.launchId) {
      setDetail(null);
      setSelectedLaunchId(launches[0].launchId);
    }
  }, [launchFromQuery, launches, selectedLaunchId]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  useEffect(() => {
    if (!selectedLaunchId) return;
    const timer = window.setInterval(() => void loadDetail(true), 5000);
    return () => window.clearInterval(timer);
  }, [loadDetail, selectedLaunchId]);

  function selectLaunch(launchId: string) {
    setDetail(null);
    setSelectedLaunchId(launchId);
    const params = new URLSearchParams(searchParams.toString());
    params.set("launch", launchId);
    router.replace(`/workflows/results/backfills?${params.toString()}`, { scroll: false });
  }

  function refresh() {
    setNotice("");
    void loadBackfillTriggers(true);
    void loadLaunches(true);
    void loadDetail(true);
  }

  function backfillLaunched(launch: WorkflowBackfillLaunchDetail) {
    setNotice(`已启动回填批次 ${launch.launchId}`);
    setDetail(launch);
    const { partitions: _partitions, ...launchSummary } = launch;
    setLaunches((current) => {
      const withoutCurrent = current.filter((item) => item.launchId !== launch.launchId);
      return [{ ...launchSummary }, ...withoutCurrent];
    });
    setSelectedLaunchId(launch.launchId);
    router.replace(`/workflows/results/backfills?launch=${encodeURIComponent(launch.launchId)}`, { scroll: false });
    void loadLaunches(true);
  }

  async function cancelLaunch(launchId: string) {
    if (!launchId || cancelingLaunchId) return;
    const accepted = window.confirm(`请求取消回填批次 ${launchId} 下仍在活动或待提交状态的分区？`);
    if (!accepted) return;
    setCancelingLaunchId(launchId);
    setNotice("");
    setDetailError("");
    try {
      const result = await cancelWorkflowBackfillLaunch(launchId);
      setNotice(
        `已请求取消 ${result.requestedCancelCount ?? 0} 个分区运行，标记 ${result.pendingCancelRequestedCount ?? 0} 个待提交分区，跳过 ${result.skippedPartitionCount ?? 0} 个分区。`
      );
      if (result.detail) {
        setDetail(result.detail);
      }
      await loadLaunches(true);
      await loadDetail(true);
    } catch (err) {
      setDetailError(workflowErrorMessage(err, "请求取消回填失败"));
    } finally {
      setCancelingLaunchId("");
    }
  }

  return (
    <div className="relative flex-1 h-full w-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <div className="mx-auto max-w-6xl space-y-6">
        <WorkflowPageHeader
          title="回填批次"
          leading={
            <Button asChild variant="outline" className="h-9 bg-white px-3 text-slate-600">
              <Link href="/workflows/results">
                <ArrowLeft strokeWidth={1.5} className="mr-2 h-4 w-4" />
                返回运行记录
              </Link>
            </Button>
          }
          actions={
            <div className="flex items-center gap-2">
              <Button asChild variant="outline" className="h-9 bg-white px-3 text-slate-600">
                <Link href="/workflows/results/triggers">
                  <Activity strokeWidth={1.5} className="mr-2 h-4 w-4" />
                  触发器事件
                </Link>
              </Button>
              <span className="font-mono text-xs text-slate-400">{selectedLaunchId || "—"}</span>
            </div>
          }
        />

        {loading && launches.length === 0 && !error ? (
          <div className="flex h-48 items-center justify-center text-sm text-slate-400">
            <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
            正在读取回填批次
          </div>
        ) : error && launches.length === 0 ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : (
          <>
            <WorkflowBackfillLaunchControl
              onLaunched={backfillLaunched}
              triggers={backfillTriggers}
            />
            <WorkflowBackfillLaunchPanel
              cancelingLaunchId={cancelingLaunchId}
              detail={detail}
              detailLoading={detailLoading}
              error={error || detailError}
              launches={launches}
              loading={loading}
              notice={notice}
              onCancelLaunch={cancelLaunch}
              onRefresh={refresh}
              onSelectLaunch={selectLaunch}
              selectedLaunchId={selectedLaunchId}
            />
          </>
        )}
      </div>
    </div>
  );
}
